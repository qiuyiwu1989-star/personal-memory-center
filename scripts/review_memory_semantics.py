#!/usr/bin/env python3
"""Freeze/record independent extraction reviews; no model, DB, network or approval."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

VERSION = 'claim-semantic-review-v1'
COVERAGE_VERSION = 'coverage-v2'
KINDS = {'identity', 'preference', 'relationship', 'decision', 'plan', 'event', 'claim', 'suggestion'}
DIMENSIONS = ('speaker', 'commitment', 'condition', 'time', 'source_alignment')
CATEGORIES = {'owner_decision', 'third_party', 'conditional', 'correction', 'need_vs_plan'}
VERDICTS = {'passed', 'failed', 'ambiguous', 'not_run'}
REPO = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _coverage_contract(package, case_ids):
    if 'coverage_contract' not in package:
        return None
    contract = package['coverage_contract']
    if not isinstance(contract, dict) or contract.get('version') != COVERAGE_VERSION:
        raise ValueError('Explicit supported coverage contract version required')
    cases = contract.get('cases')
    if not isinstance(cases, dict) or set(cases) != set(case_ids):
        raise ValueError('Exact coverage contract case manifest required')
    for case in cases.values():
        units = case.get('units') if isinstance(case, dict) else None
        if not isinstance(units, list) or not units:
            raise ValueError('Nonempty source coverage units required')
        ids = []
        for unit in units:
            if not isinstance(unit, dict) or not _text(unit.get('unit_id')):
                raise ValueError('Unique nonempty source unit identifiers required')
            ids.append(unit['unit_id'])
            if (unit.get('disposition') not in ('must_capture', 'archive_only', 'ambiguous')
                    or not _text(unit.get('rationale')) or not _text(unit.get('source_ref'))):
                raise ValueError('Explicit source disposition, rationale and source_ref required')
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate source coverage unit')
    return contract


def validate(package):
    if package.get('data_kind') not in ('synthetic_development', 'real_holdout'):
        raise ValueError('Explicit development/holdout provenance required')
    if type(package.get('independent_holdout')) is not bool:
        raise ValueError('Explicit holdout independence declaration required')
    if package['data_kind'] == 'synthetic_development' and package['independent_holdout']:
        raise ValueError('Development probes cannot be independent holdout')
    method = package.get('method', {})
    if not _text(method.get('version')) or not re.fullmatch('[0-9a-f]{64}', method.get('sha256', '')):
        raise ValueError('Frozen extraction method version/hash required')
    expected = package.get('expected_case_ids', [])
    cases = package.get('cases', [])
    if not expected or any(not _text(x) for x in expected) or len(set(expected)) != len(expected):
        raise ValueError('Unique nonempty expected case manifest required')
    ids = [c.get('case_id') for c in cases]
    if len(set(ids)) != len(ids) or set(ids) != set(expected):
        raise ValueError('Exact case coverage required, including not-run cases')
    contract = _coverage_contract(package, expected)
    for case in cases:
        if case.get('category') not in CATEGORIES or not isinstance(case.get('source'), dict) or not case.get('source'):
            raise ValueError('Category and source JSON required')
        rubric = case.get('rubric', {})
        if set(rubric) != set(DIMENSIONS) or any(not _text(v) for v in rubric.values()):
            raise ValueError('Five independent semantic rubric dimensions required')
        output = case.get('output', {})
        if output.get('execution_status') not in ('completed', 'failed', 'not_run'):
            raise ValueError('Explicit model execution state required')
        if output.get('delivery_status') not in ('accepted_candidate', 'rejected', 'not_attempted', 'not_run'):
            raise ValueError('Separate pipeline delivery state required')
        if output['delivery_status'] == 'rejected' and not _text(output.get('delivery_failure')):
            raise ValueError('Rejected delivery must retain failure reason')
        if output['execution_status'] != 'completed' and output['delivery_status'] == 'accepted_candidate':
            raise ValueError('Incomplete generation cannot be accepted delivery')
        claims = output.get('claims', [])
        if not isinstance(claims, list):
            raise ValueError('Claim list required')
        claim_ids = [c.get('claim_id') for c in claims]
        if any(not _text(x) for x in claim_ids) or len(set(claim_ids)) != len(claim_ids):
            raise ValueError('Unique claim identifiers required')
        if any(not _text(c.get('statement')) for c in claims):
            raise ValueError('Candidate statements required')
        if output['execution_status'] == 'not_run' and claims:
            raise ValueError('Not-run output cannot contain generated claims')
        if contract and any(not isinstance(c.get('kind'), str) or c['kind'] not in KINDS for c in claims):
            raise ValueError('Coverage-v2 candidates require explicit legal kind')
    return {'case_ids': expected, 'categories': sorted({c['category'] for c in cases})}


def freeze(package):
    coverage = validate(package)
    return {'review_method': COVERAGE_VERSION if package.get('coverage_contract') else VERSION, 'review_tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'package_sha256': digest(package),
            'method': package['method'], 'coverage': coverage,
            'quality_approved': False, 'status': 'frozen_not_run', 'model_calls': 0}


def _labels(row):
    """Absent dimensions remain not_run; never derive semantics from lexical checks."""
    if row is None:
        return {d: {'verdict': 'not_run', 'rationale': ''} for d in DIMENSIONS}
    if not isinstance(row, dict) or set(row) - set(DIMENSIONS):
        raise ValueError('Unknown semantic review dimension')
    result = {}
    for dimension in DIMENSIONS:
        label = row.get(dimension, {'verdict': 'not_run', 'rationale': ''})
        if not isinstance(label, dict) or label.get('verdict') not in VERDICTS:
            raise ValueError('Explicit semantic verdict required')
        if label['verdict'] != 'not_run' and not _text(label.get('rationale')):
            raise ValueError('Reviewed labels require rationale')
        result[dimension] = {'verdict': label['verdict'], 'rationale': label.get('rationale', '')}
    return result


def _aggregate(labels):
    states = {label['verdict'] for label in labels}
    return next((v for v in ('failed', 'not_run', 'ambiguous') if v in states), 'passed')


def _unit_coverage(case, units, submitted):
    """Validate mapping records; submitted semantic labels remain attestations."""
    if submitted is None:
        submitted = {}
    if not isinstance(submitted, dict) or set(submitted) - {'generated', 'delivered'}:
        raise ValueError('Unknown coverage review stage')
    expected = {u['unit_id'] for u in units}
    claim_ids = {c['claim_id'] for c in case['output'].get('claims', [])}
    stages = {}
    for stage in ('generated', 'delivered'):
        rows = submitted.get(stage, [])
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError('Coverage review stage requires mapping list')
        indexed = {}
        for row in rows:
            unit_id = row.get('unit_id')
            if not _text(unit_id) or unit_id not in expected or unit_id in indexed:
                raise ValueError('Duplicate/unknown coverage reviewed unit')
            verdict = row.get('verdict')
            refs = row.get('claim_ids')
            if verdict not in ('captured', 'omitted', 'ambiguous', 'not_run') or not _text(row.get('rationale')):
                raise ValueError('Explicit coverage verdict and rationale required')
            if (not isinstance(refs, list) or any(not _text(r) for r in refs)
                    or len(set(refs)) != len(refs) or set(refs) - claim_ids):
                raise ValueError('Unique existing coverage claim references required')
            if (verdict == 'captured' and not refs) or (verdict in ('omitted', 'not_run') and refs):
                raise ValueError('Coverage verdict and claim references inconsistent')
            if case['output']['execution_status'] != 'completed' and verdict != 'not_run':
                raise ValueError('Incomplete generation cannot be scored as coverage output')
            if verdict == 'captured':
                if stage == 'delivered' and case['output']['delivery_status'] != 'accepted_candidate':
                    raise ValueError('Unaccepted delivery cannot have captured coverage')
            indexed[unit_id] = row
        stages[stage] = [dict(indexed.get(u['unit_id'], {
            'unit_id': u['unit_id'], 'verdict': 'not_run',
            'rationale': 'No coverage review submitted.', 'claim_ids': []}), disposition=u['disposition']) for u in units]
    required = [r for rows in stages.values() for r in rows if r['disposition'] == 'must_capture']
    verdict = _aggregate([{'verdict': {'captured': 'passed', 'omitted': 'failed',
        'ambiguous': 'ambiguous', 'not_run': 'not_run'}[r['verdict']]} for r in required])
    return {'version': COVERAGE_VERSION, 'stages': stages, 'verdict': verdict,
            'review_complete': all(r['verdict'] != 'not_run' for rows in stages.values() for r in rows),
            'source_units_sha256': digest(units)}


def score(package, review):
    coverage = validate(package)
    if review.get('package_sha256') != digest(package):
        raise ValueError('Frozen source/output/rubric/method receipt mismatch')
    reviewer = review.get('reviewer', {})
    if reviewer.get('kind') not in ('human', 'independent_agent', 'synthetic_test') or not _text(reviewer.get('id')) or type(reviewer.get('independent')) is not bool:
        raise ValueError('Explicit reviewer identity/type/independence declaration required')
    rows = review.get('cases', [])
    indexed = {r.get('case_id'): r for r in rows}
    if len(indexed) != len(rows) or set(indexed) - set(coverage['case_ids']):
        raise ValueError('Duplicate/unknown reviewed cases')
    results = []
    contract = package.get('coverage_contract')
    for case in package['cases']:
        row = indexed.get(case['case_id'], {})
        submitted = row.get('claims', [])
        claims = {r.get('claim_id'): r for r in submitted}
        expected = {c['claim_id'] for c in case['output'].get('claims', [])}
        if len(claims) != len(submitted) or set(claims) - expected:
            raise ValueError('Duplicate/unknown reviewed claims')
        # Case labels also examine omissions and appropriate abstention for zero candidates.
        case_labels = _labels(row.get('dimensions'))
        items = [{'claim_id': c['claim_id'], 'dimensions': _labels(claims.get(c['claim_id'], {}).get('dimensions'))}
                 for c in case['output'].get('claims', [])]
        labels = list(case_labels.values()) + [v for item in items for v in item['dimensions'].values()]
        if case['output']['execution_status'] != 'completed':
            if any(label['verdict'] != 'not_run' for label in labels):
                raise ValueError('Incomplete generation cannot be scored as semantic output')
            verdict = 'not_run'
        else:
            verdict = _aggregate(labels)
        unit_review = None
        if contract:
            unit_review = _unit_coverage(case, contract['cases'][case['case_id']]['units'], row.get('coverage'))
            verdict = _aggregate([{'verdict': verdict}, {'verdict': unit_review['verdict']}])
        result = {'case_id': case['case_id'], 'category': case['category'],
                        'execution_status': case['output']['execution_status'],
                        'delivery_status': case['output']['delivery_status'],
                        'delivery_failure': case['output'].get('delivery_failure'),
                        'source_sha256': digest(case['source']), 'output_sha256': digest(case['output']),
                        'rubric_sha256': digest(case['rubric']), 'verdict': verdict,
                        'dimensions': case_labels, 'claims': items}
        if unit_review is not None:
            result['unit_coverage'] = unit_review
        results.append(result)
    counts = {v: sum(r['verdict'] == v for r in results) for v in sorted(VERDICTS)}
    complete = counts['passed'] == len(results)
    ready = (complete and package['data_kind'] == 'real_holdout' and package['independent_holdout']
             and reviewer['kind'] == 'human' and reviewer['independent']
             and set(coverage['categories']) == CATEGORIES
             and all(c['output']['delivery_status'] == 'accepted_candidate' for c in package['cases'])
             and (not contract or all(r['unit_coverage']['review_complete'] for r in results)))
    return {'review_method': COVERAGE_VERSION if contract else VERSION, 'review_tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'package_sha256': digest(package), 'review_input_sha256': digest(review),
            'method': package['method'], 'data_kind': package['data_kind'],
            'reviewer': reviewer, 'coverage': coverage, 'counts': counts, 'items': results,
            'status': 'ready_for_owner_review' if ready else 'review_incomplete_or_provisional',
            'quality_approved': False, 'production_gate_changed': False, 'model_calls': 0,
            'limitation': 'Submitted labels and independence are attestations, not authenticated approval or measured recall.'}


def save_receipt(result, target, previous=None):
    target = Path(target).resolve()
    if target == REPO or REPO in target.parents:
        raise ValueError('Review receipts must remain outside public repository')
    prior = None
    if previous is not None:
        previous = Path(previous).resolve()
        if previous == REPO or REPO in previous.parents:
            raise ValueError('Prior private receipts must remain outside public repository')
        # Preserve prior bytes; hash chaining records lineage, not semantic authorization.
        prior = hashlib.sha256(previous.read_bytes()).hexdigest()
    receipt = dict(result, recorded_at=datetime.now(timezone.utc).isoformat(), previous_receipt_sha256=prior)
    encoded = json.dumps(receipt, ensure_ascii=False, indent=2).encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    package = json.loads(args.package.read_text())
    result = score(package, json.loads(args.review.read_text())) if args.review else freeze(package)
    receipt_hash = save_receipt(result, args.output, args.previous)
    print(json.dumps({'status': result['status'], 'quality_approved': False,
                      'counts': result.get('counts'), 'receipt_sha256': receipt_hash}))


if __name__ == '__main__':
    main()

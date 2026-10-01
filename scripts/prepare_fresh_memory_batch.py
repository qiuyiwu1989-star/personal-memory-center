"""Private, no-model fresh-message selection and static candidate checks.

Fresh means absent from supplied receipts, never proof of global/model novelty.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.memory_center.claude import messages
from pipeline.memory_center.extraction_input import prepare_request
from pipeline.memory_center.model import PROMPT, PROMPT_VERSION


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def message_ids(data):
    found = set()
    if isinstance(data, dict):
        if isinstance(data.get('id'), str) and 'role' in data:
            found.add(data['id'].split('#', 1)[0])
        for value in data.values():
            found.update(message_ids(value))
    elif isinstance(data, list):
        for value in data:
            found.update(message_ids(value))
    return found


def select(conversations, previous, receipts, wanted, max_output_tokens=2048):
    if not wanted or len(wanted) != len(set(wanted)):
        raise ValueError('Select unique original message IDs')
    excluded_conversations = {p['conversation_id'] for p in previous if p['state'] != 'planned'}
    seen = set().union(*(message_ids(r) for r in receipts)) if receipts else set()
    if seen.intersection(wanted):
        raise ValueError('Message was present in a supplied prior receipt')
    found = {}; receipt = []
    for conversation in conversations:
        if conversation['uuid'] in excluded_conversations:
            continue
        for message in messages(conversation):
            original = message['id'].split('#', 1)[0]
            if original not in wanted:
                continue
            if original in found:
                raise ValueError('Select an unsplit, unique visible message')
            if len(message['text']) > 2000:
                raise ValueError('Fresh small-batch message exceeds 2000 characters')
            found[original] = message
            receipt.append({'original_message_id': original, 'conversation_id': conversation['uuid'],
                            'message_sha256': digest(message), 'receipt_unseen': True,
                            'historical_applied_conversation_excluded': True})
    if set(found) != set(wanted):
        raise ValueError('Selected message missing, split, or in a previously applied conversation')
    cases = []; allowances = []
    for index, original in enumerate(wanted):
        case = {'sample_index': index, 'source_type': 'conversation', 'messages': [found[original]]}
        request, spans, routes = prepare_request(case['source_type'], case['messages'])
        allowances.append(len(json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode())
                          + len(PROMPT.encode()) + max_output_tokens + 1024 if spans else 0)
        cases.append(case)
    return {'version': PROMPT_VERSION, 'prompt': PROMPT, 'max_output_tokens': max_output_tokens,
            'maximum_total_additional_tokens': 30000, 'cases': cases,
            'preflight': {'case_count': len(cases), 'reservation_allowances': allowances,
                          'sum_simultaneous_reservations': sum(allowances),
                          'sequential_settlement_required': True, 'model_calls': 0,
                          'selection_receipts': receipt,
                          'prior_receipts_sha256': [digest(r) for r in receipts],
                          'previous_metadata_sha256': digest(previous),
                          'novelty_scope': 'supplied prior inputs and non-planned historical conversation metadata only',
                          'quality_approved': False, 'production_dispatch_enabled': False}}


def candidate_gate(case, claims):
    """Check static fidelity only; semantic entailment always requires review."""
    messages_by_id = {m['id']: m for m in case['messages']}; reasons = []; seen = set()
    for index, claim in enumerate(claims):
        source = messages_by_id.get(claim.get('message_id'))
        quote = claim.get('quote'); statement = claim.get('statement', '')
        failures = []
        if not source or not isinstance(quote, str) or not quote or quote not in source['text']:
            failures.append('exact_visible_quote_required')
        if source and source['role'] != 'user':
            failures.append('non_user_source_not_personal_evidence')
        if claim.get('status') != 'source_reported':
            failures.append('candidate_status_required')
        if claim.get('quality_approved') or claim.get('owner_confirmed') or claim.get('verified'):
            failures.append('no_auto_confirmation')
        if not isinstance(statement, str) or not re.search(r'[\u4e00-\u9fff]', statement):
            failures.append('chinese_display_required')
        if source and source.get('created_at') and source['created_at'][:10] not in statement:
            failures.append('historical_source_date_required')
        if source and source.get('source_title') and source['source_title'] not in statement:
            failures.append('historical_conversation_scope_required')
        key = (claim.get('message_id'), statement)
        if key in seen:
            failures.append('duplicate_candidate')
        seen.add(key)
        if failures:
            reasons.append({'claim_index': index, 'failures': failures})
    return {'static_gate_passed': not reasons, 'failures': reasons,
            'semantic_review_required': True, 'current_validity': 'unknown',
            'identity_merge_approved': False, 'quality_approved': False,
            'production_dispatch_enabled': False}


def write_private(target, payload):
    root = Path(__file__).resolve().parents[1]; target = Path(target).resolve()
    if target == root or root in target.parents:
        raise ValueError('Private batch must remain outside public repository')
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with target.open('x') as file:
        target.chmod(0o600); json.dump(payload, file, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--conversations', required=True)
    parser.add_argument('--previous-metadata', required=True)
    parser.add_argument('--prior-input', action='append', default=[])
    parser.add_argument('--message-id', action='append', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    raw = Path(args.conversations).read_bytes()
    payload = select(json.loads(raw), json.loads(Path(args.previous_metadata).read_text()),
                     [json.loads(Path(p).read_text()) for p in args.prior_input], args.message_id)
    payload['archive_sha256'] = hashlib.sha256(raw).hexdigest()
    write_private(args.output, payload)
    print(json.dumps({k: payload['preflight'][k] for k in ('case_count', 'reservation_allowances',
                                                       'model_calls', 'quality_approved')}))


if __name__ == '__main__':
    main()

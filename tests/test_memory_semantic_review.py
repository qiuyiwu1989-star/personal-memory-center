"""Synthetic artifacts only; these tests never score private model output."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.review_memory_semantics import CATEGORIES, DIMENSIONS, digest, freeze, save_receipt, score


def package():
    return {'data_kind': 'synthetic_development', 'independent_holdout': False,
            'method': {'version': 'synthetic-method-v1', 'sha256': 'a' * 64},
            'expected_case_ids': sorted(CATEGORIES),
            'cases': [{'case_id': category, 'category': category,
                       'source': {'synthetic': True, 'text': 'Synthetic speaker requests source preservation.'},
                       'output': {'execution_status': 'completed', 'delivery_status': 'accepted_candidate', 'claims': [
                           {'claim_id': 'synthetic-claim', 'statement': 'Synthetic speaker requests source preservation.'}]},
                       'rubric': {d: 'Independent reviewer must evaluate synthetic ' + d for d in DIMENSIONS}}
                      for category in sorted(CATEGORIES)]}


def review(p, kind='synthetic_test'):
    labels = {d: {'verdict': 'passed', 'rationale': 'Synthetic test label, not real quality evidence.'}
              for d in DIMENSIONS}
    return {'package_sha256': digest(p), 'reviewer': {'id': 'synthetic-reviewer', 'kind': kind, 'independent': True},
            'cases': [{'case_id': c['case_id'], 'dimensions': copy.deepcopy(labels),
                       'claims': [{'claim_id': x['claim_id'], 'dimensions': copy.deepcopy(labels)}
                                  for x in c['output']['claims']]} for c in p['cases']]}


class SemanticReviewTest(unittest.TestCase):
    def test_synthetic_complete_cannot_approve_or_be_ready(self):
        p = package(); r = review(p); original = copy.deepcopy((p, r))
        result = score(p, r)
        self.assertEqual(result['counts']['passed'], 5)
        self.assertFalse(result['quality_approved'])
        self.assertFalse(result['production_gate_changed'])
        self.assertNotEqual(result['status'], 'ready_for_owner_review')
        self.assertEqual((p, r), original)
        self.assertEqual(len(result['items'][0]['source_sha256']), 64)

    def test_missing_reviews_dimensions_claims_remain_not_run(self):
        p = package(); r = review(p)
        r['cases'].pop()
        del r['cases'][0]['dimensions']['speaker']
        r['cases'][1]['claims'] = []
        result = score(p, r)
        self.assertEqual(result['counts']['not_run'], 3)
        self.assertEqual(result['counts']['passed'], 2)

    def test_failed_and_ambiguous_are_distinct_and_block_readiness(self):
        p = package(); r = review(p)
        r['cases'][0]['claims'][0]['dimensions']['commitment']['verdict'] = 'ambiguous'
        r['cases'][1]['dimensions']['speaker']['verdict'] = 'failed'
        result = score(p, r)
        self.assertEqual(result['counts']['ambiguous'], 1)
        self.assertEqual(result['counts']['failed'], 1)
        self.assertFalse(result['quality_approved'])

    def test_zero_candidates_requires_case_semantic_review(self):
        p = package(); p['cases'][0]['output']['claims'] = []
        r = review(p); del r['cases'][0]['dimensions']
        self.assertEqual(score(p, r)['items'][0]['verdict'], 'not_run')
        r = review(p)
        self.assertEqual(score(p, r)['items'][0]['verdict'], 'passed')
        self.assertFalse(score(p, r)['quality_approved'])

    def test_failed_or_unrun_output_not_converted_to_empty_pass(self):
        for state in ('failed', 'not_run'):
            p = package(); p['cases'][0]['output'] = {'execution_status': state, 'delivery_status': 'not_run', 'claims': []}
            r = review(p)
            with self.assertRaisesRegex(ValueError, 'Incomplete generation'):
                score(p, r)
            r['cases'].pop(0)
            self.assertEqual(score(p, r)['items'][0]['verdict'], 'not_run')
        p = package(); p['cases'][0]['output'].update(execution_status='not_run', delivery_status='not_run')
        with self.assertRaisesRegex(ValueError, 'generated claims'):
            freeze(p)

    def test_freeze_rejects_missing_cases_rubric_duplicate_claims_and_method(self):
        for change in (
            lambda p: p['cases'].pop(),
            lambda p: p['cases'][0]['rubric'].pop('time'),
            lambda p: p['cases'][0]['output']['claims'].append(copy.deepcopy(p['cases'][0]['output']['claims'][0])),
            lambda p: p['method'].update(sha256='unfrozen'),
        ):
            p = package(); change(p)
            with self.assertRaises(ValueError): freeze(p)

    def test_frozen_changes_or_unknown_reviews_rejected(self):
        p = package(); r = review(p); p['cases'][0]['source']['text'] += ' changed'
        with self.assertRaisesRegex(ValueError, 'receipt mismatch'): score(p, r)
        p = package(); r = review(p); r['cases'][0]['claims'][0]['claim_id'] = 'invented'
        with self.assertRaisesRegex(ValueError, 'unknown reviewed claims'): score(p, r)
        r = review(p); r['cases'][0]['dimensions']['speaker']['rationale'] = ''
        with self.assertRaisesRegex(ValueError, 'rationale'): score(p, r)

    def test_only_complete_declared_independent_human_holdout_ready_never_approved(self):
        # Synthetic test of metadata gating, not an actual holdout evaluation.
        p = package(); p.update(data_kind='real_holdout', independent_holdout=True)
        for kind, ready in (('human', True), ('independent_agent', False), ('synthetic_test', False)):
            result = score(p, review(p, kind))
            self.assertEqual(result['status'] == 'ready_for_owner_review', ready)
            self.assertFalse(result['quality_approved'])
        p['independent_holdout'] = False
        self.assertNotEqual(score(p, review(p, 'human'))['status'], 'ready_for_owner_review')

    def test_generated_but_rejected_delivery_retains_claims_and_cannot_be_ready(self):
        p = package(); p.update(data_kind='real_holdout', independent_holdout=True)
        p['cases'][0]['output'].update(delivery_status='rejected', delivery_failure='source_span_contract')
        result = score(p, review(p, 'human'))
        self.assertEqual(result['items'][0]['execution_status'], 'completed')
        self.assertEqual(result['items'][0]['delivery_failure'], 'source_span_contract')
        self.assertEqual(len(result['items'][0]['claims']), 1)
        self.assertEqual(result['items'][0]['verdict'], 'passed')
        self.assertNotEqual(result['status'], 'ready_for_owner_review')
        self.assertFalse(result['quality_approved'])

    def test_private_exclusive_receipts_preserve_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.json'; second = Path(directory) / 'second.json'
            result = freeze(package()); save_receipt(result, first)
            original = first.read_bytes()
            with self.assertRaises(FileExistsError): save_receipt(result, first)
            save_receipt(result, second, first)
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(json.loads(second.read_text())['previous_receipt_sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(ValueError, 'outside public'):
            save_receipt(result, Path(__file__).parent / 'not-created.json')


if __name__ == '__main__': unittest.main()

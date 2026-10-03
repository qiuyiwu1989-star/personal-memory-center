"""Explicit synthetic development contracts; no semantic holdout claim."""
import copy
import json
import unittest
from scripts.evaluate_memory_quality_contract import FIXTURE, evaluate
from pipeline.memory_center.extraction_quality import review

class MemoryQualityContractTest(unittest.TestCase):
    def setUp(self):self.contract=json.loads(FIXTURE.read_text())

    def test_frozen_probes_cover_five_boundaries_without_semantic_approval(self):
        before=copy.deepcopy(self.contract);result=evaluate(self.contract)
        self.assertEqual(result['total'],17)
        self.assertEqual(result['deterministic_passed'],17)
        self.assertEqual(self.contract,before)
        self.assertEqual(result['contract_sha256'],'83c9ec2e23be25ed216b872450370d4b45a08b29b8c10bde91f802451a235967')
        self.assertEqual(result['model_calls'],0)
        self.assertFalse(result['quality_approved'])
        self.assertTrue(all(row['semantic_judgment']=='not_run' for row in result['items']))
        self.assertEqual(result['historical_case5'],'not_retested_not_passed')

    def test_expected_contract_mismatch_is_failure_not_new_gold(self):
        self.contract['cases'][0]['expected_deterministic']['guard_reject']=True
        result=evaluate(self.contract)
        self.assertEqual(result['deterministic_passed'],16)
        self.assertFalse(result['items'][0]['deterministic_contract_passed'])

    def test_missing_labels_or_fake_historical_pass_rejected(self):
        for key,value in [('synthetic',False),('annotation_status','human_reviewed'),('historical_case5','passed'),('real_model_evaluation','passed')]:
            contract=copy.deepcopy(self.contract);contract[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):evaluate(contract)

    def test_need_hint_is_metadata_only_and_does_not_block_faithful_plan(self):
        cases={c['case_id']:c for c in self.contract['cases']}
        claims=[cases[k]['probe_claim'] for k in ('need-plan-strengthening','need-faithful','need-explicit-plan')]
        before=copy.deepcopy(claims);result=review(claims)
        self.assertEqual(claims,before)
        self.assertIn('need_to_plan_review',result['items'][0]['codes'])
        self.assertNotIn('need_to_plan_review',result['items'][1]['codes'])
        self.assertNotIn('need_to_plan_review',result['items'][2]['codes'])
        self.assertEqual(result['items'][0]['disposition'],'review_required')
        self.assertTrue(all(f['signal_only'] for row in result['items'] for f in row['findings']))

    def test_quoted_adoption_does_not_clear_third_party_review(self):
        quote='顾问建议采用 SyntheticAtlas，顾问说：“我已决定采用。”'
        claim={'statement':'用户已决定采用 SyntheticAtlas。','quote':quote}
        self.assertIn('third_party_advice_review',review([claim])['items'][0]['codes'])

    def test_stale_correction_probe_records_lexical_blind_spot(self):
        result=evaluate(self.contract)
        stale=next(r for r in result['items'] if r['case_id']=='correction-stale-counterexample')
        self.assertFalse(stale['guard_reject'])
        self.assertEqual(stale['semantic_judgment'],'not_run')
        self.assertFalse(stale['semantics_verified'])
        self.assertIn('stale corrections',result['limitations'][1])

if __name__=='__main__':unittest.main()

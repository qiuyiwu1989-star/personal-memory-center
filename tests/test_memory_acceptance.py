"""Only explicitly synthetic acceptance fixtures; no model or production writes."""
import json
from pathlib import Path
import unittest
from pipeline.memory_center.evaluation import acceptance_check,suite_gate

class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.cases=json.loads((Path(__file__).parent/'fixtures/memory-acceptance-synthetic.json').read_text())['cases']

    def run_for(self,case,empty=False):
        claims=[] if empty else [{'statement':f['description'],'quote':case['messages'][0]['text']} for f in case['required_facts']]
        acceptance={'required_matches':{f['id']:{'verdict':'pass','reason':'Synthetic matching fact reviewed','claim_indices':[i]} for i,f in enumerate(case['required_facts'])},
                    'forbidden_checks':{f['id']:{'verdict':'pass','reason':'Synthetic forbidden content absent'} for f in case['forbidden_facts']}}
        acceptance.update({key:{'verdict':'pass','reason':'Synthetic output reviewed'} for key in ('no_unexpected_claims','no_duplicate_claims')})
        review=dict.fromkeys(('semantic_support','speaker_attribution','time_handling','scope_handling','durable_value'),'pass')
        review['acceptance']=acceptance
        return {'sample_index':case['sample_index'],'version':'synthetic-v1','max_output_tokens':1024,'validation':'passed','claims':claims,'review':review}

    def test_complete_fixture_ready_does_not_approve(self):
        result=suite_gate([c['sample_index'] for c in self.cases],[self.run_for(c) for c in self.cases],'synthetic-v1',1024,self.cases)
        self.assertTrue(result['ready_for_owner_quality_decision'])
        self.assertFalse(result['quality_approved']);self.assertFalse(result['production_dispatch_enabled'])

    def test_empty_output_cannot_pass_required_configuration(self):
        c=self.cases[3];run=self.run_for(c,empty=True)
        check=acceptance_check(c,run)
        self.assertEqual(check['missing_required'],['configuration']);self.assertFalse(check['acceptance_passed'])
        result=suite_gate([4],[run],'synthetic-v1',1024,[c])
        self.assertEqual(result['omission_cases'],[4]);self.assertFalse(result['ready_for_owner_quality_decision'])

    def test_missing_fact_review_and_contract_block(self):
        c=self.cases[0];run=self.run_for(c)
        del run['review']['acceptance']['required_matches']['identity']
        self.assertEqual(acceptance_check(c,run)['pending'],['identity'])
        self.assertEqual(suite_gate([1],[run],'synthetic-v1',1024)['acceptance_pending_cases'],[1])

    def test_bad_locator_is_omission_not_semantic_success(self):
        c=self.cases[0];run=self.run_for(c)
        for bad in ([True],[99],[{}],[-1],[0,0],[]):
            run['review']['acceptance']['required_matches']['identity']['claim_indices']=bad
            self.assertFalse(acceptance_check(c,run)['acceptance_passed'])

    def test_duplicate_or_forbidden_claim_blocks(self):
        c=self.cases[6];run=self.run_for(c)
        run['review']['acceptance']['no_duplicate_claims']['verdict']='fail'
        self.assertIn('no_duplicate_claims',acceptance_check(c,run)['failures'])
        run=self.run_for(self.cases[5]);run['review']['acceptance']['forbidden_checks']['assistant']['verdict']='fail'
        self.assertEqual(acceptance_check(self.cases[5],run)['failures'],['assistant'])

    def test_negative_empty_can_pass_only_with_explicit_review(self):
        c=self.cases[9];run=self.run_for(c,empty=True)
        self.assertTrue(acceptance_check(c,run)['acceptance_passed'])
        run['review']['acceptance']['forbidden_checks']['expanded']['reason']=''
        self.assertFalse(acceptance_check(c,run)['acceptance_passed'])

    def test_duplicate_or_wrong_contract_rejected(self):
        c=self.cases[0];run=self.run_for(c)
        with self.assertRaises(ValueError):suite_gate([1],[run],'synthetic-v1',1024,[c,c])
        with self.assertRaises(ValueError):suite_gate([2],[run],'synthetic-v1',1024,[c])

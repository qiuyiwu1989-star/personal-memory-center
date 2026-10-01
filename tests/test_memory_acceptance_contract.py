import copy
import importlib.util
import json
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('acceptance_eval',Path(__file__).resolve().parents[1]/'scripts/evaluate_memory_acceptance.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class AcceptanceContractTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((Path(__file__).parent/'fixtures/synthetic-memory-acceptance-v1.json').read_text())
        self.r={'contract_sha256':m.digest(self.c),'answer_judge_status':'not_run','baselines':{b:[{'task_id':t['task_id'],'query':t['query'],'retrieved_ids':t['targets'][b]} for t in self.c['tasks']] for b in m.BASELINES}}
    def test_frame_has_30_and_no_answers_claimed(self):
        self.assertEqual(m.validate(self.c),{'tasks':30,'conversations':10,'development_tasks':12,'test_tasks':18})
        result=m.score(self.c,self.r)
        self.assertFalse(result['quality_approved'])
        self.assertEqual(result['baselines']['archive']['summary']['test']['answers_judged'],0)
        self.assertEqual(result['baselines']['archive']['summary']['test']['recall_at_k'],1)
        self.assertIsNone(result['baselines']['archive']['tasks'][2]['recall_at_k'])
    def test_receipt_query_and_identity_drift_rejected(self):
        for action in ('receipt','query','id'):
            r=copy.deepcopy(self.r)
            if action=='receipt':r['contract_sha256']='different'
            if action=='query':r['baselines']['archive'][0]['query']='changed'
            if action=='id':r['baselines']['archive'][0]['retrieved_ids']=['unknown']
            with self.assertRaises(ValueError):m.score(self.c,r)
    def test_conversation_leakage_rejected(self):
        c=copy.deepcopy(self.c);c['tasks'][0]['split']='test'
        with self.assertRaises(ValueError):m.validate(c)
    def test_answer_score_independent_of_perfect_retrieval(self):
        r=copy.deepcopy(self.r);r['answer_judge_status']='synthetic_fixture'
        row=r['baselines']['archive'][0]
        row.update(answer='合成错误答案',answer_judgment={'correct':False,'attribution_correct':True,'time_correct':True,'citations_supported':True,'abstained':False,'rationale':'Synthetic reviewer marks wrong conclusion despite correct evidence retrieval.'})
        scored=m.score(self.c,r)['baselines']['archive']['summary']['development']
        self.assertEqual(scored['recall_at_k'],1)
        self.assertEqual(scored['answers_passed'],0)
    def test_not_run_cannot_claim_answer(self):
        self.r['baselines']['archive'][0]['answer_judgment']={}
        with self.assertRaises(ValueError):m.score(self.c,self.r)

if __name__=='__main__':unittest.main()

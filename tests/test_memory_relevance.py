"""All cases explicitly synthetic. Offline scoring must fail closed on drift."""
import copy
import unittest
from pipeline.memory_center.relevance import score


class RelevanceTest(unittest.TestCase):
    def fixture(self):
        contract = {'annotation_status':'agent_review_provisional','input_sha256':'synthetic-i',
                    'results_sha256':'synthetic-r', 'corpus_record_ids':['a','b'],
                    'tasks':[{'task_id':'positive','query':'合成配置',
                              'labels':{'a':{'grade':2},'b':{'grade':0}}},
                             {'task_id':'negative','query':'合成未知',
                              'labels':{'a':{'grade':0},'b':{'grade':0}}}]}
        report = {'input_sha256':'synthetic-i','results_sha256':'synthetic-r',
                  'tasks':[{'task_id':'positive','query':'合成配置','candidate_record_ids':['b','a']},
                           {'task_id':'negative','query':'合成未知','candidate_record_ids':[]}]}
        return contract, report

    def test_rank_precision_and_negative_abstention(self):
        c,r=self.fixture(); out=score(c,r,5)
        p,n=out['tasks']
        self.assertEqual((p['precision_at_k'],p['recall_at_k'],p['mrr_at_k']),(.2,1,.5))
        self.assertIsNone(n['recall_at_k']);self.assertIsNone(n['precision_at_k'])
        self.assertTrue(n['negative_case_correct_abstention'])
        self.assertFalse(out['quality_gate_passed'])

    def test_missing_positive_and_negative_false_return(self):
        c,r=self.fixture();r['tasks'][0]['candidate_record_ids']=[]
        r['tasks'][1]['candidate_record_ids']=['a']
        out=score(c,r)
        self.assertEqual(out['tasks'][0]['recall_at_k'],0)
        self.assertFalse(out['tasks'][1]['negative_case_correct_abstention'])
        self.assertEqual(out['summary']['false_returns_at_k'],1)

    def test_receipt_query_identity_and_label_drift_fail_closed(self):
        c,r=self.fixture()
        mutations = [lambda a,b:b.update(input_sha256='changed'),
                     lambda a,b:b['tasks'][0].update(query='changed'),
                     lambda a,b:b['tasks'][0].update(candidate_record_ids=['unknown']),
                     lambda a,b:b['tasks'][0].update(candidate_record_ids=['a','a']),
                     lambda a,b:a['tasks'][0]['labels'].pop('a'),
                     lambda a,b:a.update(annotation_status='human-confirmed')]
        for mutate in mutations:
            a,b=copy.deepcopy(c),copy.deepcopy(r);mutate(a,b)
            with self.assertRaises(ValueError):score(a,b)

    def test_support_only_is_not_direct_relevance(self):
        c,r=self.fixture();c['tasks'][0]['labels']['b']['grade']=1
        out=score(c,r)
        self.assertEqual(out['tasks'][0]['support_only_at_k'],1)
        self.assertEqual(out['tasks'][0]['false_returns_at_k'],0)

"""Explicitly synthetic retrieval safety and budget scenarios; no LLM/provider."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from pipeline.memory_center.core import Store, encoded
from pipeline.memory_center.governance import context

spec=importlib.util.spec_from_file_location('retrieval_benchmark',Path(__file__).resolve().parents[1]/'scripts/benchmark_memory_retrieval.py')
benchmark=importlib.util.module_from_spec(spec);spec.loader.exec_module(benchmark)

class RetrievalBenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        messages=[{'id':'m1','role':'user','text':'合成项目配置使用本地索引。','created_at':'2000-01-01','source_title':'合成资料'}]
        claim={'topic':'projects','kind':'fact','subject':'synthetic-project','statement':messages[0]['text'],
               'message_id':'m1','quote':messages[0]['text'],'status':'stated'}
        self.principal,count=benchmark.seed_candidates(self.store,[{'sample_index':1,'messages':messages}],
                     [{'sample_index':1,'validation':'passed','validated_claims':[claim]}])
        self.assertEqual(count,1)
    def tearDown(self):self.tmp.cleanup()
    def govern(self,**changes):
        values=dict(holder='synthetic-holder',subject_id='synthetic-project',as_of='2000-01-01',
                    valid_until=None,state='verified',priority='P1',revision=1,note='Synthetic fixture only',reviewed=1.0)
        values.update(changes)
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('r-0-0',*(values[k] for k in ('holder','subject_id','as_of','valid_until','state','priority','revision','note','reviewed'))))
    def test_ten_scenarios_and_unconfirmed_context_are_distinct(self):
        result=benchmark.run_benchmark(self.store,self.principal,'rehearsal')
        self.assertEqual(result['task_count'],10)
        self.assertEqual(result['model_calls'],0)
        self.assertFalse(result['quality_gate_passed'])
        self.assertTrue(all(t['usable_context_records']==0 for t in result['tasks']))
        self.assertTrue(all(t['within_char_budget'] for t in result['tasks']))
        row=self.store.snapshot(self.principal,'rehearsal','项目配置')['records'][0]
        self.assertEqual(row['quote'],'合成项目配置使用本地索引。')
        self.assertEqual(row['source_date'],'2000-01-01')
    def test_reviewed_provenance_expiration_future_and_rejection(self):
        self.govern()
        row=context(self.store,self.principal,'rehearsal','项目配置')['records'][0]
        self.assertEqual((row['source_id'],row['message_id']),('source-0','m1'))
        self.assertEqual(row['governance']['holder'],'synthetic-holder')
        for changes in ({'valid_until':'2000-01-02'},{'as_of':'2999-01-01'},{'state':'rejected'}):
            self.govern(**changes)
            self.assertEqual(context(self.store,self.principal,'rehearsal','项目配置')['records'],[])
    def test_owner_scope_and_no_model_attempts(self):
        stranger=dict(self.principal,owner='other')
        self.assertEqual(self.store.snapshot(stranger,'rehearsal','项目配置')['records'],[])
        with self.assertRaises(PermissionError):context(self.store,self.principal,'not-authorized','')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM model_attempts').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
    def test_serialized_budget_and_supersession(self):
        self.govern()
        for size in (500,800,1600):
            reply=context(self.store,self.principal,'rehearsal','',max_chars=size)
            self.assertLessEqual(len(encoded(reply)),size)
        with self.store.db() as db:db.execute("UPDATE records SET lifecycle='superseded' WHERE id='r-0-0'")
        self.assertEqual(context(self.store,self.principal,'rehearsal','')['records'],[])

if __name__=='__main__':unittest.main()

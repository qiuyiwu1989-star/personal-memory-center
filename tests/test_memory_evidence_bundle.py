"""Synthetic read-only evidence grouping and combined-budget fixtures."""
import tempfile
import unittest
from unittest.mock import patch
from pipeline.memory_center.core import Store, Invalid, encoded
from pipeline.memory_center.evidence_bundle import bundle
from pipeline.memory_center import source_discovery


class EvidenceBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        source_discovery.setup(self.store)
        self.scope='synthetic-scope'
        self.p={'id':'synthetic-agent','owner':'synthetic-owner','scopes':[self.scope],
                'actions':['read','write','source_read'],'trusted_user':True}
        texts=['合成 Atlas 查询已核实。','合成 Atlas 查询仅为候选。']
        source=self.store.ingest(self.p,{'scope':self.scope,'source_key':'synthetic-source',
            'source_type':'conversation','processing_policy':'archive',
            'messages':[{'id':str(i),'role':'user','text':text} for i,text in enumerate(texts)]})['id']
        with self.store.db() as db:
            for i,text in enumerate(texts):
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (str(i),self.p['owner'],self.scope,'projects','claim','Atlas',text,
                            'user_stated',source,str(i),text,'active',1,None,i))
            db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('0','synthetic-holder','synthetic-project','2000-01-01',None,'verified','P1',1,'Synthetic fixture',0))
        source_discovery.rebuild(self.store,self.p,self.scope)

    def test_three_groups_preserve_separate_trust_and_read_only_state(self):
        with self.store.db() as db:before=list(db.iterdump())
        result=bundle(self.store,self.p,self.scope,'Atlas')
        self.assertEqual([r['id'] for r in result['trusted_context']['records']],['0'])
        self.assertEqual([r['id'] for r in result['source_reports']['records']],['1'])
        self.assertFalse(result['source_reports']['facts_confirmed'])
        self.assertEqual(result['original_evidence']['status'],'available')
        self.assertFalse(result['original_evidence']['facts_confirmed'])
        self.assertEqual(result['original_evidence']['total'],2)
        self.assertTrue(result['unresolved_questions'])
        self.assertLessEqual(len(encoded(result)),6000)
        with self.store.db() as db:self.assertEqual(list(db.iterdump()),before)

    def test_missing_source_permission_is_explicit_and_never_calls_discovery(self):
        p=self.p | {'actions':['read']}
        with patch('pipeline.memory_center.evidence_bundle.source_discovery.search') as search:
            result=bundle(self.store,p,self.scope,'Atlas')
        search.assert_not_called()
        self.assertEqual(result['original_evidence']['reason'],'source_read_not_authorized')
        self.assertNotIn('results',result['original_evidence'])
        self.assertEqual(len(result['source_reports']['records']),1)

    def test_candidates_never_fallback_into_empty_trusted_context(self):
        with self.store.db() as db:db.execute("UPDATE record_governance SET state='candidate' WHERE record_id='0'")
        result=bundle(self.store,self.p,self.scope,'Atlas')
        self.assertEqual(result['trusted_context']['records'],[])
        self.assertEqual(result['trusted_context']['total'],0)
        self.assertEqual(result['source_reports']['total'],2)

    def test_entire_json_budget_preserves_whole_trusted_item_before_candidates(self):
        with self.store.db() as db:
            db.execute('UPDATE records SET statement=? WHERE id=?',('Atlas '+('\\\n合成'*120),'1'))
        for budget in (1500,2000,6000,16000):
            result=bundle(self.store,self.p,self.scope,'Atlas',max_chars=budget)
            self.assertLessEqual(len(encoded(result)),budget)
            if result['source_reports']['records']:
                self.assertEqual(result['source_reports']['records'][0]['statement'],'Atlas '+('\\\n合成'*120))
        result=bundle(self.store,self.p,self.scope,'Atlas',max_chars=1500)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['trusted_context']['records'][0]['id'],'0')

    def test_owner_scope_budget_and_mode_boundaries(self):
        with self.assertRaises(PermissionError):bundle(self.store,self.p,'other-scope','Atlas')
        with self.assertRaises(PermissionError):bundle(self.store,self.p|{'actions':['source_read']},self.scope,'Atlas')
        other=bundle(self.store,self.p|{'owner':'other-synthetic-owner'},self.scope,'Atlas')
        self.assertEqual(other['trusted_context']['total'],0)
        self.assertEqual(other['source_reports']['total'],0)
        self.assertEqual(other['original_evidence']['total'],0)
        for budget in (1499,16001,True):
            with self.assertRaises(Invalid):bundle(self.store,self.p,self.scope,'Atlas',max_chars=budget)
        with self.assertRaises(Invalid):bundle(self.store,self.p,self.scope,'Atlas',retrieval_mode='implicit-fallback')
        with self.assertRaises(Invalid):bundle(self.store,self.p,self.scope,'x'*501)


if __name__=='__main__':unittest.main()

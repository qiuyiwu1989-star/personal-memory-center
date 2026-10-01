"""Synthetic mode regression: strict experiments must not replace the baseline."""
import tempfile,unittest
from pipeline.memory_center.core import Store,Invalid
from pipeline.memory_center.governance import context

class RetrievalModesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.p={'id':'synthetic','owner':'synthetic','scopes':['personal'],'actions':['read','write'],'trusted_user':True}
        texts=['本地索引配置必须保留出处。','合成索引配置可采用默认设置。','不要虚构故事。']
        source=self.store.ingest(self.p,{'source_key':'synthetic','scope':'personal','source_type':'conversation','processing_policy':'archive','messages':[{'id':str(i),'role':'user','text':s} for i,s in enumerate(texts)]})['id']
        with self.store.db() as db:
            for i,text in enumerate(texts):
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(str(i),'synthetic','personal','projects','decision','synthetic-project',text,'user_stated',source,str(i),text,'active',1,None,i))
                db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',(str(i),'synthetic','synthetic-project','2000-01-01',None,'verified','P2' if i==0 else 'P0',1,'Synthetic fixture',0))
    def tearDown(self):self.tmp.cleanup()
    def test_baseline_is_preserved_and_strict_mode_is_explicit(self):
        legacy=self.store.snapshot(self.p,'personal','虚构人物')
        strict=self.store.snapshot(self.p,'personal','虚构人物',retrieval_mode='lexical-v2')
        self.assertEqual(legacy['retrieval'],'lexical-v1');self.assertEqual([r['id'] for r in legacy['records']],['2'])
        self.assertEqual(strict['records'],[])
        with self.assertRaises(Invalid):self.store.snapshot(self.p,'personal','',retrieval_mode='auto-switch')
    def test_strict_context_relevance_precedes_priority_and_is_still_bounded(self):
        reply=context(self.store,self.p,'personal','本地索引配置',retrieval_mode='lexical-v2')
        self.assertEqual(reply['records'][0]['id'],'0')
        with self.store.db() as db:db.execute("UPDATE record_governance SET state='candidate' WHERE record_id='0'")
        self.assertNotIn('0',[r['id'] for r in context(self.store,self.p,'personal','本地索引配置',retrieval_mode='lexical-v2')['records']])
        with self.assertRaises(PermissionError):context(self.store,self.p,'other','',retrieval_mode='lexical-v2')

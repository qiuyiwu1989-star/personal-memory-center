import tempfile,unittest
from pipeline.memory_center.core import Store
from pipeline.memory_center.reprocessing import preview

class PreviewAssociationTest(unittest.TestCase):
    def test_preview_associates_same_evidence_without_changing_old_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            p={'id':'owner','owner':'synthetic','scopes':['personal'],'actions':['read','write'],'trusted_user':True}
            imported=store.ingest(p,{'scope':'personal','source_key':'synthetic-note','source_type':'conversation','processing_policy':'archive','messages':[{'id':'m','role':'user','text':'项目配置采用合成甲模块。','source_title':'合成项目','created_at':'2025-10-01'}]})
            source=imported['id']
            with store.db() as db:
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('old','synthetic','personal','projects','decision','user','项目配置采用合成甲模块。','user_stated',source,'m','项目配置采用合成甲模块。','active',1,None,0))
            claim={'topic':'projects','kind':'decision','subject':'user','statement':'合成项目采用甲模块。','message_id':'m','quote':'项目配置采用合成甲模块。'}
            result=preview(store,p,source,{'claims':[claim]},'synthetic-v1')
            self.assertEqual(result['changes'][0]['associations'][0]['relation'],'same_evidence')
            self.assertEqual(result['changes'][0]['associations'][0]['record_id'],'old')
            with store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0],1)
            self.assertFalse(result['semantic_verified'])

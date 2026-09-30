import hashlib
import tempfile
import unittest
from pipeline.memory_center.core import Store
from pipeline.memory_center.documents import define_topic, build_documents
from pipeline.memory_center.web import local_app


class Extractor:
    configured=True
    calls=0
    def extract(self, messages):
        self.calls+=1
        m=messages[0]
        return {'claims':[{'topic':'projects','kind':'preference','subject':'user',
               'statement':m['text'],'quote':m['text'],'message_id':m['id']}]}, None


class DocumentTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.principal={'id':'owner','owner':'owner','scopes':['project:demo'],'actions':['read','write'],'trusted_user':True}
        self.model=Extractor()
        self.body={'scope':'project:demo','source_key':'conversation:demo','messages':[{'id':'1','role':'user','text':'先逐条确认，再存记忆。','source_title':'Memory discussion','created_at':'2026-09-10'}]}
        define_topic(self.store,self.principal,'project:demo','memory','记忆中心',['conversation:demo'])
        self.store.ingest(self.principal,self.body);self.store.process_one(self.model)
    def tearDown(self):self.tmp.cleanup()
    def doc(self):return build_documents(self.store,self.principal,'project:demo')[0]
    def test_new_source_gets_automatic_topic_without_extra_model_call(self):
        self.store.ingest(self.principal,dict(self.body,source_key='new:topic'))
        self.store.process_one(self.model)
        docs=build_documents(self.store,self.principal,'project:demo')
        automatic=[d for d in docs if d['slug'].startswith('source-')]
        self.assertEqual(len(automatic),1)
        self.assertEqual(automatic[0]['claims'],1)
        self.assertEqual(self.model.calls,2)
    def test_exact_duplicate_keeps_document_version_and_model_calls(self):
        before=self.doc();result=self.store.ingest(self.principal,self.body)
        self.assertTrue(result['duplicate']);self.assertFalse(self.store.process_one(self.model))
        after=self.doc()
        self.assertEqual((before['digest'],before['revision']),(after['digest'],after['revision']))
        self.assertEqual(self.model.calls,1)
    def test_correction_updates_current_section_preserves_history_and_membership(self):
        before=self.doc();row=self.store.snapshot(self.principal,'project:demo')['records'][0]
        self.store.correct(self.principal,row['id'],{'statement':'测试纠正：自动整理，不逐条确认。','revision':1})
        after=self.doc()
        self.assertEqual(after['revision'],2)
        self.assertEqual(after['claims'],1)
        self.assertIn('测试纠正：自动整理，不逐条确认。',after['markdown'])
        current=after['markdown'].split('## 重要变化')[0]
        self.assertNotIn('先逐条确认，再存记忆。',current)
        self.assertIn('先逐条确认，再存记忆。',after['markdown'].split('## 重要变化')[1])
        self.assertIn('+',after['changes'])
    def test_same_claim_adds_evidence_not_another_claim(self):
        body=dict(self.body,source_key='conversation:demo:second')
        self.store.ingest(self.principal,body);self.store.process_one(self.model)
        after=self.doc()
        self.assertEqual(after['claims'],1)
        self.assertEqual(len(after['dependencies']),2)
    def test_scope_owner_isolation(self):
        with self.assertRaises(PermissionError):build_documents(self.store,self.principal,'personal')
        self.assertEqual(build_documents(self.store,dict(self.principal,owner='other'),'project:demo'),[])
    def test_export_is_disposable_and_search_works(self):
        from pathlib import Path
        before=self.doc();path=Path(before['export_path']);path.write_text('external edit')
        after=self.doc();self.assertEqual(after['digest'],before['digest']);self.assertEqual(path.read_text(),before['markdown'])
        self.assertEqual(len(build_documents(self.store,self.principal,'project:demo','逐条确认')),1)
        self.assertEqual(build_documents(self.store,self.principal,'project:demo','不存在的内容'),[])
    def test_http_documents_requires_scope_auth(self):
        grant=dict(self.principal,token_sha256=hashlib.sha256(b'test').hexdigest())
        client=local_app(self.store,[grant],self.model).test_client()
        path='/api/inside/memory-center/v1/documents?scope=project:demo'
        self.assertEqual(client.get(path).status_code,401)
        self.assertEqual(client.get(path,headers={'Authorization':'Bearer test'}).get_json()['documents'][0]['claims'],1)


if __name__=='__main__':unittest.main()

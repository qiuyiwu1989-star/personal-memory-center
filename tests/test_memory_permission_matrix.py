"""Synthetic protocol permission matrix and immediate grant reload revocation."""
import hashlib
import unittest
from starlette.testclient import TestClient
import test_memory_center as fixture
from pipeline.memory_center.service import create_app


class PermissionMatrixTest(unittest.TestCase):
    setUp=fixture.MemoryTest.setUp
    tearDown=fixture.MemoryTest.tearDown
    body=fixture.MemoryTest.body
    ingest=fixture.MemoryTest.ingest
    rows=fixture.MemoryTest.rows

    def setup_protocol(self,**fields):
        grant=dict(self.owner,id='synthetic-review-agent',trusted_user=False,**fields)
        grant['token_sha256']=hashlib.sha256(b'synthetic-protocol-secret').hexdigest()
        active=[grant]
        app=create_app(self.store,lambda:list(active),self.model,run_worker=False)
        return active,TestClient(app,base_url='http://127.0.0.1:5078')

    def rpc(self,client,name,args):
        return client.post('/mcp/',headers=self.headers_protocol(),json={
            'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})

    def headers_protocol(self):
        return {'Authorization':'Bearer synthetic-protocol-secret','Accept':'application/json, text/event-stream'}

    def test_read_only_agent_cannot_write_correct_confirm_or_expand_source(self):
        source=self.ingest();rid=self.rows()[0]['id']
        active,client=self.setup_protocol(actions=['read'])
        with client as c:
            self.assertFalse(self.rpc(c,'memory_context',{'scope':'personal','query':''}).json()['result'].get('isError',False))
            for name,args in (
                ('memory_import',{'source_key':'synthetic-denied','messages':self.body()['messages']}),
                ('memory_reextract',{'source_id':source['id'],'request_key':'synthetic-denied'}),
                ('memory_source_get',{'source_id':source['id'],'message_id':'1'}),
                ('memory_context',{'scope':'other-synthetic-scope','query':''})):
                with self.subTest(tool=name):self.assertTrue(self.rpc(c,name,args).json()['result']['isError'])
            for path,body in (
                ('/records/'+rid+'/correct',{'statement':'synthetic correction','revision':1}),
                ('/records/'+rid+'/governance',{'state':'verified','revision':0}),
                ('/sources',self.body(source_key='synthetic-denied'))):
                with self.subTest(path=path):self.assertEqual(c.post(self.prefix+path,headers=self.headers_protocol(),json=body).status_code,403)
        self.assertEqual(self.model.calls,1)
        self.assertEqual(len(self.rows()),1)

    def test_revocation_and_scope_reduction_apply_next_mcp_and_rest_request(self):
        active,client=self.setup_protocol(actions=['read'])
        with client as c:
            self.assertEqual(self.rpc(c,'memory_context',{'scope':'personal','query':''}).status_code,200)
            self.assertEqual(c.get(self.prefix+'/records?scope=personal',headers=self.headers_protocol()).status_code,200)
            active[0]=dict(active[0],scopes=['project:demo'])
            self.assertTrue(self.rpc(c,'memory_context',{'scope':'personal','query':''}).json()['result']['isError'])
            self.assertEqual(c.get(self.prefix+'/records?scope=personal',headers=self.headers_protocol()).status_code,403)
            active.clear()
            self.assertEqual(self.rpc(c,'memory_context',{'scope':'project:demo','query':''}).status_code,401)
            self.assertEqual(c.get(self.prefix+'/records?scope=project:demo',headers=self.headers_protocol()).status_code,401)
        self.assertEqual(self.model.calls,0)

if __name__=='__main__':unittest.main()

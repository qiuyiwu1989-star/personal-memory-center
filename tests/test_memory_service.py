import asyncio
import hashlib
import tempfile
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from pipeline.memory_center.core import Store
from pipeline.memory_center.service import create_app
from test_memory_center import FakeModel

class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.grant={'id':'agent','owner':'q','scopes':['personal'],'actions':['read'],'token_sha256':hashlib.sha256(b'secret').hexdigest()}
        self.browser=dict(self.grant,login_user='demo-user',actions=['read','write'],trusted_user=True)
        self.app=create_app(self.store,lambda:[self.grant],FakeModel(),self.browser,run_worker=False)
    def tearDown(self):self.tmp.cleanup()
    def test_unauthorized_and_cross_origin(self):
        with TestClient(self.app,base_url="http://127.0.0.1:5078") as c:
            self.assertEqual(c.post('/mcp/',json={}).status_code,401)
            self.assertEqual(c.post('/mcp/',headers={'Authorization':'Bearer secret','Origin':'https://evil.example'},json={}).status_code,403)
            self.assertEqual(c.get('/api/inside/memory-center/v1/status').status_code,401)
    def test_cookie_validation_and_csrf(self):
        with TestClient(self.app,base_url="http://127.0.0.1:5078") as c,patch('pipeline.memory_center.service.httpx.get') as who:
            who.return_value.status_code=200;who.return_value.json.return_value={'logged_in':True,'user':'demo-user'}
            c.cookies.set('qy_session','test-cookie')
            self.assertEqual(c.get('/api/inside/memory-center/v1/status').status_code,200)
            self.assertEqual(c.post('/api/inside/memory-center/v1/sources',json={}).status_code,401)
            self.assertEqual(c.post('/api/inside/memory-center/v1/sources',headers={'Origin':'https://evil.example','X-Memory-Local':'1'},json={}).status_code,401)
            self.assertEqual(c.post('/api/inside/memory-center/v1/sources',headers={'Origin':'https://memory.example.invalid','X-Memory-Local':'1'},json={}).status_code,400)
            who.return_value.json.return_value={'logged_in':False}
            self.assertEqual(c.get('/api/inside/memory-center/v1/status').status_code,401)
    def test_mcp_revocation_takes_effect_on_next_request(self):
        grants=[self.grant]
        app=create_app(self.store,lambda:grants,FakeModel(),run_worker=False)
        with TestClient(app,base_url='http://127.0.0.1:5078') as c:
            h={'Authorization':'Bearer secret','Accept':'application/json, text/event-stream'}
            body={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}}
            self.assertEqual(c.post('/mcp/',headers=h,json=body).status_code,200)
            grants.clear()
            self.assertEqual(c.post('/mcp/',headers=h,json=body).status_code,401)

    def test_sdk_handshake_tool_call_and_write_denial(self):
        with TestClient(self.app,base_url="http://127.0.0.1:5078") as c:
            h={'Authorization':'Bearer secret','Accept':'application/json, text/event-stream'}
            def rpc(method,params,i=1):
                return c.post('/mcp/',headers=h,json={'jsonrpc':'2.0','id':i,'method':method,'params':params}).json()
            r=rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
            self.assertIn('result',r)
            r=rpc('tools/list',{});self.assertEqual(len(r['result']['tools']),9)
            r=rpc('tools/call',{'name':'memory_search','arguments':{'query':'hello'}})
            self.assertFalse(r['result'].get('isError',False))
            r=rpc('tools/call',{'name':'memory_import','arguments':{'source_key':'test','messages':[{'id':'1','role':'user','text':'test'}]}})
            self.assertTrue(r['result']['isError'])
            self.assertEqual(self.store.snapshot(self.browser,'personal')['jobs'],[])

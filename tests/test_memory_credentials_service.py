"""Cookie owner issues grant; same live loader revokes REST and MCP immediately."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from starlette.testclient import TestClient
from pipeline.memory_center.core import Store
from pipeline.memory_center.service import create_app
from pipeline.memory_center.web import load_grants
from pipeline.memory_center.agent_credentials import AgentCredentials

class NoModel:
    configured=False
    def extract(self,*args):raise AssertionError('credential management never calls model')

class CredentialServiceTests(unittest.TestCase):
    def test_issue_revoke_cookie_csrf_and_mcp(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'grants.json';path.write_text('[]');store=Store(directory)
            owner={'id':'synthetic-human','owner':'synthetic-owner','scopes':['personal'],'actions':['read','source_read','write'],'trusted_user':True,'login_user':'synthetic-user'}
            app=create_app(store,lambda:load_grants(path),NoModel(),owner,run_worker=False,credential_manager=AgentCredentials(path))
            prefix='/api/inside/memory-center/v1'
            with TestClient(app,base_url='http://127.0.0.1:5078') as c,patch('pipeline.memory_center.service.httpx.get') as who:
                who.return_value.status_code=200;who.return_value.json.return_value={'logged_in':True,'user':'synthetic-user'};c.cookies.set('qy_session','synthetic-cookie')
                data={'request_key':'synthetic-request','description':'合成只读连接','scopes':['personal'],'actions':['read'],'days':1}
                self.assertEqual(c.post(prefix+'/agent-credentials',json=data).status_code,401)
                h={'Origin':'https://memory.example.invalid','X-Memory-Local':'1'}
                result=c.post(prefix+'/agent-credentials',json=data,headers=h);self.assertEqual(result.status_code,200)
                token=result.json()['token'];ident=result.json()['credential']['id'];bearer={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
                rpc={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}}
                self.assertEqual(c.post('/mcp/',headers=bearer,json=rpc).status_code,200)
                self.assertEqual(c.get(prefix+'/status',headers=bearer).status_code,200)
                self.assertEqual(c.get(prefix+'/agent-credentials',headers=bearer).status_code,403)
                self.assertNotIn(token,c.get(prefix+'/agent-credentials').text)
                self.assertEqual(c.post(prefix+'/agent-credentials/'+ident+'/revoke',headers=h,json={}).status_code,200)
                self.assertEqual(c.post('/mcp/',headers=bearer,json=rpc).status_code,401)
                self.assertEqual(c.get(prefix+'/status',headers=bearer).status_code,401)
                listing=c.get(prefix+'/agent-credentials').json();self.assertEqual(listing['credentials'][0]['state'],'revoked')

if __name__=='__main__':unittest.main()

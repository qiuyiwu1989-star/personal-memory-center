"""Synthetic real MCP/REST candidate windows and per-request authorization."""
import hashlib
import json
import unittest
from starlette.testclient import TestClient
import test_memory_candidate_window as baseline
from test_memory_center import FakeModel
from pipeline.memory_center.service import create_app
from pipeline.memory_center.core import encoded


class CandidateRemoteTest(unittest.TestCase):
    setUp=baseline.CandidateWindowTest.setUp
    seed=baseline.CandidateWindowTest.seed
    prefix='/api/inside/memory-center/v1'

    def protocol(self,**fields):
        self.model=FakeModel()
        grant=dict(self.p,**dict(actions=['read'],trusted_user=False)|fields)
        grant['token_sha256']=hashlib.sha256(b'synthetic-window-secret').hexdigest()
        self.active=[grant]
        return TestClient(create_app(self.store,lambda:self.active,self.model,run_worker=False),base_url='http://127.0.0.1:5078')

    def headers(self):
        return {'Authorization':'Bearer synthetic-window-secret','Accept':'application/json, text/event-stream'}

    def rpc(self,client,name,args):
        return client.post('/mcp/',headers=self.headers(),json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}})

    def candidate(self,client,**args):
        result=self.rpc(client,'memory_candidate_search',dict(query='Atlas',scope=self.scope)|args).json()['result']
        self.assertFalse(result.get('isError',False),result)
        self.assertEqual(len(result['content']),1)
        text=result['content'][0]['text']
        self.assertEqual(json.loads(text),result['structuredContent'])
        self.assertLessEqual(len(text),args.get('max_chars',6000))
        return result['structuredContent']

    def rest(self,client,**args):
        return client.get(self.prefix+'/candidate-search',headers=self.headers(),params=dict(q='Atlas',scope=self.scope)|args)

    def test_real_pagination_total_coverage_same_window_and_small_budgets(self):
        self.seed(8)
        with self.store.db() as db:
            db.execute('UPDATE records SET statement=? WHERE id=?',('Atlas '+('合成\\\n'*10000),'window-7'))
        with self.protocol() as client:
            with self.store.db() as db:before=list(db.iterdump())
            for budget in (500,1500,6000):
                first=self.candidate(client,max_chars=budget,window_limit=3)
                response=self.rest(client,max_chars=budget,window_limit=3)
                self.assertEqual(response.status_code,200)
                self.assertLessEqual(len(response.text),budget)
                self.assertEqual(response.json(),first)
                self.assertEqual(first['kind'],'candidate_reports')
                self.assertFalse(first['facts_confirmed'])
                self.assertEqual(first['total'],9)
                self.assertEqual(first['coverage']['examined'],3)
                self.assertEqual(first['coverage']['continue_offset'],3)
                self.assertTrue(first['truncated'])
                self.assertNotIn('window-7',[r['id'] for r in first['records']])
                self.assertEqual(self.candidate(client,max_chars=budget,window_limit=3),first)
                next_page=self.candidate(client,max_chars=budget,window_limit=3,offset=3)
                self.assertEqual(next_page['coverage']['offset'],3)
                self.assertEqual(next_page['coverage']['continue_offset'],6)
                self.assertFalse(set(r['id'] for r in first['records']) & set(r['id'] for r in next_page['records']))
            last=self.candidate(client,max_chars=6000,window_limit=3,offset=6)
            self.assertIsNone(last['coverage']['continue_offset'])
            self.assertEqual(last['coverage']['examined'],3)
            self.assertNotIn('0',[r['id'] for r in last['records']])
            with self.store.db() as db:self.assertEqual(list(db.iterdump()),before)
        self.assertEqual(self.model.calls,0)

    def test_candidate_permissions_revocation_owner_isolation_and_no_trusted_fallback(self):
        with self.protocol() as client:
            found=self.candidate(client,max_chars=1500)
            self.assertEqual([r['id'] for r in found['records']],['1'])
            trusted=json.loads(self.rpc(client,'memory_context',{'scope':self.scope,'query':'仅为候选'}).json()['result']['content'][0]['text'])
            self.assertEqual(trusted['records'],[])
            source=found['records'][0]
            self.assertTrue(self.rpc(client,'memory_source_get',dict(source_id=source['source_id'],message_id=source['message_id'])).json()['result']['isError'])
            self.assertTrue(self.rpc(client,'memory_candidate_search',dict(query='',scope=self.scope+'-denied')).json()['result']['isError'])
            self.assertEqual(self.rest(client,scope=self.scope+'-denied').status_code,403)
            self.active[0]=dict(self.active[0],owner='synthetic-other-owner')
            self.assertEqual(self.candidate(client)['total'],0)
            self.assertEqual(self.rest(client).json()['total'],0)
            self.active[0]=dict(self.active[0],scopes=[])
            self.assertTrue(self.rpc(client,'memory_candidate_search',dict(query='',scope=self.scope)).json()['result']['isError'])
            self.assertEqual(self.rest(client).status_code,403)
            self.active.clear()
            self.assertEqual(self.rpc(client,'memory_candidate_search',dict(query='',scope=self.scope)).status_code,401)
            self.assertEqual(self.rest(client).status_code,401)
        self.assertEqual(self.model.calls,0)

    def test_unicode_long_scope_metadata_and_parameter_validation(self):
        long_scope='合成范围'*100
        with self.store.db() as db:
            db.execute('UPDATE sources SET scope=?',(long_scope,))
            db.execute('UPDATE records SET scope=?',(long_scope,))
        with self.protocol(scopes=[long_scope]) as client:
            result=self.candidate(client,query='合成',scope=long_scope,max_chars=500)
            self.assertLessEqual(len(encoded(result)),500)
            self.assertEqual(result['total'],1)
            self.assertFalse(result['facts_confirmed'])
            self.assertEqual(self.rest(client,q='合成',scope=long_scope,max_chars=500).json(),result)
            for key,value in (('offset','oops'),('offset','-1'),('offset','1.5'),('offset','１'),('window_limit','129'),('max_chars','499')):
                self.assertEqual(self.rest(client,scope=long_scope,**{key:value}).status_code,400)
            for args in ({'offset':10001},{'window_limit':129},{'max_chars':499},{'retrieval_mode':'unknown'},
                         {'offset':True},{'offset':'0'},{'offset':1.5},{'window_limit':True},{'max_chars':1500.0}):
                self.assertTrue(self.rpc(client,'memory_candidate_search',dict(scope=long_scope,query='')|args).json()['result']['isError'])

    def test_new_tool_schema_preserves_legacy_search_contract(self):
        with self.protocol() as client:
            response=client.post('/mcp/',headers=self.headers(),json={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}}).json()
            tools={tool['name']:tool for tool in response['result']['tools']}
            self.assertTrue({'memory_context','memory_candidate_search','memory_source_withdraw'}.issubset(set(tools)))
            old=tools['memory_search']['inputSchema']
            self.assertEqual(set(old['properties']),{'query','scope','max_chars','retrieval_mode'})
            self.assertEqual(old['required'],['query'])
            self.assertEqual(old['properties']['scope']['default'],'personal')
            self.assertEqual(old['properties']['max_chars']['default'],6000)
            new=tools['memory_candidate_search']['inputSchema']
            self.assertEqual(set(new['properties']),set(old['properties'])|{'offset','window_limit'})
            self.assertEqual(new['properties']['offset']['default'],0)
            self.assertEqual(new['properties']['window_limit']['default'],128)
            old_result=json.loads(self.rpc(client,'memory_search',dict(query='Atlas',scope=self.scope)).json()['result']['content'][0]['text'])
            self.assertEqual(set(old_result),{'records','total','truncated'})
            self.assertEqual(old_result['total'],2)
            self.assertEqual(self.candidate(client)['total'],1)


if __name__=='__main__':unittest.main()

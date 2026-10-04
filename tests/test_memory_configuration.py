import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pipeline.memory_center.core import Store, Conflict, Invalid
from pipeline.memory_center.configuration import draft, activate, listing, runtime, extra_reservation
from pipeline.memory_center.visual_map import build
from pipeline.memory_center.model import Model, PROMPT_VERSION
from pipeline.memory_center.web import local_app
from test_memory_center import FakeModel

class ConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.owner={'id':'owner','owner':'synthetic','trusted_user':True,'scopes':['personal','project:demo'],'actions':['read','write','source_read']}
        self.agent=dict(self.owner,id='agent',trusted_user=False)
    def tearDown(self):self.tmp.cleanup()
    def make(self,kind='prompt',payload=None,scope='personal'):
        return draft(self.store,self.owner,scope,{'kind':kind,'label':'synthetic version','payload':payload or {'instructions':'仅保留有明确出处的长期判断。'}})['id']
    def enable(self,vid,revision=0,scope='personal'):
        return activate(self.store,self.owner,scope,vid,{'revision':revision,'note':'合成样本验证完成；并非真实质量认证。'})
    def test_drafts_are_immutable_and_do_not_change_runtime(self):
        vid=self.make();self.assertEqual(runtime(self.store,{'owner':'synthetic','scope':'personal'}),{})
        before=listing(self.store,self.owner,'personal')['versions'][0]
        self.enable(vid)
        self.assertEqual(runtime(self.store,{'owner':'synthetic','scope':'personal'})['prompt_version'],vid)
        self.assertEqual(before,listing(self.store,self.owner,'personal')['versions'][0])
        self.assertFalse(listing(self.store,self.owner,'personal')['events']==[])
    def test_agent_and_scope_and_owner_isolation(self):
        vid=self.make()
        with self.assertRaises(PermissionError):listing(self.store,self.agent,'personal')
        with self.assertRaises(PermissionError):draft(self.store,self.agent,'personal',{})
        with self.assertRaises(Invalid):self.enable(vid,scope='project:demo')
        other=dict(self.owner,owner='other')
        self.assertEqual(listing(self.store,other,'personal')['versions'],[])
        with self.assertRaises(Invalid):activate(self.store,other,'personal',vid,{'revision':0,'note':'这是另一个人的配置测试。'})
    def test_stale_activation_and_rollback_audited(self):
        first=self.make();second=self.make(payload={'instructions':'第二版补充规则'})
        self.enable(first)
        with self.assertRaises(Conflict):self.enable(second)
        self.enable(second,1);self.enable(first,2)
        self.assertEqual(len(listing(self.store,self.owner,'personal')['events']),3)
    def test_activation_blocks_pending_jobs(self):
        vid=self.make()
        self.store.ingest(self.owner,{'source_key':'pending','messages':[{'id':'1','role':'user','text':'合成测试材料'}]})
        with self.assertRaises(Conflict):self.enable(vid)
    def test_model_destination_and_secret_fields_rejected(self):
        env={'QIU_MEMORY_LLM_BASE':'https://model.example.invalid/api/v1'}
        with patch.dict(os.environ,env):
            good={'base_url':env['QIU_MEMORY_LLM_BASE'],'model':'synthetic-endpoint','max_tokens':1024}
            self.make('model',good)
            for base in ('https://evil.example/api/v1','https://model.example.invalid/api/v1?key=abc','http://model.example.invalid/api/v1'):
                with self.assertRaises(Invalid):self.make('model',dict(good,base_url=base))
            with self.assertRaises(Invalid):self.make('model',dict(good,key='synthetic-secret'))
    def test_skill_is_exportable_not_remote_execution(self):
        vid=self.make('skill',{'name':'memory-capture','version':'synthetic-v1','instructions':'合成 Skill 草稿'})
        with self.assertRaises(Invalid):self.enable(vid)
        manifest=listing(self.store,self.owner,'personal')['integration']
        self.assertEqual(len(manifest['tools']),10)
        self.assertEqual(len(manifest['skills']),2)
    def test_prompt_budget_reserves_utf8_and_empty_is_baseline(self):
        vid=self.make(payload={'instructions':'中文补充'})
        self.enable(vid)
        with self.store.db() as db:self.assertEqual(extra_reservation(db,'synthetic','personal'),len('中文补充'.encode())+300)
        blank=self.make(payload={'instructions':''});self.enable(blank,1)
        with self.store.db() as db:self.assertEqual(extra_reservation(db,'synthetic','personal'),0)
    def test_active_model_rechecks_provisioned_destination(self):
        good={'base_url':'https://model.example.invalid/api/v1','model':'synthetic','max_tokens':100}
        with patch.dict(os.environ,{'QIU_MEMORY_LLM_BASE':good['base_url']}):vid=self.make('model',good);self.enable(vid)
        with patch.dict(os.environ,{'QIU_MEMORY_LLM_BASE':'https://other.example.invalid'}):
            with self.assertRaises(Invalid):runtime(self.store,{'owner':'synthetic','scope':'personal'})
    def test_runtime_keeps_baseline_version_and_records_config(self):
        vid=self.make();self.enable(vid)
        model=Model(self.store)
        source={'owner':'synthetic','scope':'personal','source_type':'conversation','payload':json.dumps([{'id':'1','role':'user','text':'从现在起，本项目必须保留变更历史，直到我明确更改。'}],ensure_ascii=False)}
        with patch.object(model,'_call',return_value=({'claims':[]},{'total_tokens':10,'method_version':PROMPT_VERSION})) as call:
            plan,usage=model.extract_source(source)
        self.assertIn('Mandatory baseline:',call.call_args.args[0]);self.assertEqual(usage['configuration_versions']['prompt_version'],vid)
        self.assertEqual(usage['method_version'],PROMPT_VERSION)
    def test_rest_denies_unauthenticated_and_agent_configuration(self):
        grants=[dict(self.owner,token_sha256=hashlib.sha256(b'owner').hexdigest()),dict(self.agent,token_sha256=hashlib.sha256(b'agent').hexdigest())]
        c=local_app(self.store,grants,FakeModel()).test_client();url='/api/inside/memory-center/v1/configuration'
        self.assertEqual(c.get(url).status_code,401)
        self.assertEqual(c.get(url,headers={'Authorization':'Bearer agent'}).status_code,403)
        self.assertEqual(c.get(url,headers={'Authorization':'Bearer owner'}).status_code,200)
    def test_map_is_paginated_scoped_and_does_not_infer_attribution(self):
        from pipeline.memory_center.budget import configure
        configure(self.store,self.owner,'personal',{'token_limit':100000})
        for i in range(3):
            self.store.ingest(self.owner,{'source_key':'synthetic:'+str(i),'messages':[{'id':'1','role':'user','text':'我喜欢先看合成测试结论。'}]});self.store.process_one(FakeModel())
        result=build(self.store,self.owner,'personal',limit=2)
        self.assertEqual((result['total'],len(result['records']),result['next_offset']),(3,2,2))
        self.assertEqual({e['relation'] for e in result['edges']},{'来源'})
        self.assertFalse(any(r['usable'] for r in result['records']))
        self.assertEqual(build(self.store,dict(self.owner,owner='other'),'personal')['total'],0)
        with self.assertRaises(PermissionError):build(self.store,dict(self.agent,scopes=['project:demo']),'personal')
        with self.assertRaises(Invalid):build(self.store,self.owner,'personal',limit=1000)
    def test_source_endpoint_enforces_source_read(self):
        result=self.store.ingest(self.owner,{'source_key':'synthetic','processing_policy':'archive','messages':[{'id':'1','role':'user','text':'合成原文'}]})
        grant=dict(self.owner,actions=['read'],token_sha256=hashlib.sha256(b'reader').hexdigest())
        c=local_app(self.store,[grant],FakeModel()).test_client()
        response=c.get('/api/inside/memory-center/v1/source',query_string={'source_id':result['id'],'message_id':'1'},headers={'Authorization':'Bearer reader'})
        self.assertEqual(response.status_code,403)

    def test_bulk_settles_custom_prompt_reserve_without_extra_charge(self):
        from test_memory_bulk import BulkTest, BATCH, MeteredModel
        fixture=BulkTest();fixture.setUp()
        try:
            scope=fixture.owner['scopes'][1]
            vid=draft(fixture.store,fixture.owner,scope,{'kind':'prompt','label':'synthetic','payload':{'instructions':'中文额外提示'*20}})['id']
            activate(fixture.store,fixture.owner,scope,vid,{'revision':0,'note':'合成预算测试，不是实际质量验收。'})
            batch=fixture.bulk.create(fixture.owner,BATCH,100000)
            fixture.bulk.tick()
            with fixture.store.db() as db:
                segment=dict(db.execute("SELECT * FROM bulk_segments WHERE state='queued'").fetchone())
            self.assertGreater(segment['reserved_tokens'],35000)
            fixture.store.process_one(MeteredModel(20000));fixture.bulk.control(fixture.owner,batch['id'],'pause');fixture.bulk.tick()
            self.assertEqual(fixture.bulk.status(fixture.owner,batch['id'])['tokens_spent'],20000)
        finally:fixture.tearDown()

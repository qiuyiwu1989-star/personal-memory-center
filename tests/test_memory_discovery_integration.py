"""Synthetic REST/discovery integration review; no production resources or models."""
import json
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from pipeline.memory_center.core import Store,encoded,Invalid
from pipeline.memory_center import source_discovery as discovery
from pipeline.memory_center.web import blueprint,PREFIX

class NoModel:
    configured=False

class DiscoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.p={'id':'synthetic-reviewer','owner':'synthetic-owner','scopes':['synthetic-review'],'actions':['read','source_read','write'],'trusted_user':True}
        self.scope='synthetic-review'
        self.app=Flask(__name__)
        self.app.register_blueprint(blueprint(self.store,[],NoModel(),lambda:self.p))
        self.client=self.app.test_client()
    def add(self,text,role='user',source_type='conversation',key='synthetic-source'):
        return self.store.ingest(self.p,{'scope':self.scope,'source_key':key,'source_type':source_type,'processing_policy':'archive','messages':[{'id':'synthetic-message','role':role,'text':text}]})['id']
    def rebuild(self):
        response=self.client.post(PREFIX+'/archive-index',json={'scope':self.scope})
        self.assertEqual(response.status_code,200)
    def test_rest_wire_search_and_read_json_stay_in_requested_budget(self):
        self.add('合成中文证据与预算。'*700,role='assistant',source_type='imported_summary');self.rebuild()
        found=self.client.get(PREFIX+'/archive-search',query_string={'scope':self.scope,'q':'预算','max_chars':1600})
        self.assertEqual(found.status_code,200)
        self.assertLessEqual(len(found.get_data(as_text=True)),1600,'REST serialized search envelope exceeds max_chars')
        hit=found.json['results'][0]
        self.assertEqual(hit['role'],'assistant');self.assertEqual(hit['material_type'],'imported_summary');self.assertFalse(found.json['facts_confirmed'])
        page=self.client.post(PREFIX+'/archive-source',json={'scope':self.scope,'locator':hit['locator'],'max_chars':700})
        self.assertEqual(page.status_code,200)
        self.assertLessEqual(len(page.get_data(as_text=True)),700,'REST serialized source envelope exceeds max_chars')
    def test_rest_source_pages_lossless_under_wire_budget(self):
        original='合成原文。'*800+'<thinking>合成隐藏推理</thinking>'+'合成结尾。'*80
        self.add(original);self.rebuild()
        loc=discovery.search(self.store,self.p,self.scope,'原文')['results'][0]['locator']
        position=0;parts=[]
        while True:
            response=self.client.post(PREFIX+'/archive-source',json={'scope':self.scope,'locator':loc,'offset':position,'max_chars':700})
            self.assertEqual(response.status_code,200)
            self.assertLessEqual(len(response.get_data(as_text=True)),700)
            part=response.json;parts.append(part['text'])
            self.assertFalse(part['facts_confirmed']);self.assertNotIn('隐藏推理',part['text'])
            if part['next_offset']is None:break
            self.assertGreater(part['next_offset'],position);position=part['next_offset']
        visible=discovery._visible({'role':'user','text':original})
        self.assertEqual(''.join(parts),visible)
        self.assertEqual(len(''.join(parts)),len(original))
    def test_mcp_archive_reads_need_no_write_and_no_implicit_rebuild(self):
        import hashlib
        from starlette.testclient import TestClient
        from pipeline.memory_center.service import create_app
        self.add('合成预算原话。'*700,role='assistant',source_type='document');self.rebuild()
        grant=dict(self.p,actions=['read','source_read'],token_sha256=hashlib.sha256(b'synthetic-token').hexdigest())
        app=create_app(self.store,lambda:[grant],NoModel(),run_worker=False)
        with self.store.db()as db:before=[dict(r) for r in db.execute('SELECT * FROM source_discovery_versions')]
        with TestClient(app,base_url='http://127.0.0.1:5078')as client:
            headers={'Authorization':'Bearer synthetic-token','Accept':'application/json, text/event-stream'}
            def call(name,arguments):
                return client.post('/mcp/',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':arguments}}).json()['result']
            found=call('memory_archive_search',{'scope':self.scope,'query':'预算','max_chars':1600})
            self.assertFalse(found.get('isError',False));data=found.get('structuredContent') or json.loads(found['content'][0]['text'])
            self.assertFalse(data['facts_confirmed']);self.assertEqual(data['kind'],'source_evidence')
            self.assertLessEqual(len(encoded(data)),1600)
            self.assertLessEqual(len(found['content'][0]['text']),1600)
            read=call('memory_archive_source_get',{'scope':self.scope,'locator':data['results'][0]['locator'],'max_chars':700})
            self.assertFalse(read.get('isError',False));read_data=read.get('structuredContent') or json.loads(read['content'][0]['text'])
            self.assertEqual(read_data['role'],'assistant');self.assertLessEqual(len(encoded(read_data)),700)
            self.assertLessEqual(len(read['content'][0]['text']),700,'MCP SDK serialization must respect tool payload budget')
            denied=call('memory_import',{'scope':self.scope,'source_key':'synthetic-denied','messages':[{'id':'1','role':'user','text':'合成禁止写'}]})
            self.assertTrue(denied.get('isError'))
            grant['actions']=['read']
            self.assertTrue(call('memory_archive_search',{'scope':self.scope,'query':'预算'}).get('isError'))
        with self.store.db()as db:
            self.assertEqual(before,[dict(r) for r in db.execute('SELECT * FROM source_discovery_versions')])
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],0)
    def test_locator_invalidated_and_cross_owner_denied(self):
        sid=self.add('合成预算原话');self.rebuild()
        loc=discovery.search(self.store,self.p,self.scope,'预算')['results'][0]['locator']
        self.p['owner']='another-synthetic-owner'
        self.assertEqual(self.client.post(PREFIX+'/archive-source',json={'scope':self.scope,'locator':loc}).status_code,400)
        self.p['owner']='synthetic-owner'
        with self.store.db() as db:db.execute('UPDATE sources SET payload=? WHERE id=?',(encoded([{'id':'synthetic-message','role':'user','text':'合成修改后'}]),sid))
        self.assertEqual(self.client.post(PREFIX+'/archive-source',json={'scope':self.scope,'locator':loc}).status_code,400)
    def test_rest_read_permission_and_no_candidate_side_effect(self):
        self.add('合成预算');self.rebuild()
        self.p['actions']=['read']
        self.assertEqual(self.client.get(PREFIX+'/archive-search',query_string={'scope':self.scope}).status_code,403)
        self.assertEqual(self.client.post(PREFIX+'/archive-index',json={'scope':self.scope}).status_code,403)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],0)
    def test_index_failure_rolls_back_previous_replacement(self):
        self.add('合成预算',key='synthetic-one');self.add('合成车辆',key='synthetic-two');self.rebuild()
        with self.store.db() as db:before=[dict(r) for r in db.execute('SELECT * FROM source_discovery_chunks ORDER BY id')]
        original=discovery._chunks;calls=0
        def fail_second(source):
            nonlocal calls
            calls+=1
            if calls==2:raise RuntimeError('synthetic indexing failure')
            return original(source)
        with patch.object(discovery,'_chunks',side_effect=fail_second):
            with self.assertRaises(RuntimeError):discovery.rebuild(self.store,self.p,self.scope,force=True)
        with self.store.db() as db:after=[dict(r) for r in db.execute('SELECT * FROM source_discovery_chunks ORDER BY id')]
        self.assertEqual(before,after)

if __name__=='__main__':unittest.main()

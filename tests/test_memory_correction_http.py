"""Synthetic real TCP REST/MCP correction boundary; never contacts production or LLM."""
import hashlib
import json
import importlib.util
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
import httpx
import uvicorn
from pipeline.memory_center.core import Store
from pipeline.memory_center.service import create_app


class NoModel:
    configured = False
    def extract(self, *args):
        raise AssertionError('HTTP acceptance must not call a model')


class CorrectionHTTPTests(unittest.TestCase):
    def test_two_readers_correction_history_inbox_and_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            from pipeline.memory_center.temporal import setup
            setup(store)
            owner = dict(id='synthetic-human', owner='synthetic-owner', scopes=['personal', 'agent:synthetic-inbox'],
                         actions=['read', 'write', 'source_read'], trusted_user=True)
            grants = []
            for name, principal in [('human', owner),
                    ('reader-a', dict(owner, id='reader-a', actions=['read'], trusted_user=False, scopes=['personal'])),
                    ('reader-b', dict(owner, id='reader-b', actions=['read'], trusted_user=False, scopes=['personal'])),
                    ('writer', dict(owner, id='writer', actions=['read', 'write'], trusted_user=False, scopes=['agent:synthetic-inbox']))]:
                grants.append(dict(principal, token_sha256=hashlib.sha256(('synthetic-'+name).encode()).hexdigest()))
            listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(128)
            url = 'http://127.0.0.1:'+str(listener.getsockname()[1])
            server = uvicorn.Server(uvicorn.Config(create_app(store, lambda: grants, NoModel(), run_worker=False), log_level='critical', access_log=False))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True); thread.start()
            try:
                deadline = time.monotonic()+10
                while not server.started and thread.is_alive() and time.monotonic()<deadline: time.sleep(.02)
                self.assertTrue(server.started)
                with httpx.Client(base_url=url, timeout=10, follow_redirects=False, trust_env=False) as c:
                    prefix = '/api/inside/memory-center/v1'
                    def headers(name): return {'Authorization': 'Bearer synthetic-'+name, 'Accept': 'application/json, text/event-stream'}
                    def post(path, payload, name='human', status=200):
                        r = c.post(prefix+path, json=payload, headers=headers(name)); self.assertEqual(r.status_code, status, r.text); return r.json()
                    def rpc(name, tool, arguments):
                        r = c.post('/mcp/', headers=headers(name), json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':tool,'arguments':arguments}})
                        self.assertEqual(r.status_code, 200); return r.json()['result']
                    def contexts():
                        out=[]
                        for name in ('reader-a','reader-b'):
                            r=rpc(name,'memory_context',{'scope':'personal','query':'','max_chars':6000})
                            self.assertFalse(r.get('isError',False),r)
                            out.append(r.get('structuredContent') or json.loads(r['content'][0]['text']))
                        self.assertEqual(out[0],out[1]); return out[0]
                    self.assertEqual(contexts()['records'], [])
                    gov=dict(state='verified', holder='owner:synthetic-owner', subject_id='owner:synthetic-owner', as_of='2000-01-01')
                    first=post('/owner-records',dict(scope='personal',request_key='synthetic-create',statement='合成偏好：先看结论。',explicit_confirmation=True,governance=gov))
                    before=contexts(); self.assertEqual(before['records'][0]['id'],first['id'])
                    edit=post('/records/'+first['id']+'/revise',dict(scope='personal',request_key='synthetic-edit',revision=1,governance_revision=1,statement='合成偏好：先看证据。'))
                    pending=contexts(); self.assertEqual(pending['records'],[])
                    self.assertNotEqual(before['context_revision'],pending['context_revision'])
                    history=c.get(prefix+'/records?scope=personal&history=1',headers=headers('human')).json()['records']
                    by_id={r['id']:r for r in history}; self.assertEqual(by_id[first['id']]['lifecycle'],'superseded')
                    self.assertEqual(by_id[edit['id']]['governance']['state'],'candidate')
                    post('/records/'+edit['id']+'/governance',dict(revision=1,**gov))
                    approved=contexts(); self.assertEqual(approved['records'][0]['id'],edit['id'])
                    spec=importlib.util.spec_from_file_location('tcp_probe',Path(__file__).resolve().parents[1]/'scripts/check_agent_memory_read.py')
                    probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
                    receipt=probe.probe(url+'/mcp/', ['synthetic-reader-a','synthetic-reader-b'], 'personal')
                    self.assertEqual(receipt['result'],'pass');self.assertEqual(receipt['records_in_bounded_response'],1)
                    self.assertEqual(receipt['initialized_readers'],2);self.assertEqual(len(receipt['negotiated_protocols']),2)
                    self.assertNotIn('先看证据',json.dumps(receipt,ensure_ascii=False))
                    self.assertEqual(approved['records'][0]['statement'],'合成偏好：先看证据。')
                    post('/records/'+edit['id']+'/governance',dict(revision=2,state='rejected',change_kind='withdrawal'))
                    self.assertEqual(contexts()['records'],[])
                    post('/owner-records',dict(scope='personal',request_key='synthetic-forgery',statement='合成伪造。'),name='writer',status=403)
                    for name in ('reader-a','reader-b'):
                        post('/records/'+edit['id']+'/governance',dict(revision=3,**gov),name=name,status=403)
                        self.assertTrue(rpc(name,'memory_source_get',dict(source_id=first['source_id'],message_id='owner-statement')).get('isError'))
                    arguments=dict(scope='agent:synthetic-inbox',source_key='synthetic-assistant-1',source_type='document',processing_policy='archive',messages=[dict(id='m1',role='assistant',text='合成助手建议，不是本人决定。')])
                    receipt=rpc('writer','memory_import',arguments); self.assertFalse(receipt.get('isError',False),receipt)
                    duplicate=rpc('writer','memory_import',arguments)
                    data=duplicate.get('structuredContent') or json.loads(duplicate['content'][0]['text']); self.assertTrue(data['duplicate'])
                    self.assertTrue(rpc('writer','memory_context',dict(scope='personal',query='')).get('isError'))
                    self.assertEqual(contexts()['records'],[])
                    with store.db() as db:
                        source=db.execute("SELECT payload,trusted_user FROM sources WHERE source_key='synthetic-assistant-1'").fetchone()
                        self.assertEqual(source['trusted_user'],0); self.assertEqual(json.loads(source['payload'])[0]['role'],'assistant')
                        self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],2)
                    self.assertIn('no-store', [v.strip() for v in c.get(prefix+'/status',headers=headers('reader-a')).headers['cache-control'].split(',')])
            finally:
                server.should_exit=True; thread.join(timeout=10); listener.close()
                self.assertFalse(thread.is_alive())

if __name__ == '__main__': unittest.main()

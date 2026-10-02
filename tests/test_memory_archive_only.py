"""Synthetic least-cost grant checks through Store, REST and real MCP app."""
import hashlib
import json
import unittest
from starlette.testclient import TestClient
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid, encoded
from pipeline.memory_center.reprocessing import enqueue, control
from pipeline.memory_center.budget import configure
from pipeline.memory_center.service import create_app


class ArchiveOnlyTest(unittest.TestCase):
    setUp=baseline.MemoryTest.setUp
    tearDown=baseline.MemoryTest.tearDown
    body=baseline.MemoryTest.body
    ingest=baseline.MemoryTest.ingest
    rows=baseline.MemoryTest.rows

    def limited(self,**changes):
        return dict(self.owner,id='synthetic-writer',trusted_user=False,archive_only=True,**changes)

    def test_missing_policy_archives_explicit_extract_and_body_override_denied(self):
        p=self.limited()
        result=self.store.ingest(p,self.body(archive_only=False))
        self.assertEqual(self.store.snapshot(p,'personal')['jobs'][0]['state'],'archived')
        self.assertFalse(self.store.process_one(self.model));self.assertEqual(self.model.calls,0)
        # Permission validation happens before dedup: resubmitting the same
        # source cannot disguise an extraction request as an existing archive.
        for policy in ('extract',):
            with self.assertRaises(PermissionError):self.store.ingest(p,self.body(processing_policy=policy))
        with self.assertRaises(PermissionError):self.store.ingest(p,self.body(scope='unknown',processing_policy='archive'))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'],1)
            self.assertEqual(db.execute('SELECT count(*) n FROM extraction_runs').fetchone()['n'],0)
        self.assertTrue(self.store.ingest(p,self.body())['duplicate'])

    def test_legacy_default_extract_and_explicit_unrestricted_remain_compatible(self):
        for i,flag in enumerate((None,False)):
            p=dict(self.owner,id='synthetic-legacy-'+str(i),trusted_user=False)
            if flag is not None:p['archive_only']=flag
            self.store.ingest(p,self.body(source_key='legacy-'+str(i)))
        self.assertEqual([j['state'] for j in self.store.snapshot(self.owner,'personal')['jobs']],['received','received'])
        self.assertEqual(self.model.calls,0)

    def test_reextract_translate_retry_and_budget_cannot_schedule(self):
        source=self.store.ingest(self.owner,self.body(processing_policy='archive'))
        p=self.limited()
        for operation in ('reextract','translate'):
            with self.assertRaises(PermissionError):enqueue(self.store,p,source['id'],'synthetic-'+operation,operation,'unknown-record')
        with self.store.db() as db:db.execute("UPDATE jobs SET state='failed' WHERE id=?",(source['job_id'],))
        with self.assertRaises(PermissionError):self.store.retry(p,source['job_id'])
        # Even a misconfigured trusted flag cannot bypass cost capability.
        trusted=dict(p,trusted_user=True)
        with self.assertRaises(PermissionError):configure(self.store,trusted,'personal',{'token_limit':100000})
        run=enqueue(self.store,self.owner,source['id'],'synthetic-legacy-run')
        with self.store.db() as db:db.execute("UPDATE extraction_runs SET state='failed' WHERE id=?",(run['id'],))
        with self.assertRaises(PermissionError):control(self.store,trusted,run['id'],'retry')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(source['job_id'],)).fetchone()['state'],'failed')
            self.assertEqual(db.execute('SELECT state FROM extraction_runs WHERE id=?',(run['id'],)).fetchone()['state'],'failed')
        self.assertEqual(self.model.calls,0)

    def test_real_mcp_and_rest_share_server_constraint(self):
        grant=dict(self.limited(),token_sha256=hashlib.sha256(b'synthetic-limited-secret').hexdigest())
        app=create_app(self.store,lambda:[grant],self.model,run_worker=False)
        with TestClient(app,base_url='http://127.0.0.1:5078') as c:
            h={'Authorization':'Bearer synthetic-limited-secret','Accept':'application/json, text/event-stream'}
            def rpc(name,args):
                return c.post('/mcp/',headers=h,json={'jsonrpc':'2.0','id':1,'method':'tools/call',
                       'params':{'name':name,'arguments':args}}).json()['result']
            args={'scope':'personal','source_key':'synthetic-mcp','messages':self.body()['messages']}
            first=rpc('memory_import',args)
            self.assertFalse(first.get('isError',False))
            sid=json.loads(first['content'][0]['text'])['id']
            self.assertTrue(rpc('memory_import',args|{'processing_policy':'extract'})['isError'])
            self.assertTrue(rpc('memory_reextract',{'source_id':sid,'request_key':'synthetic-blocked'})['isError'])
            self.assertEqual(c.post(self.prefix+'/sources',headers=h,json=self.body(source_key='synthetic-rest')).status_code,202)
            self.assertEqual(c.post(self.prefix+'/sources',headers=h,json=self.body(processing_policy='extract')).status_code,403)
            self.assertEqual(c.post(self.prefix+'/materials/'+sid+'/reextract',headers=h,json={'request_key':'synthetic-rest-run'}).status_code,403)
        self.assertFalse(self.store.process_one(self.model));self.assertEqual(self.model.calls,0)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM extraction_runs').fetchone()['n'],0)

class ArchiveOnlyBulkTest(unittest.TestCase):
    # Reuse an explicitly synthetic archive catalogue and private temp Store.
    from test_memory_bulk import BulkTest as _fixture
    setUp=_fixture.setUp
    tearDown=_fixture.tearDown

    def test_create_resume_retry_limit_blocked_but_pause_retained(self):
        from test_memory_bulk import BATCH
        p=dict(self.owner,archive_only=True)
        with self.assertRaises(PermissionError):self.bulk.create(p,BATCH,100000)
        batch_id=self.bulk.create(self.owner,BATCH,100000)['id']
        self.bulk.control(p,batch_id,'pause')
        for action in ('resume','retry_failed','set_limit'):
            with self.subTest(action=action), self.assertRaises(PermissionError):
                self.bulk.control(p,batch_id,action,200000)
        self.assertEqual(self.bulk.status(self.owner,batch_id)['state'],'paused')

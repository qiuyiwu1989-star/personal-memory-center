"""Synthetic automatic-ingest/index integration; no model/provider/production use."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pipeline.memory_center.core import Store
from pipeline.memory_center import source_discovery as discovery
from pipeline.memory_center import source_index_queue as queue
from pipeline.memory_center.postgres import Connection

class IndexQueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.p={'id':'synthetic-importer','owner':'synthetic-owner','scopes':['synthetic-scope'],'actions':['read','source_read','write'],'trusted_user':False}
        self.body={'scope':'synthetic-scope','source_key':'synthetic-integration','source_type':'document','processing_policy':'archive','messages':[{'id':'one','role':'external','text':'合成自动索引预算资料'}]}
    def test_archive_ingest_queues_once_and_indexes_without_cost_or_facts(self):
        first=self.store.ingest(self.p,self.body)
        self.assertFalse(first['duplicate'])
        self.assertEqual(queue.status(self.store,self.p,self.body['scope'])['generation'],1)
        self.assertTrue(self.store.ingest(self.p,self.body)['duplicate'])
        self.assertEqual(queue.status(self.store,self.p,self.body['scope'])['generation'],1)
        with self.store.db() as db:
            before={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in ('sources','jobs','records','model_budgets','model_attempts')}
        result=queue.work_once(self.store,debounce_seconds=0)
        self.assertEqual(result['state'],'ready');self.assertEqual(result['model_calls'],0)
        found=discovery.search(self.store,self.p,self.body['scope'],'预算')
        self.assertEqual(found['total'],1);self.assertEqual(found['results'][0]['role'],'external');self.assertFalse(found['facts_confirmed'])
        with self.store.db() as db:
            after={name:[dict(r) for r in db.execute('SELECT * FROM '+name)] for name in before}
        self.assertEqual(before,after)
    def test_queue_failure_rolls_back_ingest_source_job_and_envelope(self):
        with patch('pipeline.memory_center.source_index_queue.enqueue',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):self.store.ingest(self.p,self.body)
        with self.store.db() as db:
            for name in ('sources','jobs','source_envelopes','scope_index_queue'):
                self.assertEqual(db.execute('SELECT count(*) n FROM '+name).fetchone()['n'],0)

    def test_workbench_materials_separate_index_and_extraction_state(self):
        self.store.ingest(self.p,self.body)
        owner=dict(self.p,trusted_user=True)
        first=self.store.materials(owner)['materials'][0]
        self.assertEqual(first['state'],'archived')
        self.assertEqual(first['index_status']['state'],'pending')
        queue.work_once(self.store,debounce_seconds=0)
        ready=self.store.materials(owner)['materials'][0]
        self.assertEqual(ready['state'],'archived')
        self.assertEqual(ready['index_status']['state'],'ready')
    def test_postgres_adapter_maps_claim_lock_to_transaction_lock(self):
        class FakePG:
            def __init__(self):self.calls=[]
            def execute(self,sql,params=()):self.calls.append((sql,params));return object()
        pg=FakePG();adapter=Connection(pg)
        adapter.execute('BEGIN IMMEDIATE')
        adapter.execute('SELECT * FROM scope_index_queue WHERE owner=? AND scope=?',('synthetic-owner','synthetic-scope'))
        self.assertEqual(pg.calls[0][0],'SELECT pg_advisory_xact_lock(7169283401)')
        self.assertEqual(pg.calls[1],('SELECT * FROM scope_index_queue WHERE owner=%s AND scope=%s',('synthetic-owner','synthetic-scope')))

    def test_queue_migration_split_is_valid_for_postgres_adapter(self):
        class FakePG:
            def __init__(self):self.calls=[]
            def execute(self,sql,params=()):self.calls.append(sql)
        pg=FakePG()
        Connection(pg).executescript(Path('pipeline/memory_center/migrations/006_scope_index_queue.sql').read_text())
        self.assertEqual(len(pg.calls),2)
        for sql in pg.calls:
            meaningful='\n'.join(line for line in sql.splitlines() if not line.lstrip().startswith('--')).strip()
            self.assertTrue(meaningful.startswith(('CREATE TABLE','CREATE INDEX')))

if __name__=='__main__':unittest.main()

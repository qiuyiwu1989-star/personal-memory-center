"""Synthetic scope-coalesced technical queue; no providers or production data."""
import tempfile
import time
import unittest
from unittest.mock import patch
from pipeline.memory_center.core import Store,Invalid,encoded
from pipeline.memory_center import source_index_queue as queue


class SourceIndexQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name);queue.setup(self.store)
        self.owner='synthetic-owner';self.scope='synthetic-scope'
        self.p={'id':'synthetic-reader','owner':self.owner,'scopes':[self.scope],
                'actions':['read','source_read','write'],'trusted_user':True}

    def enqueue(self,owner=None,scope=None):
        with self.store.db() as db:queue.enqueue(db,owner or self.owner,scope or self.scope)

    def work(self):return queue.work_once(self.store,debounce_seconds=0)

    def test_coalesces_generation_and_transaction_rollback(self):
        self.enqueue();self.enqueue();self.enqueue()
        status=queue.status(self.store,self.p,self.scope)
        self.assertEqual(status['generation'],3);self.assertEqual(status['state'],'pending')
        with self.assertRaises(RuntimeError):
            with self.store.db() as db:
                queue.enqueue(db,self.owner,self.scope)
                raise RuntimeError('synthetic rollback')
        self.assertEqual(queue.status(self.store,self.p,self.scope)['generation'],3)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM scope_index_queue').fetchone()['n'],1)

    def test_dirty_generation_during_work_not_lost(self):
        self.enqueue()
        def newer_import(store,principal,scope):
            self.assertEqual(principal['owner'],self.owner)
            self.assertEqual(principal['scopes'],[self.scope])
            self.assertFalse(principal['trusted_user'])
            self.assertEqual(set(principal['actions']),{'read','source_read','write'})
            self.enqueue()
            return {'indexed_sources':1,'confirmed_facts':0}
        with patch('pipeline.memory_center.source_discovery.rebuild',newer_import):
            self.assertEqual(self.work()['state'],'pending')
        state=queue.status(self.store,self.p,self.scope)
        self.assertEqual(state['generation'],2);self.assertTrue(state['dirty'])
        with patch('pipeline.memory_center.source_discovery.rebuild',return_value={'confirmed_facts':0}):
            self.assertEqual(self.work()['state'],'ready')
        state=queue.status(self.store,self.p,self.scope)
        self.assertEqual(state['indexed_generation'],2);self.assertFalse(state['dirty'])

    def test_nonexpired_lease_and_stolen_lease_cannot_finish(self):
        self.enqueue()
        def stolen(store,principal,scope):
            with self.store.db() as db:
                db.execute("UPDATE scope_index_queue SET lease='synthetic-other-lease',lease_until=?",(time.time()+100,))
            return {'confirmed_facts':0}
        with patch('pipeline.memory_center.source_discovery.rebuild',stolen):
            self.assertEqual(self.work()['state'],'lease_lost')
        self.assertEqual(self.work()['state'],'idle')
        self.assertEqual(queue.status(self.store,self.p,self.scope)['indexed_generation'],0)

    def test_expired_lease_recovered(self):
        self.enqueue()
        with self.store.db() as db:
            db.execute("UPDATE scope_index_queue SET state='processing',lease='synthetic-expired',lease_until=?",(time.time()-1,))
        with patch('pipeline.memory_center.source_discovery.rebuild',return_value={'confirmed_facts':0}):
            self.assertEqual(self.work()['state'],'ready')
        self.assertFalse(queue.status(self.store,self.p,self.scope)['dirty'])

    def test_failure_stores_only_type_and_bounded_retry(self):
        self.enqueue()
        with patch('pipeline.memory_center.source_discovery.rebuild',side_effect=RuntimeError('synthetic secret source body')):
            result=self.work()
        self.assertEqual(result['state'],'failed');self.assertEqual(result['error_type'],'RuntimeError')
        state=queue.status(self.store,self.p,self.scope)
        self.assertEqual(state['error_type'],'RuntimeError');self.assertLessEqual(state['retry_after']-time.time(),60)
        with self.store.db() as db:
            self.assertNotIn('secret','\n'.join(db.iterdump()))
            db.execute('UPDATE scope_index_queue SET retry_after=?',(time.time()-1,))
        with patch('pipeline.memory_center.source_discovery.rebuild',return_value={'confirmed_facts':0}):
            self.assertEqual(self.work()['state'],'ready')

    def test_only_one_scope_claimed_and_owner_isolated_status(self):
        self.enqueue();self.enqueue('other-owner','other-scope')
        with patch('pipeline.memory_center.source_discovery.rebuild',return_value={'confirmed_facts':0}) as rebuild:
            self.work();self.assertEqual(rebuild.call_count,1)
        self.assertEqual(queue.status(self.store,dict(self.p,owner='absent-owner'),self.scope)['state'],'idle')
        with self.assertRaises(PermissionError):queue.status(self.store,dict(self.p,actions=[]),self.scope)
        with self.assertRaises(PermissionError):queue.status(self.store,self.p,'other-scope')
        metadata=queue.status(self.store,self.p,self.scope)
        self.assertLess(len(encoded(metadata)),600)
        self.assertNotIn('lease',metadata);self.assertNotIn('owner',metadata)

    def test_debounce_merges_burst_without_claiming_each_source(self):
        self.enqueue()
        with patch('pipeline.memory_center.source_discovery.rebuild') as rebuild:
            self.assertEqual(queue.work_once(self.store)['state'],'idle');rebuild.assert_not_called()
        with self.store.db() as db:db.execute('UPDATE scope_index_queue SET updated=?',(time.time()-3,))
        with patch('pipeline.memory_center.source_discovery.rebuild',return_value={'confirmed_facts':0}):
            self.assertEqual(queue.work_once(self.store)['state'],'ready')

    def test_real_rebuild_does_not_extract_or_change_source_fact_or_budget(self):
        imported=self.store.ingest(self.p,{'scope':self.scope,'source_key':'synthetic-source','processing_policy':'archive',
            'messages':[{'id':'synthetic-message','role':'user','text':'合成预算材料'}]})
        self.enqueue()
        with self.store.db() as db:
            before_source=dict(db.execute('SELECT * FROM sources WHERE id=?',(imported['id'],)).fetchone())
            before_job=dict(db.execute('SELECT * FROM jobs WHERE id=?',(imported['job_id'],)).fetchone())
            before_budget=[dict(r) for r in db.execute('SELECT * FROM model_budgets')]
        result=self.work()
        self.assertEqual(result['state'],'ready');self.assertEqual(result['model_calls'],0);self.assertEqual(result['extraction_tokens'],0)
        with self.store.db() as db:
            self.assertEqual(before_source,dict(db.execute('SELECT * FROM sources WHERE id=?',(imported['id'],)).fetchone()))
            self.assertEqual(before_job,dict(db.execute('SELECT * FROM jobs WHERE id=?',(imported['job_id'],)).fetchone()))
            self.assertEqual(before_budget,[dict(r) for r in db.execute('SELECT * FROM model_budgets')])
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],0)
            self.assertEqual(db.execute('SELECT count(*) n FROM source_discovery_chunks').fetchone()['n'],1)

    def test_invalid_internal_keys_and_timing_parameters(self):
        with self.store.db() as db:
            for bad in ('',None,True):
                with self.assertRaises(Invalid):queue.enqueue(db,bad,self.scope)
        for bad in (0,901,True,float('nan')):
            with self.assertRaises(Invalid):queue.work_once(self.store,lease_seconds=bad)
        for bad in (-1,61,True):
            with self.assertRaises(Invalid):queue.work_once(self.store,debounce_seconds=bad)


    def test_worker_preserves_legacy_visibility_exclusion(self):
        self.store.ingest(self.p,{'scope':self.scope,'source_key':'claude:archive:synthetic-legacy','processing_policy':'archive',
            'messages':[{'id':'synthetic-legacy','role':'assistant','text':'旧扁平投影不能证明可见'}]})
        self.enqueue()
        result=self.work()
        self.assertEqual(result['state'],'ready')
        self.assertEqual(result['index']['skipped_legacy_sources'],1)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM source_discovery_chunks').fetchone()['n'],0)


if __name__=='__main__':unittest.main()

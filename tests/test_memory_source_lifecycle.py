"""Synthetic source withdrawal acceptance; no real credentials or model calls."""
import json
import unittest
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid, Conflict, encoded
from pipeline.memory_center import source_lifecycle as lifecycle
from pipeline.memory_center import source_discovery as discovery
from pipeline.memory_center.governance import context, review
from pipeline.memory_center.documents import define_topic, build_documents
from pipeline.memory_center.reprocessing import enqueue, process_one as process_run


class SourceLifecycleTest(unittest.TestCase):
    setUp = baseline.MemoryTest.setUp
    tearDown = baseline.MemoryTest.tearDown
    body = baseline.MemoryTest.body
    ingest = baseline.MemoryTest.ingest
    rows = baseline.MemoryTest.rows

    def verify(self, rid):
        review(self.store,self.owner,rid,{'revision':0,'state':'verified','holder':'owner:q',
                                      'subject_id':'owner:q','as_of':'2000-01-01'})

    def test_permission_idempotency_and_preserved_bytes(self):
        source=self.ingest()
        with self.store.db() as db:
            original=dict(db.execute('SELECT * FROM sources WHERE id=?',(source['id'],)).fetchone())
        for p in (dict(self.owner,trusted_user=False),dict(self.owner,actions=['read']),dict(self.owner,scopes=[])):
            with self.assertRaises(PermissionError):lifecycle.withdraw(self.store,p,'personal',source['id'])
        with self.assertRaises(Invalid):lifecycle.withdraw(self.store,dict(self.owner,owner='other'),'personal',source['id'])
        receipt=lifecycle.withdraw(self.store,self.owner,'personal',source['id'],'synthetic withdrawal')
        again=lifecycle.withdraw(self.store,self.owner,'personal',source['id'],'different retry note')
        self.assertTrue(again['duplicate']);self.assertEqual(receipt['withdrawn_at'],again['withdrawn_at'])
        with self.store.db() as db:
            self.assertEqual(original,dict(db.execute('SELECT * FROM sources WHERE id=?',(source['id'],)).fetchone()))
            self.assertEqual(db.execute('SELECT count(*) n FROM source_withdrawals').fetchone()['n'],1)
        self.assertEqual(self.rows(),[])
        self.assertTrue(self.rows(history=True)[0]['source_withdrawn'])
        self.assertFalse(self.rows(history=True)[0]['usable'])
        self.assertEqual(self.store.material(self.owner,source['id'])['messages'][0]['text'],self.body()['messages'][0]['text'])

    def test_context_index_documents_and_independent_evidence(self):
        source=self.ingest();self.verify(self.rows()[0]['id'])
        second=self.ingest(source_key='chat-2');self.verify(next(r['id'] for r in self.rows() if r['source_id']==second['id']))
        before=context(self.store,self.owner,'personal','')
        p=dict(self.owner,actions=['read','write','source_read'])
        discovery.rebuild(self.store,p,'personal')
        hit=next(r for r in discovery.search(self.store,p,'personal','结论')['results'] if r['source_id']==source['id'])
        define_topic(self.store,self.owner,'personal','synthetic','Synthetic',['chat-'])
        docs=build_documents(self.store,self.owner,'personal')
        original_doc=next(d for d in docs if d['slug']=='synthetic')
        lifecycle.withdraw(self.store,self.owner,'personal',source['id'])
        after=context(self.store,self.owner,'personal','')
        self.assertNotEqual(before['context_revision'],after['context_revision'])
        self.assertEqual([r['source_id'] for r in after['records']],[second['id']])
        self.assertEqual({r['source_id'] for r in discovery.search(self.store,p,'personal','结论')['results']},{second['id']})
        with self.assertRaises(Invalid):discovery.read(self.store,p,'personal',hit['locator'])
        current=next(d for d in build_documents(self.store,self.owner,'personal') if d['slug']=='synthetic')
        self.assertGreater(current['revision'],original_doc['revision'])
        self.assertTrue(all(d['id'] not in {r['id'] for r in self.rows(history=True) if r['source_id']==source['id']} for d in current['dependencies']))
        with self.store.db() as db:
            self.assertTrue(db.execute('SELECT revision FROM document_versions WHERE slug=? AND revision=?',('synthetic',original_doc['revision'])).fetchone())
        discovery.rebuild(self.store,p,'personal')
        self.assertEqual(discovery.search(self.store,p,'personal','结论')['total'],1)

    def test_cancel_queued_and_deny_reextract(self):
        source=self.store.ingest(self.owner,self.body())
        run=enqueue(self.store,self.owner,source['id'],'synthetic-run')
        receipt=lifecycle.withdraw(self.store,self.owner,'personal',source['id'])
        self.assertEqual(receipt['counts']['jobs_cancelled'],1)
        self.assertEqual(receipt['counts']['runs_cancelled'],1)
        self.assertFalse(self.store.process_one(self.model));self.assertEqual(self.model.calls,0)
        with self.assertRaises(Invalid):enqueue(self.store,self.owner,source['id'],'synthetic-next')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM extraction_runs WHERE id=?',(run['id'],)).fetchone()['state'],'withdrawn')

    def test_inflight_worker_does_not_repopulate_and_usage_retained(self):
        source=self.store.ingest(self.owner,self.body())
        outer=self
        class RacingModel(baseline.FakeModel):
            def extract(self,messages):
                lifecycle.withdraw(outer.store,outer.owner,'personal',source['id'])
                return super().extract(messages)
        self.assertTrue(self.store.process_one(RacingModel()))
        self.assertEqual(self.rows(history=True),[])
        with self.store.db() as db:
            job=db.execute('SELECT state,usage FROM jobs WHERE id=?',(source['job_id'],)).fetchone()
            self.assertEqual(job['state'],'withdrawn')
            self.assertEqual(json.loads(job['usage'])['prompt_tokens'],17)

    def test_inflight_error_usage_survives_withdrawal(self):
        source=self.store.ingest(self.owner,self.body())
        outer=self
        class RacingFailure(baseline.FakeModel):
            def extract(self,messages):
                lifecycle.withdraw(outer.store,outer.owner,'personal',source['id'])
                error=Invalid('synthetic provider failure')
                error.usage={'prompt_tokens':19,'completion_tokens':2}
                raise error
        self.assertTrue(self.store.process_one(RacingFailure()))
        with self.store.db() as db:
            job=db.execute('SELECT state,usage FROM jobs WHERE id=?',(source['job_id'],)).fetchone()
            self.assertEqual(job['state'],'withdrawn')
            self.assertEqual(json.loads(job['usage'])['prompt_tokens'],19)
        self.assertEqual(self.rows(history=True),[])

    def test_inflight_reextract_preserves_metering_and_not_ready(self):
        source=self.store.ingest(self.owner,self.body(processing_policy='archive'))
        run=enqueue(self.store,self.owner,source['id'],'synthetic-racing-run')
        outer=self
        class RacingModel(baseline.FakeModel):
            def extract(self,messages):
                lifecycle.withdraw(outer.store,outer.owner,'personal',source['id'])
                return super().extract(messages)
        self.assertTrue(process_run(self.store,RacingModel()))
        with self.store.db() as db:
            row=db.execute('SELECT state,usage FROM extraction_runs WHERE id=?',(run['id'],)).fetchone()
            self.assertEqual(row['state'],'withdrawn')
            self.assertEqual(json.loads(row['usage'])['completion_tokens'],9)
        self.assertEqual(self.rows(history=True),[])

    def test_preview_bounded_and_candidate_rank_count(self):
        source=self.ingest()
        for n in (1000,2000,6000):
            result=lifecycle.preview(self.store,self.owner,'personal',source['id'],n)
            self.assertLessEqual(len(encoded(result)),n)
            self.assertTrue(result['archive_retained'])
        lifecycle.withdraw(self.store,self.owner,'personal',source['id'])
        self.assertEqual(self.store.candidate_reports(self.owner,'personal')['total'],0)

    def test_unsettled_bulk_blocked_then_settled_allowed(self):
        source=self.ingest()
        with self.store.db() as db:
            db.execute("INSERT INTO bulk_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ('synthetic-batch','q','synthetic-archive','personal','paused',100000,35000,1,1,1,0,0,1.0))
            db.execute("INSERT INTO bulk_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ('synthetic-segment','synthetic-batch','synthetic-conversation',0,'chat-1','[]','conversation',
                        'sample','queued',source['job_id'],0,1,35000,0,None,1.0))
        self.assertEqual(lifecycle.preview(self.store,self.owner,'personal',source['id'])['blockers'],['bulk_processing_or_unsettled'])
        with self.assertRaises(Conflict):lifecycle.withdraw(self.store,self.owner,'personal',source['id'])
        self.assertEqual(len(self.rows()),1)
        with self.store.db() as db:
            db.execute("UPDATE bulk_segments SET state='applied',attempts_counted=1,reserved_tokens=0,spent_tokens=26 WHERE id='synthetic-segment'")
        self.assertEqual(lifecycle.preview(self.store,self.owner,'personal',source['id'])['blockers'],[])
        self.assertEqual(lifecycle.withdraw(self.store,self.owner,'personal',source['id'])['state'],'withdrawn')

    def test_bulk_retry_cannot_requeue_withdrawn_source(self):
        from pipeline.memory_center.bulk import Bulk
        from pipeline.memory_center.claude import PARSER_VERSION
        source=self.ingest()
        with self.store.db() as db:
            db.execute("INSERT INTO bulk_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ('synthetic-batch','q','synthetic-archive','personal','paused',100000,26,1,1,1,0,0,1.0))
            db.execute("INSERT INTO bulk_batch_parsers VALUES(?,?)",('synthetic-batch',PARSER_VERSION))
            db.execute("INSERT INTO bulk_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ('synthetic-segment','synthetic-batch','synthetic-conversation',0,'chat-1','[]','conversation',
                        'sample','failed',source['job_id'],1,1,0,26,'synthetic',1.0))
            db.execute("UPDATE jobs SET state='failed' WHERE id=?",(source['job_id'],))
        lifecycle.withdraw(self.store,self.owner,'personal',source['id'])
        with self.assertRaisesRegex(Invalid,'没有可重试'):Bulk(self.store).control(dict(self.owner,scopes=self.owner['scopes']+['claude:archive']),'synthetic-batch','retry_failed')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM jobs WHERE id=?',(source['job_id'],)).fetchone()['state'],'failed')
            self.assertEqual(db.execute("SELECT reserved_tokens FROM bulk_segments WHERE id='synthetic-segment'").fetchone()['reserved_tokens'],0)

    def test_missing_migration_fails_closed_for_mutation(self):
        source=self.ingest()
        with self.store.db() as db:db.execute('DROP TABLE source_withdrawals')
        self.assertEqual(len(self.rows()),1)
        with self.assertRaisesRegex(Invalid,'009'):lifecycle.withdraw(self.store,self.owner,'personal',source['id'])

if __name__=='__main__':unittest.main()

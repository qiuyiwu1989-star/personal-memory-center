"""Synthetic trusted-entry regression tests; editing is not confirmation."""
import concurrent.futures
import threading
import unittest
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid, Conflict
from pipeline.memory_center.governance import context, review, usable


class TrustedEntryTest(unittest.TestCase):
    setUp=baseline.MemoryTest.setUp
    tearDown=baseline.MemoryTest.tearDown
    body=baseline.MemoryTest.body
    ingest=baseline.MemoryTest.ingest
    rows=baseline.MemoryTest.rows

    def verify(self,rid,revision=0,**extra):
        return review(self.store,self.owner,rid,dict(revision=revision,state='verified',
            holder='owner:q',subject_id='owner:q',as_of='2000-01-01',**extra))

    def correct(self,row,**extra):
        return self.store.correct(self.owner,row['id'],dict(statement='Synthetic revised report.',
            revision=row['revision']) | extra)

    def test_correction_does_not_promote_then_explicit_review_uses_contract(self):
        self.ingest();old=self.rows()[0];result=self.correct(old)
        row=self.rows()[0]
        self.assertEqual(row['governance']['state'],'candidate')
        self.assertIsNone(row['governance']['holder'])
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],0)
        self.verify(result['id'],revision=1)
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],1)

    def test_changed_verified_assertion_requires_new_confirmation_preserves_history(self):
        self.ingest();old=self.rows()[0];self.verify(old['id']);previous=self.rows()[0]
        self.correct(previous)
        self.assertEqual(context(self.store,self.owner,'personal','')['records'],[])
        history=self.rows(history=True);retired=next(r for r in history if r['id']==old['id'])
        self.assertEqual(retired['lifecycle'],'superseded')
        for field in ('source_id','quote','statement','governance'):
            self.assertEqual(retired[field],previous[field])
        self.assertEqual(self.rows()[0]['supersedes'],old['id'])

    def test_legacy_missing_and_owner_corrected_governance_fail_closed_without_rewrite(self):
        self.ingest();result=self.correct(self.rows()[0]);rid=result['id']
        with self.store.db() as db:db.execute('DELETE FROM record_governance WHERE record_id=?',(rid,))
        self.assertEqual(self.rows()[0]['governance']['state'],'candidate')
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],0)
        with self.store.db() as db:
            db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                (rid,None,None,None,None,'owner_corrected','P3',0,'Synthetic legacy marker',0))
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],0)
        self.assertEqual(self.rows()[0]['governance']['state'],'owner_corrected')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM record_governance WHERE record_id=?',(rid,)).fetchone()['state'],'owner_corrected')

    def test_verified_read_contract_rejects_incomplete_or_malformed_metadata(self):
        self.ingest();row=self.rows()[0];self.verify(row['id']);row=self.rows()[0]
        self.assertTrue(usable(row))
        for patch in ({'holder':None},{'subject_id':None},{'as_of':None},
                      {'as_of':'2000-1-1'},{'valid_until':'nonsense'},{'state':'owner_corrected'}):
            self.assertFalse(usable(dict(row,governance=dict(row['governance'],**patch))))

    def test_correct_rejects_silent_confirmation_fields_boolean_revision_and_spoof(self):
        self.ingest();row=self.rows()[0]
        for patch in ({'explicit_confirmation':True},{'governance':{'state':'verified'}},
                      {'revision':True}):
            with self.assertRaises(Invalid):self.correct(row,**patch)
        with self.assertRaises(PermissionError):
            self.store.correct(dict(self.owner,trusted_user='yes'),row['id'],{'revision':1,'statement':'Synthetic'})
        self.assertEqual(len(self.rows(history=True)),1)

    def test_confirm_requires_registered_identity_current_time_and_owner_permission(self):
        self.ingest();rid=self.correct(self.rows()[0])['id']
        base=dict(revision=1,state='verified',holder='owner:q',subject_id='owner:q',as_of='2000-01-01')
        for patch in ({'holder':'synthetic-unregistered'},{'as_of':'2099-01-01'},
                      {'valid_until':'2001-01-01'},{'subject_id':None}):
            with self.assertRaises(Invalid):review(self.store,self.owner,rid,dict(base,**patch))
        with self.assertRaises(PermissionError):review(self.store,dict(self.owner,trusted_user=False),rid,base)
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],0)

    def test_parallel_corrections_serialize_and_stale_review_cannot_restore_old(self):
        self.ingest();old=self.rows()[0];barrier=threading.Barrier(2)
        def attempt():
            barrier.wait()
            try:return self.correct(old)
            except Conflict:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sum(result is not None for result in results),1)
        with self.assertRaises(Conflict):self.verify(old['id'])
        self.assertEqual(len(self.rows(history=True)),2)
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],0)

    def test_concurrent_review_and_correction_never_trust_changed_assertion(self):
        self.ingest();old=self.rows()[0];barrier=threading.Barrier(2)
        def correction():
            barrier.wait();return self.correct(old)
        def confirmation():
            barrier.wait()
            try:return self.verify(old['id'])
            except Conflict:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            correction_future=pool.submit(correction);review_future=pool.submit(confirmation)
            correction_future.result();review_future.result()
        self.assertEqual(self.rows()[0]['governance']['state'],'candidate')
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],0)


if __name__=='__main__':unittest.main()

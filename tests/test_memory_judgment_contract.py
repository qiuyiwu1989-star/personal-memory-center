"""Synthetic contract regression tests; no production sources or model service."""
import datetime
import unittest
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid, Conflict
from pipeline.memory_center.governance import review, context
from pipeline.memory_center.entities import register, listing
from pipeline.memory_center.judgment_contract import normalize, validate_verified


class JudgmentContractTest(unittest.TestCase):
    setUp = baseline.MemoryTest.setUp
    tearDown = baseline.MemoryTest.tearDown
    body = baseline.MemoryTest.body
    ingest = baseline.MemoryTest.ingest
    rows = baseline.MemoryTest.rows

    def valid(self):
        return {'state':'verified','revision':0,'holder':'owner:q','subject_id':'owner:q',
                'as_of':'2000-01-01','priority':'P1'}

    def test_review_rejects_future_expired_and_noncanonical_dates_atomically(self):
        self.ingest();rid=self.rows()[0]['id']
        today=datetime.date.today().isoformat()
        future=(datetime.date.today()+datetime.timedelta(days=1)).isoformat()
        for change in ({'as_of':future},{'valid_until':today},{'as_of':'20000101'},
                       {'as_of':'2000-W01-1'},{'revision':False},{'state':[]},
                       {'holder':[]},{'unknown':'synthetic'}):
            with self.subTest(change=change), self.assertRaises(Invalid):
                review(self.store,self.owner,rid,self.valid()|change)
        self.assertEqual(self.rows()[0]['governance']['revision'],0)
        self.assertEqual(self.rows()[0]['governance']['state'],'candidate')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM governance_events').fetchone()['n'],0)

    def test_unknowns_are_not_inferred_and_historical_is_not_current(self):
        self.ingest();rid=self.rows()[0]['id']
        gov=review(self.store,self.owner,rid,{'revision':0,'state':'candidate'})
        self.assertIsNone(gov['holder']);self.assertIsNone(gov['as_of'])
        review(self.store,self.owner,rid,self.valid()|{'revision':1,'state':'historical',
                                                   'valid_until':'2000-01-02'})
        self.assertEqual(context(self.store,self.owner,'personal','')['records'],[])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM governance_events').fetchone()['n'],2)

    def test_scoped_entities_and_owners_cannot_be_borrowed(self):
        self.ingest();rid=self.rows()[0]['id']
        register(self.store,self.owner,'project:demo',{'id':'synthetic:person','kind':'person','name':'合成人物'})
        other=dict(self.owner,owner='synthetic-other')
        register(self.store,other,'personal',{'id':'synthetic:other','kind':'person','name':'合成另一人'})
        for subject in ('synthetic:person','synthetic:other','owner:synthetic-other','unresolved:speaker-2'):
            with self.subTest(subject=subject),self.assertRaises(Invalid):
                review(self.store,self.owner,rid,self.valid()|{'subject_id':subject})
        register(self.store,self.owner,'personal',{'id':'synthetic:person','kind':'person','name':'合成人物'})
        review(self.store,self.owner,rid,self.valid()|{'subject_id':'synthetic:person'})
        self.assertEqual(context(self.store,self.owner,'personal','')['total'],1)

    def test_reserved_owner_entity_and_untrusted_review(self):
        for eid in ('owner:q','owner:someone'):
            with self.assertRaises(Invalid):
                register(self.store,self.owner,'personal',{'id':eid,'kind':'project','name':'合成项目'})
        self.assertEqual(listing(self.store,self.owner,'personal')['entities'][0]['kind'],'person')
        self.ingest();rid=self.rows()[0]['id']
        with self.assertRaises(PermissionError):
            review(self.store,dict(self.owner,trusted_user='true'),rid,self.valid())
        with self.assertRaises(PermissionError):
            review(self.store,dict(self.owner,scopes=['project:demo']),rid,self.valid())
        with self.assertRaises(Invalid):
            review(self.store,dict(self.owner,owner='synthetic-other'),rid,self.valid())

    def test_shared_contract_interval_and_explicit_holder(self):
        values=normalize({'state':'verified','holder':'owner:q','subject_id':'owner:q','as_of':'2000-01-01',
                          'valid_until':'2001-01-01'})
        with self.store.db() as db:
            validate_verified(db,'q','personal',values,today='2000-12-31')
            with self.assertRaises(Invalid):validate_verified(db,'q','personal',values,today='2001-01-01')
        self.assertIsNone(normalize({})['holder'])
        with self.assertRaises(Invalid):normalize({'state':'verified','as_of':'2000-01-01'})

    def test_verified_revision_retains_history_and_rejects_stale_write(self):
        self.ingest();rid=self.rows()[0]['id']
        review(self.store,self.owner,rid,self.valid())
        with self.assertRaises(Conflict):review(self.store,self.owner,rid,self.valid())
        review(self.store,self.owner,rid,{'revision':1,'state':'rejected','note':'合成撤回'})
        self.assertEqual(len(self.rows(history=True)),1)
        self.assertEqual(context(self.store,self.owner,'personal','')['records'],[])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM governance_events').fetchone()['n'],2)

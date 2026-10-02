"""Read-only scoped diagnostics over deliberately synthetic broken links."""
import contextlib
import json
import unittest
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid, encoded
from pipeline.memory_center.governance_diagnostics import diagnose


class GovernanceDiagnosticsTest(unittest.TestCase):
    setUp=baseline.MemoryTest.setUp
    tearDown=baseline.MemoryTest.tearDown

    def fixture(self):
        with self.store.db() as db:
            db.execute('INSERT INTO memory_entities VALUES(?,?,?,?,?,?)',
                       ('q','project:demo','synthetic:other-scope','person','合成名字','[]'))
            db.execute('INSERT INTO memory_entities VALUES(?,?,?,?,?,?)',
                       ('synthetic-other','personal','synthetic:foreign-owner','person','合成名字','[]'))
            for sid,scope,payload in (
                    ('s-good','personal',encoded([{'id':'m','role':'assistant','text':'SYNTHETIC PRIVATE BODY'}])),
                    ('s-cross','project:demo',encoded([{'id':'m','role':'user','text':'SYNTHETIC OTHER SCOPE'}])),
                    ('s-bad','personal','{}')):
                db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (sid,'q',scope,sid,sid,'document','synthetic-agent',0,payload,0))
            db.execute('INSERT INTO source_envelopes VALUES(?,?,?)',
                       ('s-good',encoded({'locator':'paragraph:synthetic'}),'archive'))
            for rid,source,mid,quote,sup,lifecycle in (
                    ('record-a','s-good','m','SYNTHETIC PRIVATE BODY',None,'active'),
                    ('record-b','s-cross','m','SYNTHETIC OTHER SCOPE','outside-record','active'),
                    ('record-c','s-good','absent','synthetic','record-a','superseded'),
                    ('record-d','s-bad','m','synthetic',None,'active')):
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (rid,'q','personal','topics','claim','SYNTHETIC SUBJECT','SYNTHETIC STATEMENT',
                            'agent_suggested',source,mid,quote,lifecycle,1,sup,0))
            db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('record-b','synthetic:other-scope','synthetic:foreign-owner','2000-01-01','2001-01-01',
                        'verified','P1',1,'SYNTHETIC NOTE',0))
            db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                       ('record-d','owner:q','owner:q','20000101',None,'candidate','P3',1,'',0))

    def reader(self):return dict(self.owner,actions=['read','source_read'],trusted_user=False)

    def test_counts_no_body_scoped_links_and_exclusive_expiry(self):
        self.fixture()
        result=diagnose(self.store,self.reader(),'personal',today='2001-01-01')
        self.assertEqual((result['record_count'],result['active_count']),(4,3))
        counts=result['counts']
        self.assertEqual(counts['missing_holder'],2)
        self.assertEqual(counts['missing_subject_id'],2)
        self.assertEqual(counts['missing_as_of'],2)
        self.assertEqual(counts['expired_active'],1)
        self.assertEqual(counts['invalid_effective_date'],1)
        self.assertEqual(counts['dangling_supersedes'],1)
        self.assertEqual(counts['cross_scope_entity_reference'],1)
        self.assertEqual(counts['unresolved_entity_reference'],1)
        self.assertEqual(counts['source_missing_or_outside_scope'],1)
        self.assertEqual(counts['source_message_missing'],1)
        self.assertEqual(counts['source_payload_invalid'],1)
        self.assertEqual(counts['source_original_locator_missing'],1)
        for secret in ('SYNTHETIC PRIVATE BODY','SYNTHETIC OTHER SCOPE','SYNTHETIC STATEMENT',
                       'SYNTHETIC SUBJECT','SYNTHETIC NOTE','synthetic:foreign-owner','outside-record'):
            self.assertNotIn(secret,encoded(result))

    def test_no_queries_or_existence_probe_in_unauthorized_scopes(self):
        self.fixture()
        p=dict(self.reader(),scopes=['personal'])
        narrow=diagnose(self.store,p,'personal')
        self.assertEqual(narrow['counts']['cross_scope_entity_reference'],0)
        self.assertEqual(narrow['counts']['unresolved_entity_reference'],1)
        with self.assertRaises(PermissionError):diagnose(self.store,p,'project:demo')
        with self.assertRaises(PermissionError):diagnose(self.store,dict(p,actions=['read']),'personal')
        other=dict(p,owner='synthetic-other')
        self.assertEqual(diagnose(self.store,other,'personal')['record_count'],0)

    def test_diagnosis_issues_no_ddl_dml_and_does_not_create_events(self):
        self.fixture();original_db=self.store.db;queries=[]
        with original_db() as db:
            before={t:db.execute('SELECT count(*) n FROM '+t).fetchone()['n']
                    for t in ('records','record_governance','events','governance_events')}
        @contextlib.contextmanager
        def traced():
            with original_db() as db:
                db.set_trace_callback(queries.append)
                yield db
        self.store.db=traced
        diagnose(self.store,self.reader(),'personal')
        self.store.db=original_db
        self.assertTrue(queries)
        self.assertTrue(all(q.lstrip().upper().startswith('SELECT') for q in queries),queries)
        with original_db() as db:
            after={t:db.execute('SELECT count(*) n FROM '+t).fetchone()['n'] for t in before}
        self.assertEqual(before,after)

    def test_response_budget_and_zero_sample_retains_counts(self):
        self.fixture()
        for budget in (1000,1600,6000,16000):
            result=diagnose(self.store,self.reader(),'personal',sample_limit=10,max_chars=budget)
            self.assertLessEqual(len(encoded(result)),budget)
            self.assertEqual(result['record_count'],4)
        self.assertEqual(diagnose(self.store,self.reader(),'personal',sample_limit=0)['samples'],{})
        for kwargs in ({'sample_limit':True},{'sample_limit':11},{'max_chars':999},{'today':'20010101'}):
            with self.assertRaises(Invalid):diagnose(self.store,self.reader(),'personal',**kwargs)

    def test_quote_gap_count_and_missing_optional_tables_are_not_repaired(self):
        self.fixture()
        with self.store.db() as db:
            db.execute("UPDATE records SET quote='SYNTHETIC ABSENT' WHERE id='record-a'")
            db.execute('DROP TABLE source_envelopes')
        result=diagnose(self.store,self.reader(),'personal')
        self.assertEqual(result['counts']['source_quote_missing_or_mismatch'],1)
        self.assertIn('source_envelopes',result['coverage_missing'])
        with self.store.db() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='source_envelopes'").fetchone())

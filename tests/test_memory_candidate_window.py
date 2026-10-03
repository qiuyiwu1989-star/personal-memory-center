"""Synthetic exact ranking/counts with bounded candidate source hydration."""
import unittest
from unittest.mock import patch
import test_memory_evidence_bundle as baseline
from pipeline.memory_center.core import encoded,Invalid
from pipeline.memory_center import core,reading
from pipeline.memory_center.evidence_bundle import bundle


class CandidateWindowTest(unittest.TestCase):
    setUp=baseline.EvidenceBundleTest.setUp

    def seed(self,count):
        with self.store.db() as db:
            template=dict(db.execute("SELECT * FROM sources LIMIT 1").fetchone())
            columns=tuple(template)
            for i in range(count):
                source='synthetic-window-source-'+str(i)
                raw=dict(template,id=source,source_key=source,payload=encoded([{'id':'m','role':'user','text':'Synthetic payload '+str(i),'created_at':'2000-01-01','source_title':'Synthetic Atlas title'}]))
                db.execute('INSERT INTO sources ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(raw[key] for key in columns))
                text=('Atlas focus' if i%5==0 else 'Atlas other')+' synthetic '+str(i)
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('window-'+str(i),self.p['owner'],self.scope,'projects','claim','Atlas',text,'source_reported',source,'m',text,'active',1,None,i//3))

    def test_large_scope_exact_count_and_rank_only_window_source_hydrated(self):
        self.seed(5000)
        expected=self.store.snapshot(self.p,self.scope,'focus',limit=1000000,governance_filter='candidate',include_jobs=False)
        original=core.json.loads;payloads=[]
        def observing(value,*args,**kwargs):
            if isinstance(value,str) and 'Synthetic payload ' in value:payloads.append(value)
            return original(value,*args,**kwargs)
        with patch('pipeline.memory_center.core.json.loads',side_effect=observing):
            result=self.store.candidate_reports(self.p,self.scope,'focus',window_limit=7,offset=5)
        self.assertEqual(result['total'],1000)
        self.assertEqual([row['id'] for row in result['records']],[row['id'] for row in expected['records'][5:12]])
        self.assertEqual(len(payloads),7)
        self.assertEqual(result['coverage'],{'mode':'ranked_window','offset':5,'examined':7,'continue_offset':12})
        self.assertTrue(result['truncated'])
        self.assertTrue(all(row['source_date']=='2000-01-01' for row in result['records']))

    def test_default_page_compatibility_all_modes_and_translations(self):
        self.seed(15)
        with self.store.db() as db:
            db.execute('INSERT INTO record_translations VALUES(?,?,?,?,?)',('window-1','zh','Atlas focus synthetic translation','synthetic',0))
        for mode in ('lexical-v1','lexical-v2','lexical-v3'):
            for query in ('','Atlas','focus','missing-project'):
                snapshot=self.store.snapshot(self.p,self.scope,query,limit=1000000,governance_filter='candidate',retrieval_mode=mode,include_jobs=False)
                expected=reading.search_page(snapshot,16000)
                result=self.store.candidate_reports(self.p,self.scope,query,retrieval_mode=mode)
                coverage=result.pop('coverage')
                self.assertEqual(result,expected)
                self.assertEqual(coverage['mode'],'ranked_window' if mode=='lexical-v1' else 'legacy_full_scope')

    def test_oversize_items_and_bundle_trim_do_not_rewrite_examined_ranks(self):
        self.seed(6)
        with self.store.db() as db:db.execute("UPDATE records SET statement=? WHERE id='window-3'",('Atlas '+('x'*20000),))
        result=self.store.candidate_reports(self.p,self.scope,'Atlas',window_limit=3,max_chars=16000)
        self.assertEqual(result['coverage']['examined'],3)
        self.assertEqual(result['coverage']['continue_offset'],3)
        self.assertLess(len(result['records']),3)
        continued=self.store.candidate_reports(self.p,self.scope,'Atlas',window_limit=3,offset=3)
        self.assertEqual(continued['coverage']['offset'],3)
        self.assertFalse(set(row['id'] for row in result['records']) & set(row['id'] for row in continued['records']))
        for budget in (1500,2000,3000,6000,16000):
            bundled=bundle(self.store,self.p,self.scope,'Atlas',max_chars=budget)
            self.assertLessEqual(len(encoded(bundled)),budget)
            self.assertEqual(bundled['source_reports']['coverage']['examined'],7)
            self.assertIsNone(bundled['source_reports']['coverage']['continue_offset'])
            self.assertTrue(bundled['source_reports']['truncated'])

    def test_equal_created_has_deterministic_id_order(self):
        self.seed(15)
        result=self.store.candidate_reports(self.p,self.scope,'Atlas',window_limit=16)
        observed=[row['id'] for row in result['records'] if row['id'].startswith('window-')]
        expected=[f'window-{i}' for i in sorted(range(15),key=lambda i:(-int(i//3),f'window-{i}'))]
        self.assertEqual(observed,expected)

    def test_offset_limit_does_not_advertise_an_invalid_continuation(self):
        self.seed(10150)
        result=self.store.candidate_reports(self.p,self.scope,'Atlas',offset=10000)
        self.assertEqual(result['coverage']['examined'],128)
        self.assertIsNone(result['coverage']['continue_offset'])
        self.assertTrue(result['coverage']['offset_limit_reached'])
        self.assertEqual(result['total'],10151)

    def test_permissions_and_window_boundaries(self):
        with self.assertRaises(PermissionError):self.store.candidate_reports(self.p,self.scope+'-other')
        with self.assertRaises(PermissionError):self.store.candidate_reports(self.p|{'actions':[]},self.scope)
        other=self.store.candidate_reports(self.p|{'owner':'synthetic-other-owner'},self.scope)
        self.assertEqual(other['total'],0)
        self.assertEqual(other['records'],[])
        for kwargs in ({'window_limit':129},{'window_limit':True},{'offset':-1},{'offset':10001},{'max_chars':499},{'retrieval_mode':'unknown'}):
            with self.assertRaises(Invalid):self.store.candidate_reports(self.p,self.scope,**kwargs)


if __name__=='__main__':unittest.main()

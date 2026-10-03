"""Synthetic provenance budgets and hydration cost regressions."""
import unittest
from unittest.mock import patch
import test_memory_evidence_bundle as baseline
from pipeline.memory_center.core import encoded
from pipeline.memory_center.evidence_bundle import bundle
from pipeline.memory_center.reading import search_page

class ReadEfficiencyTest(unittest.TestCase):
    setUp=baseline.EvidenceBundleTest.setUp

    def test_small_bundle_preserves_original_before_candidate_volume(self):
        with self.store.db() as db:
            source=db.execute("SELECT source_id FROM records WHERE id='1'").fetchone()['source_id']
            for i in range(2,6):
                text='Synthetic Atlas candidate '+str(i)+'. '+('资料内容 '*10)
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (str(i),self.p['owner'],self.scope,'projects','claim','Atlas',text,'source_reported',source,'1',text,'active',1,None,i))
        large=bundle(self.store,self.p,self.scope,'Atlas',max_chars=6000)
        small=bundle(self.store,self.p,self.scope,'Atlas',max_chars=3000)
        self.assertEqual(large['source_reports']['total'],5)
        self.assertTrue(small['original_evidence']['results'])
        self.assertTrue(small['trusted_context']['records'])
        self.assertLess(len(small['source_reports']['records']),5)
        self.assertLessEqual(len(encoded(small)),3000)
        locator=small['original_evidence']['results'][0]['locator']
        self.assertEqual(set(locator),{'chunk_id','source_id','source_digest','message_id','message_index'})
        self.assertEqual(small['original_evidence']['next_offset'],len(small['original_evidence']['results']) if small['original_evidence']['total']>len(small['original_evidence']['results']) else None)

    def test_usable_prefilter_does_not_hydrate_candidate_sources(self):
        excluded=self.store.ingest(self.p,{'scope':self.scope,'source_key':'synthetic-excluded-source','processing_policy':'archive',
                     'messages':[{'id':'candidate-only','role':'user','text':'Synthetic excluded payload'}]})['id']
        with self.store.db() as db:
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('excluded',self.p['owner'],self.scope,'projects','claim','Atlas','Synthetic Atlas candidate only','source_reported',excluded,'candidate-only','Synthetic excluded payload','active',1,None,10))
            payload=db.execute('SELECT payload FROM sources WHERE id=?',(excluded,)).fetchone()['payload']
        from pipeline.memory_center import core
        original_loads=core.json.loads;observed=[]
        def recording(text,*args,**kwargs):observed.append(text);return original_loads(text,*args,**kwargs)
        with patch('pipeline.memory_center.core.json.loads',side_effect=recording):
            snapshot=self.store.snapshot(self.p,self.scope,'Atlas',governance_filter='usable',include_jobs=False)
        self.assertEqual(snapshot['total'],1)
        self.assertEqual(snapshot['jobs'],[])
        self.assertNotIn(payload,observed)

    def test_shared_source_decoded_once_and_results_unchanged(self):
        with self.store.db() as db:
            source=db.execute("SELECT source_id FROM records WHERE id='1'").fetchone()['source_id']
            payload=db.execute('SELECT payload FROM sources WHERE id=?',(source,)).fetchone()['payload']
            for i in range(2,12):
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (str(i),self.p['owner'],self.scope,'projects','claim','Atlas','Synthetic Atlas '+str(i),'source_reported',source,'1','Synthetic evidence','active',1,None,i))
        from pipeline.memory_center import core
        original=core.json.loads;observed=[]
        def recording(text,*args,**kwargs):observed.append(text);return original(text,*args,**kwargs)
        with patch('pipeline.memory_center.core.json.loads',side_effect=recording):
            result=self.store.snapshot(self.p,self.scope,'Atlas',include_jobs=False)
        self.assertEqual(result['total'],12)
        self.assertEqual(observed.count(payload),1)

    def test_exact_budget_arithmetic_matches_legacy_skip_large_then_small(self):
        rows=self.store.snapshot(self.p,self.scope,'Atlas')['records']
        rows=[dict(rows[0],statement='Synthetic Atlas '+('"\\\n'*1500)),dict(rows[1],statement='Synthetic short Atlas')]*20
        snapshot={'records':rows,'total':len(rows)}
        def legacy(budget):
            result={'records':[],'total':len(rows),'truncated':True}
            for row in rows:
                item={k:row[k] for k in ('id','statement','subject','status','source_id','message_id','source_date','revision','governance')}
                candidate=dict(result,records=result['records']+[item],truncated=len(result['records'])+1<len(rows))
                if len(encoded(candidate))<=budget:result=candidate
            result['truncated']=len(result['records'])<len(rows)
            return result
        for budget in (500,600,1600,3000,6000,16000):
            self.assertEqual(search_page(snapshot,budget),legacy(budget))

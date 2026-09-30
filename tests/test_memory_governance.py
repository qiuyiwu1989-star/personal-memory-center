import json
import unittest
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid, Conflict, encoded
from pipeline.memory_center.governance import review, context
from pipeline.memory_center.reading import page

class GovernanceTest(unittest.TestCase):
    setUp = baseline.MemoryTest.setUp
    tearDown = baseline.MemoryTest.tearDown
    body = baseline.MemoryTest.body
    ingest = baseline.MemoryTest.ingest
    rows = baseline.MemoryTest.rows
    def test_reprocessing_does_not_overwrite_or_promote(self):
        from pipeline.memory_center.reprocessing import preview
        result=self.ingest()
        old=self.rows()[0]
        plan={'claims':[{'topic':old['topic'],'kind':old['kind'],'subject':old['subject'],'statement':old['statement'],'message_id':old['message_id'],'quote':old['quote']}]}
        diff=preview(self.store,self.owner,result['id'],plan,'synthetic-v2')
        self.assertEqual(diff['changes'][0]['comparison'],'duplicate')
        self.assertFalse(diff['semantic_verified'])
        self.assertEqual(self.rows()[0]['governance']['state'],'candidate')
        self.assertEqual(len(self.rows(history=True)),1)
        plan['claims'][0]['quote']='absent evidence'
        with self.assertRaises(Invalid):preview(self.store,self.owner,result['id'],plan,'synthetic-v3')

    def test_archive_no_model_and_provenance(self):
        result=self.store.ingest(self.owner,self.body(processing_policy='archive',source_metadata={'locator':'paragraph:2','parser_version':'text-v1'}))
        self.assertFalse(self.store.process_one(self.model))
        self.assertEqual(self.model.calls,0)
        self.assertEqual(self.store.snapshot(self.owner,'personal')['jobs'][0]['state'],'archived')
        with self.store.db() as db:
            envelope=db.execute('SELECT metadata FROM source_envelopes WHERE source_id=?',(result['id'],)).fetchone()
            self.assertEqual(json.loads(envelope['metadata'])['locator'],'paragraph:2')
        with self.assertRaises(Invalid):self.store.ingest(self.owner,self.body(source_metadata={'owner':'another-user'}))

    def test_legacy_not_current_and_correction_propagates(self):
        self.ingest()
        row=self.rows()[0]
        self.assertEqual(row['governance']['state'],'candidate')
        self.assertIsNone(row['governance']['as_of'])
        self.assertEqual(context(self.store,self.owner,'personal','')['records'],[])
        self.store.correct(self.owner,row['id'],{'revision':1,'statement':'先看数据。'})
        other=dict(self.owner,id='second-agent',trusted_user=False)
        self.assertEqual(context(self.store,other,'personal','')['records'][0]['statement'],'先看数据。')

    def test_review_permissions_dates_history_and_stale_write(self):
        self.ingest();rid=self.rows()[0]['id']
        data={'state':'verified','revision':0,'holder':'owner:q','subject_id':'owner:q','as_of':'2000-01-01','priority':'P2'}
        with self.assertRaises(PermissionError):review(self.store,self.agent,rid,data)
        with self.assertRaises(Invalid):review(self.store,self.owner,rid,dict(data,as_of=None))
        review(self.store,self.owner,rid,data)
        with self.assertRaises(Conflict):review(self.store,self.owner,rid,data)
        self.assertEqual(len(context(self.store,self.owner,'personal','')['records']),1)
        from pipeline.memory_center.governance import usable
        self.assertFalse(usable(self.rows()[0], today='1999-12-31'))
        review(self.store,self.owner,rid,dict(data,revision=1,state='historical'))
        self.assertEqual(context(self.store,self.owner,'personal','')['records'],[])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM governance_events').fetchone()['n'],2)
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],1)

    def test_full_response_budget_and_lossless_pages(self):
        doc={'slug':'demo','title':'合成测试','revision':1,'markdown':'引号"\\\n'*800}
        offset=0;parts=[]
        while True:
            result=page(doc,offset,500)
            self.assertLessEqual(len(encoded(result)),500)
            parts.append(result['markdown'])
            if result['next_offset'] is None:break
            self.assertGreater(result['next_offset'],offset)
            offset=result['next_offset']
        self.assertEqual(''.join(parts),doc['markdown'])

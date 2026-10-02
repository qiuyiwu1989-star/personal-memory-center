"""Source declaration survives archive and workers without granting trust."""
import unittest
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid
from pipeline.memory_center import reprocessing, temporal
from pipeline.memory_center.import_adapter import prepare_imports
from pipeline.memory_center.model import PROMPT_VERSION
from pipeline.memory_center.extraction_input import prepare_request

class Recorder:
    configured=True
    def __init__(self):self.sources=[]
    def extract_source(self,source):
        self.sources.append(dict(source))
        return {'claims':[]},{'total_tokens':1,'method_version':PROMPT_VERSION}

class MetadataTest(unittest.TestCase):
    setUp=baseline.MemoryTest.setUp
    tearDown=baseline.MemoryTest.tearDown
    body=baseline.MemoryTest.body

    def test_archive_and_both_workers_preserve_declared_coverage(self):
        model=Recorder();meta={'visibility':'visible_only','original_ref':'synthetic://partial'}
        result=self.store.ingest(self.owner,self.body(source_metadata=meta))
        self.store.process_one(model)
        self.assertEqual(len(model.sources),1)
        self.assertEqual(model.sources[0]['source_metadata'],meta)
        reprocessing.enqueue(self.store,self.owner,result['id'],'synthetic-reextract')
        reprocessing.process_one(self.store,model)
        self.assertEqual(len(model.sources),2)
        self.assertEqual(model.sources[1]['source_metadata'],meta)
        request,_,_=prepare_request('conversation',[],version=PROMPT_VERSION,source_metadata=meta)
        self.assertEqual(request['source_visibility']['status'],'visible_only')
        self.assertFalse(request['source_visibility']['attachments_verified'])
        self.assertEqual(self.store.snapshot(self.owner,'personal')['records'],[])

    def test_absence_stays_unknown_invalid_or_authority_metadata_rejected(self):
        model=Recorder();self.store.ingest(self.owner,self.body());self.store.process_one(model)
        self.assertEqual(model.sources[0]['source_metadata'],{})
        for meta in ({'visibility':'complete'}, {'visibility':True}, {'trusted_user':'true'}):
            with self.assertRaises(Invalid):self.store.ingest(self.owner,self.body(source_key=str(meta),source_metadata=meta))

    def test_legacy_correction_audited_or_explicit_fields_roll_back(self):
        self.store.ingest(self.owner,self.body());self.store.process_one(self.model)
        row=self.store.snapshot(self.owner,'personal')['records'][0]
        with self.assertRaises(Invalid):self.store.correct(self.owner,row['id'],{'revision':1,'statement':'Synthetic correction','change_kind':'interpretation_correction'})
        self.assertEqual(self.store.snapshot(self.owner,'personal')['records'][0]['lifecycle'],'active')
        temporal.setup(self.store)
        result=self.store.correct(self.owner,row['id'],{'revision':1,'statement':'Synthetic correction','change_kind':'interpretation_correction'})
        self.assertTrue(temporal.status(self.store,self.owner,'personal')['stale'])
        with self.store.db() as db:
            event=dict(db.execute('SELECT * FROM memory_change_events').fetchone())
        self.assertEqual(event['record_id'],result['id'])
        self.assertEqual(event['previous_record_id'],row['id'])
        self.assertIsNone(event['valid_from'])

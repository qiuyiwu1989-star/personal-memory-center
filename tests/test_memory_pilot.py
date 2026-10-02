"""Synthetic boundary checks for the private, zero-provider pilot runner."""
import tempfile
import unittest
from pipeline.memory_center.core import Store, Invalid
from pipeline.memory_center.governance import review, context
from pipeline.memory_center.documents import build_documents
from pipeline.memory_center.reprocessing import preview
from scripts.pilot_memory_governance import run_pilot, OWNER, READER, SCOPE


def synthetic_receipts():
    text='Synthetic preference: read the conclusion first.'
    case={'sample_index':1,'source_type':'conversation','messages':[{'id':'synthetic-1','role':'user','text':text}]}
    claim={'topic':'preferences','kind':'preference','subject':'synthetic owner','statement':text,
           'message_id':'synthetic-1','quote':text}
    return [case],[{'sample_index':1,'version':'2026-10-01.10','validation':'passed','validated_claims':[claim]}]


class PilotTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        cases,runs=synthetic_receipts();self.report=run_pilot(self.store,cases,runs)
        self.row=self.store.snapshot(OWNER,SCOPE)['records'][0]
    def tearDown(self):self.tmp.cleanup()

    def test_replay_preserves_candidate_and_no_worker(self):
        self.assertEqual(self.report['candidate_count'],1)
        self.assertEqual(self.report['duplicate_candidates_detected'],1)
        self.assertGreater(self.report['association_count'],0)
        self.assertEqual(self.report['document_claim_count'],1)
        self.assertEqual(self.report['usable_context_records'],0)
        self.assertEqual(self.report['worker_tasks'],0)
        self.assertEqual(self.report['model_calls'],0)
        self.assertFalse(self.report['quality_approved'])
        self.assertTrue(all(v for k,v in self.report['mcp'].items() if k not in ('candidate_search_count','candidate_search_total')))
        self.assertEqual(self.row['status'],'source_reported')
        self.assertIn('待核实候选',self.report['documents'][0]['markdown'])

    def test_synthetic_correction_updates_agents_retains_old_provenance(self):
        original=self.row
        revised=self.store.correct(OWNER,original['id'],{'revision':original['revision'],
                     'statement':'Synthetic correction: read the evidence first.'})
        current=context(self.store,READER,SCOPE,'')
        self.assertEqual([r['id'] for r in current['records']],[revised['id']])
        history=self.store.snapshot(OWNER,SCOPE,history=True)['records']
        old=next(r for r in history if r['id']==original['id'])
        self.assertEqual(old['lifecycle'],'superseded')
        self.assertEqual(old['quote'],original['quote'])
        self.assertEqual(old['source_id'],original['source_id'])
        doc=build_documents(self.store,OWNER,SCOPE)[0]
        self.assertGreater(doc['revision'],self.report['documents'][0]['revision'])
        self.assertIn('Synthetic correction',doc['markdown'])

    def test_expired_and_future_synthetic_states_do_not_enter_context(self):
        body={'revision':0,'holder':'owner:pilot','subject_id':'owner:pilot','state':'verified',
              'as_of':'2000-01-01','valid_until':'2001-01-01','priority':'P1'}
        # New writes reject invalid current states. Older stored rows must
        # remain harmless without silently mutating their audit history.
        for dates in ({'as_of':'2000-01-01','valid_until':'2001-01-01'},
                      {'as_of':'2099-01-01','valid_until':None}):
            body.update(dates)
            with self.assertRaises(Invalid):review(self.store,OWNER,self.row['id'],body)
            with self.store.db() as db:
                db.execute('INSERT OR REPLACE INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (self.row['id'],'owner:pilot','owner:pilot',body['as_of'],body['valid_until'],
                            'verified','P1',0,'Synthetic legacy fixture',0))
            self.assertEqual(context(self.store,READER,SCOPE,'')['records'],[])

    def test_agent_cannot_verify_and_other_owner_cannot_preview(self):
        with self.assertRaises(PermissionError):
            review(self.store,READER,self.row['id'],{'state':'verified'})
        with self.assertRaises(Invalid):
            preview(self.store,dict(OWNER,owner='other'),self.row['source_id'],{'claims':[]},'synthetic')
        with self.assertRaises(PermissionError):
            context(self.store,dict(READER,scopes=['other']),SCOPE,'')

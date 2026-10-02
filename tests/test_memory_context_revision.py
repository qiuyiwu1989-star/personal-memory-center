"""Synthetic change detection and bounded progressive context contracts."""
import unittest
import test_memory_center as baseline
from pipeline.memory_center.core import Invalid, encoded
from pipeline.memory_center.governance import context, review


class ContextRevisionTest(unittest.TestCase):
    setUp=baseline.MemoryTest.setUp
    tearDown=baseline.MemoryTest.tearDown
    body=baseline.MemoryTest.body
    ingest=baseline.MemoryTest.ingest
    rows=baseline.MemoryTest.rows

    def corrected(self,statement='Synthetic corrected statement.'):
        self.ingest()
        row=self.rows()[0]
        return self.store.correct(self.owner,row['id'],{'revision':row['revision'],'statement':statement})

    def test_repeat_is_stable_correction_and_rejection_change_marker(self):
        revised=self.corrected()
        reader=dict(self.owner,id='synthetic-reader',trusted_user=False,actions=['read'])
        first=context(self.store,reader,'personal','')
        self.assertEqual(first,context(self.store,reader,'personal',''))
        self.assertEqual(first['scope'],'personal')
        self.assertEqual(first['etag'],'"'+first['context_revision']+'"')
        newer=self.store.correct(self.owner,revised['id'],{'revision':2,'statement':'Synthetic new correction.'})
        second=context(self.store,reader,'personal','')
        self.assertNotEqual(first['context_revision'],second['context_revision'])
        self.assertEqual(second['records'][0]['id'],newer['id'])
        review(self.store,self.owner,newer['id'],{'revision':0,'state':'rejected'})
        third=context(self.store,reader,'personal','')
        self.assertEqual(third['records'],[])
        self.assertNotEqual(second['etag'],third['etag'])

    def test_record_provenance_fields_remain_distinct(self):
        self.ingest(messages=[{'id':'synthetic-date','role':'user','text':'Synthetic dated source.',
                              'created_at':'2000-02-02'}])
        row=self.rows()[0]
        review(self.store,self.owner,row['id'],{'revision':0,'state':'verified','holder':'owner:q',
              'subject_id':'owner:q','as_of':'2000-01-01'})
        result=context(self.store,self.owner,'personal','')
        item=result['records'][0]
        self.assertEqual(item['source_date'],'2000-02-02')
        self.assertEqual(item['governance']['as_of'],'2000-01-01')
        self.assertEqual(item['status'],'user_stated')
        self.assertEqual(item['subject'],row['subject'])

    def test_all_budgets_include_whole_envelope_and_do_not_call_model(self):
        self.corrected(statement='Synthetic "\\ statement. '*60)
        before=self.model.calls
        for budget in (500,600,1600,4000,16000):
            result=context(self.store,self.owner,'personal','',budget)
            self.assertLessEqual(len(encoded(result)),budget)
            self.assertEqual(result['total'],1)
            self.assertEqual(result['truncated'],not bool(result['records']))
        self.assertEqual(self.model.calls,before)
        for budget in (499,16001,True):
            with self.assertRaises(Invalid):context(self.store,self.owner,'personal','',budget)

    def test_revocation_checks_permissions_before_returning_content(self):
        self.corrected()
        reader=dict(self.owner,actions=['read'],trusted_user=False)
        first=context(self.store,reader,'personal','')
        reader['actions']=[]
        with self.assertRaises(PermissionError):context(self.store,reader,'personal','')
        reader['actions']=['read'];reader['scopes']=['project:demo']
        with self.assertRaises(PermissionError):context(self.store,reader,'personal','')
        other=dict(self.owner,owner='synthetic-other')
        result=context(self.store,other,'personal','')
        self.assertEqual(result['records'],[])
        self.assertNotEqual(first['etag'],result['etag'])

    def test_governance_changes_marker_even_if_item_exceeds_budget(self):
        self.corrected(statement='Synthetic long statement. '*65)
        rid=self.rows()[0]['id']
        before=context(self.store,self.owner,'personal','',500)
        self.assertEqual(before['records'],[])
        review(self.store,self.owner,rid,{'revision':0,'state':'verified','holder':'owner:q',
              'subject_id':'owner:q','as_of':'2000-01-01','priority':'P0'})
        after=context(self.store,self.owner,'personal','',500)
        self.assertEqual(after['records'],[])
        self.assertNotEqual(before['context_revision'],after['context_revision'])

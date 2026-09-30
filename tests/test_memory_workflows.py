"""Synthetic acceptance cases: costs, re-extraction, translation and isolation."""
import tempfile
import unittest
from pipeline.memory_center.core import Store, Invalid, Conflict
from pipeline.memory_center.budget import configure, status
from pipeline.memory_center.reprocessing import enqueue, process_one, listing, get_preview, control
from pipeline.memory_center.entities import register
from pipeline.memory_center.governance import review, context
from pipeline.memory_center.documents import define_topic, build_documents

class Extractor:
    configured=True
    calls=0
    def extract(self,messages):
        self.calls+=1;m=messages[0]
        return {'claims':[{'topic':'projects','kind':'decision','subject':'user','statement':'合成新候选：'+m['text'], 'message_id':m['id'],'quote':m['text']}]},{'total_tokens':42}
    def translate(self,statement):
        self.calls+=1
        return '合成译文：先给结论。',{'total_tokens':12}

class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.owner={'id':'owner','owner':'synthetic','trusted_user':True,'actions':['read','write'],'scopes':['personal','project:other']}
        self.agent=dict(self.owner,id='agent',trusted_user=False)
        self.model=Extractor()
        self.source=self.store.ingest(self.owner,{'source_key':'synthetic:notes','processing_policy':'archive','messages':[{'id':'m1','role':'user','text':'Keep the conclusion first.'}]})['id']
    def tearDown(self):self.tmp.cleanup()
    def budget(self,cap=100000):return configure(self.store,self.owner,'personal',{'token_limit':cap})
    def test_no_budget_no_call_and_authorized_resume(self):
        rid=enqueue(self.store,self.agent,self.source,'synthetic-run')['id']
        process_one(self.store,self.model)
        self.assertEqual(self.model.calls,0)
        self.assertEqual(listing(self.store,self.owner,'personal')['runs'][0]['state'],'paused_budget')
        self.budget();process_one(self.store,self.model)
        run=listing(self.store,self.owner,'personal')['runs'][0]
        self.assertEqual(run['state'],'ready');self.assertEqual(status(self.store,self.owner,'personal')['tokens_spent'],42)
        self.assertEqual(self.store.snapshot(self.owner,'personal')['records'],[])
        with self.assertRaises(PermissionError):control(self.store,self.agent,rid,'apply',[0])
        control(self.store,self.owner,rid,'apply',[0])
        self.assertEqual(self.store.snapshot(self.owner,'personal')['records'][0]['governance']['state'],'candidate')
        self.assertEqual(context(self.store,self.agent,'personal','')['records'],[])
        with self.assertRaises(Conflict):control(self.store,self.owner,rid,'apply',[0])
    def test_unknown_failure_preserves_reserve_retry_cost(self):
        self.budget();rid=enqueue(self.store,self.owner,self.source,'synthetic-failure')['id']
        class Broken:
            def extract(self,messages):raise RuntimeError('private content must not reach error')
        process_one(self.store,Broken());before=status(self.store,self.owner,'personal')
        self.assertGreater(before['tokens_spent'],0);self.assertEqual(before['unresolved_attempts'],1)
        run=listing(self.store,self.owner,'personal')['runs'][0];self.assertEqual(run['error'],'RuntimeError')
        control(self.store,self.owner,rid,'retry');process_one(self.store,self.model)
        self.assertEqual(status(self.store,self.owner,'personal')['tokens_spent'],before['tokens_spent']+42)
    def test_acknowledgement_cannot_support_expanded_claim(self):
        from pipeline.memory_center.core import validate_plan,encoded
        source={'source_type':'conversation','trusted_user':False,'payload':encoded([{'id':'1','role':'user','text':'继续'}])}
        plan={'claims':[{'topic':'projects','kind':'decision','subject':'user','statement':'合成：已决定第九章的年龄与家长角色。','message_id':'1','quote':'继续'}]}
        with self.assertRaises(Invalid):validate_plan(plan,source)

    def test_quality_gate_and_scope_permissions(self):
        with self.assertRaises(Invalid):configure(self.store,self.owner,'personal',{'token_limit':200000})
        with self.assertRaises(PermissionError):configure(self.store,self.agent,'personal',{'token_limit':100000})
        configure(self.store,self.owner,'personal',{'token_limit':200000,'quality_approved':True,'note':'Synthetic test only: explicit owner quality approval'})
        other=dict(self.agent,scopes=['project:other'])
        with self.assertRaises(PermissionError):enqueue(self.store,other,self.source,'synthetic-other')
        with self.assertRaises(PermissionError):listing(self.store,other,'personal')
    def test_translation_changes_display_not_evidence_or_governance(self):
        self.budget();run=enqueue(self.store,self.owner,self.source,'synthetic-extract')['id'];process_one(self.store,self.model);control(self.store,self.owner,run,'apply',[0])
        record=self.store.snapshot(self.owner,'personal')['records'][0]
        translation=enqueue(self.store,self.owner,self.source,'synthetic-translate','translate',record['id'])['id']
        process_one(self.store,self.model);control(self.store,self.owner,translation,'apply',[0])
        updated=self.store.snapshot(self.owner,'personal')['records'][0]
        self.assertEqual(updated['statement'],record['statement']);self.assertEqual(updated['quote'],record['quote'])
        self.assertEqual(updated['display_statement'],'合成译文：先给结论。');self.assertTrue(updated['translated'])
        self.assertEqual(updated['governance']['state'],'candidate')
        self.assertEqual(status(self.store,self.owner,'personal')['tokens_spent'],54)
    def test_entities_do_not_merge_same_names_or_cross_scope(self):
        register(self.store,self.owner,'personal',{'id':'person:a','kind':'person','name':'合成人物','aliases':['同名']})
        register(self.store,self.owner,'personal',{'id':'person:b','kind':'person','name':'合成人物','aliases':['同名']})
        with self.assertRaises(Invalid):register(self.store,self.owner,'personal',{'id':'person:a','kind':'person','name':'另一个人'})
        self.budget();run=enqueue(self.store,self.owner,self.source,'synthetic-extract')['id'];process_one(self.store,self.model);control(self.store,self.owner,run,'apply',[0]);record=self.store.snapshot(self.owner,'personal')['records'][0]
        data={'state':'verified','priority':'P1','holder':'person:missing','subject_id':'person:a','as_of':'2000-01-01','revision':0}
        with self.assertRaises(Invalid):review(self.store,self.owner,record['id'],data)
        review(self.store,self.owner,record['id'],dict(data,holder='person:b'))
        self.assertEqual(len(context(self.store,self.agent,'personal','')['records']),1)
    def test_source_pages_are_bounded_and_lossless(self):
        from pipeline.memory_center.reading import source_page
        from pipeline.memory_center.core import encoded
        message={'id':'synthetic','role':'external','text':'合成 \" \\\ \n'*500}
        offset=0;parts=[]
        while True:
            result=source_page('synthetic:source',message,offset,500)
            self.assertLessEqual(len(encoded(result)),500);parts.append(result['message']['text'])
            if result['next_offset'] is None:break
            self.assertGreater(result['next_offset'],offset);offset=result['next_offset']
        self.assertEqual(''.join(parts),message['text'])

    def test_small_documents_keep_candidate_state_and_source_evidence(self):
        define_topic(self.store,self.owner,'personal','synthetic','合成主题',['synthetic:'])
        with self.store.db() as db:
            import time
            for i in range(60):
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (str(i),'synthetic','personal','projects','decision','user','合成陈述 '+str(i),'source_reported',self.source,'m1','Keep the conclusion first.','active',1,None,time.time()+i))
        docs=build_documents(self.store,self.owner,'personal')
        self.assertEqual(sum(d['is_index'] for d in docs),1)
        leaves=[d for d in docs if not d['is_index']]
        self.assertEqual(len(leaves),3);self.assertTrue(all(d['claims']<=25 for d in leaves))
        self.assertEqual(sum(d['claims'] for d in leaves),60)
        self.assertTrue(all('待核实候选' in d['markdown'] for d in leaves))
        self.assertTrue(all('Keep the conclusion first.' in d['markdown'] for d in leaves))

"""Synthetic source labels are metadata, never corroboration or project identity."""
import unittest
from pipeline.memory_center.extraction_input import prepare_request,resolve_plan

class ScopeAttachmentTest(unittest.TestCase):
    def plan(self,source_type='conversation',title='合成 A /  B'):
        _,spans,_=prepare_request(source_type,[{'id':'synthetic','role':'user','text':'我希望保留出处。','source_title':title}])
        return spans,{'claims':[{'topic':'projects','kind':'plan','subject':'user','statement':'用户希望保留出处。','evidence_id':next(iter(spans))}]}
    def test_exact_metadata_label_without_evidence_changes(self):
        spans,p=self.plan();claim=resolve_plan(p,spans,version='2026-10-01.12')['claims'][0]
        self.assertEqual(claim['statement'],'来源对话：合成 A /  B。用户希望保留出处。')
        self.assertEqual(claim['quote'],'我希望保留出处。')
        self.assertFalse(any(k.startswith('_') for k in claim))
        self.assertEqual(p['claims'][0]['statement'],'用户希望保留出处。')
    def test_legacy_summary_and_missing_title_are_not_reanchored(self):
        for kind,title,version in [('conversation','合成范围','2026-10-01.11'),('imported_summary','合成范围','2026-10-01.12'),('conversation',None,'2026-10-01.12')]:
            spans,p=self.plan(kind,title);self.assertEqual(resolve_plan(p,spans,version=version)['claims'][0]['statement'],'用户希望保留出处。')
    def test_message_date_is_a_metadata_label_not_event_validity(self):
        msg={'id':'synthetic','role':'user','text':'我希望保留出处。','source_title':'合成范围','created_at':'2025-01-01T12:00:00Z'}
        _,spans,_=prepare_request('conversation',[msg]);p={'claims':[{'topic':'projects','kind':'plan','subject':'user','statement':'用户希望保留出处。','evidence_id':next(iter(spans))}]}
        c=resolve_plan(p,spans,version='2026-10-01.13')['claims'][0]
        self.assertTrue(c['statement'].startswith('来源消息日期：2025-01-01（非事件成立时间，当前有效性待核实）。来源对话：合成范围。'))
        self.assertEqual(c['quote'],msg['text'])
        _,summary_spans,_=prepare_request('imported_summary',[msg])
        self.assertNotIn('2025-01-01',resolve_plan(p,summary_spans,version='2026-10-01.13')['claims'][0]['statement'])
    def test_source_label_is_not_an_executable_or_semantic_instruction(self):
        from pipeline.memory_center.core import validate_plan,encoded,Invalid
        message={'id':'synthetic','role':'user','text':'我希望保留出处。','source_title':'开始第六讲','created_at':'2025-01-01'}
        _,spans,_=prepare_request('conversation',[message]);sid=next(iter(spans));source={'payload':encoded([message]),'source_type':'conversation','trusted_user':False,'processing_method_version':'2026-10-01.13'}
        p={'claims':[{'topic':'projects','kind':'plan','subject':'user','statement':'用户希望保留出处。','evidence_id':sid}]}
        self.assertEqual(len(validate_plan(resolve_plan(p,spans,version='2026-10-01.13'),source)),1)
        p['claims'][0]['statement']='用户要求开始第六讲。'
        with self.assertRaises(Invalid):validate_plan(resolve_plan(p,spans,version='2026-10-01.13'),source)

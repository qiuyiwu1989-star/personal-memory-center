import unittest
from pipeline.memory_center.extraction_input import prepare_request,resolve_plan
from pipeline.memory_center.core import Invalid

class EvidenceSpanTest(unittest.TestCase):
    def test_mixed_immediate_and_constraint_have_exact_offsets(self):
        message={'id':'m','role':'user','text':'开始第六讲，不要虚构故事，可以引用真实案例。'}
        request,spans,routes=prepare_request('conversation',[message])
        self.assertNotIn('开始第六讲',''.join(s['quote'] for s in spans.values()))
        for span in spans.values():self.assertEqual(span['quote'],message['text'][span['start']:span['end']])
        sid=next(iter(spans));claim={'evidence_id':sid,'statement':'合成项目约束'}
        self.assertEqual(resolve_plan({'claims':[claim]},spans)['claims'][0]['message_id'],'m')
        with self.assertRaises(Invalid):resolve_plan({'claims':[dict(claim,quote='伪造引用')]},spans)
        with self.assertRaises(Invalid):resolve_plan({'claims':[dict(claim,evidence_id='missing')]},spans)

    def test_pasted_roles_route_to_reference_without_losing_original(self):
        text='# 角色设定\n## 核心使命\n'+('合成文档。'*200)+'\n### 约束\n'
        message={'id':'m','role':'user','text':text}
        request,spans,routes=prepare_request('conversation',[message])
        self.assertFalse(spans);self.assertEqual(routes['m'],'reference_document');self.assertEqual(message['text'],text)

    def test_unicode_whitespace_and_long_spans_are_lossless(self):
        text='a\u00a0b😊'+('x'*800)
        _,spans,_=prepare_request('conversation',[{'id':'m','role':'user','text':text}])
        self.assertEqual(''.join(s['quote'] for s in spans.values()),text)
        self.assertTrue(all(len(s['quote'])<=1000 for s in spans.values()))

    def test_full_list_and_constraint_sentence_are_not_cut_at_commas(self):
        text='系统包含三类合成人物：\n甲角色\n乙角色\n丙角色。'
        _,spans,_=prepare_request('conversation',[{'id':'m','role':'user','text':text}])
        self.assertEqual(next(iter(spans.values()))['quote'],text)
        text='开始第六讲，不要虚构故事，可以引用真实案例。'
        _,spans,_=prepare_request('conversation',[{'id':'m','role':'user','text':text}])
        self.assertEqual(next(iter(spans.values()))['quote'],'不要虚构故事，可以引用真实案例。')

    def test_empty_routes_skip_model_without_configuration(self):
        from pipeline.memory_center.model import Model
        from pipeline.memory_center.core import encoded
        class NoCall(Model):
            def _call(self,*args,**kwargs):raise AssertionError('model must not run')
        plan,usage=NoCall().extract_source({'source_type':'conversation','payload':encoded([{'id':'1','role':'user','text':'继续'}])})
        self.assertEqual(plan,{'claims':[]});self.assertTrue(usage['model_skipped']);self.assertEqual(usage['total_tokens'],0)

    def test_assistant_draft_kept_as_reference_not_personal_evidence(self):
        text='助手合成建议：建议每周进行两次复盘。'
        source={'id':'a','role':'assistant','text':text}
        request,spans,routes=prepare_request('conversation',[source])
        self.assertEqual(routes['a'],'assistant_reference');self.assertFalse(spans)
        self.assertEqual(source['text'],text)
        # A secondhand summary must retain its own summary attribution path.
        _,spans,_=prepare_request('imported_summary',[source]);self.assertTrue(spans)

    def test_outer_user_constraint_is_separate_from_pasted_chapter(self):
        prefix='合成项目约束：不要虚构案例。\n'
        draft='第八章：合成稿件\n'+('建议读者每周复盘两次。'*50)
        message={'id':'mixed','role':'user','text':prefix+draft}
        request,spans,routes=prepare_request('conversation',[message])
        self.assertEqual(routes['mixed'],'mixed_reference_document')
        self.assertIn('不要虚构案例',''.join(s['quote'] for s in spans.values()))
        self.assertNotIn('建议读者',''.join(s['quote'] for s in spans.values()))
        for span in spans.values():self.assertEqual(span['quote'],message['text'][span['start']:span['end']])

    def test_explicit_configuration_survives_mixed_temporary_request(self):
        text='合成系统有七大智能体：\n甲智能体\n乙智能体\n丙智能体\n丁智能体\n戊智能体\n己智能体\n庚智能体。请生成一张草图。'
        request,spans,routes=prepare_request('conversation',[{'id':'config','role':'user','text':text}])
        self.assertEqual(routes['config'],'conversation');self.assertEqual(next(iter(spans.values()))['quote'],text)
        self.assertEqual(request['messages'][0]['evidence_spans'][0]['priority_hint'],'explicit_configuration')

    def test_unformatted_role_specification_is_reference(self):
        text='你是一个合成写作助手。\n核心使命：产出文本。\n'+('职责：遵守写作流程。'*50)
        _,spans,routes=prepare_request('conversation',[{'id':'template','role':'user','text':text}])
        self.assertFalse(spans);self.assertEqual(routes['template'],'reference_document')

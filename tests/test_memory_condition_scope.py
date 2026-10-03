"""Synthetic scope contrasts, no provider, personal source or frozen rubric."""
import unittest
from pipeline.memory_center.core import Invalid
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
from pipeline.memory_center.modality import scoped_evidence_ranges, modality_problem

VERSION='2026-10-03.17'

class ConditionScopeTest(unittest.TestCase):
    def prepared(self,text,version=VERSION):
        return prepare_request('conversation',[{'id':'synthetic','role':'user','text':text,
            'source_title':'Synthetic scope','created_at':'2026-01-02'}],version=version,
            source_metadata={'visibility':'visible_only'})

    def test_explicit_independent_project_has_exact_lossless_spans(self):
        text='如果测试通过，我计划发布 Atlas。另外，我对另一个独立项目 Orion 的要求是：保留每条原始证据。'
        request,spans,_=self.prepared(text)
        self.assertEqual(len(spans),2)
        self.assertEqual(''.join(s['quote'] for s in spans.values()),text)
        for span in spans.values():
            self.assertEqual(text[span['start']:span['end']],span['quote'])
        self.assertEqual([p['modality_hint'] for p in request['messages'][0]['evidence_spans']],['conditional','stated'])
        self.assertEqual(request['source_visibility']['status'],'visible_only')
        sid=list(spans)[1]
        resolved=resolve_plan({'claims':[{'topic':'projects','kind':'claim','subject':'user',
            'statement':'用户对独立项目 Orion 要求保留每条原始证据。','evidence_id':sid}]},spans,version=VERSION)
        self.assertEqual(resolved['claims'][0]['quote'],text[text.index('另外'):])
        self.assertEqual(resolved['claims'][0]['modality'],'stated')
        self.assertIn('非事件成立时间',resolved['claims'][0]['statement'])

    def test_ordinary_adjacency_and_same_object_keep_condition(self):
        for suffix in ('总之，我需要 Atlas 保留证据。','另外，我对项目 Atlas 的要求是保留证据。',
                       '我对项目 Orion 的要求是保留证据。','我希望它保留证据。',
                       '我对另一个独立项目 Orion 的要求是：如果离线可用则保留证据。'):
            text='如果测试通过，我计划发布 Atlas。'+suffix
            with self.subTest(suffix=suffix):
                self.assertEqual(scoped_evidence_ranges(text),[(0,len(text))])

    def test_quoted_and_third_party_independence_are_not_owner_evidence(self):
        for text in (
            '如果测试通过，团队说：“另外，我对另一个独立项目 Orion 的要求是：保留证据。”',
            '如果测试通过，我计划发布 Atlas。张三说我对另一个独立项目 Orion 的要求是：保留证据。',
            '张三说：如果测试通过，我计划发布 Atlas。我对另一个独立项目 Orion 的要求是：保留证据。',
            '以下是同事来信：如果测试通过，我计划发布 Atlas。我对另一个独立项目 Orion 的要求是：保留证据。',
            '如果测试通过，我计划发布 Atlas。“另外，我对另一个独立项目 Orion 的要求是：保留证据。”',
        ):
            with self.subTest(text=text):
                self.assertEqual(scoped_evidence_ranges(text),[(0,len(text))])

    def test_list_dependencies_remain_whole(self):
        text='如果测试通过，要求如下：\n1. 发布 Atlas。另一个独立项目 Orion 要保留证据。\n2. 继续评测。'
        self.assertEqual(scoped_evidence_ranges(text),[(0,len(text))])

    def test_conditional_fragment_cannot_be_promoted_after_split(self):
        text='如果测试通过，我计划发布 Atlas。我对另一独立项目 Orion 的要求是：保留证据。'
        _,spans,_=self.prepared(text)
        with self.assertRaises(Invalid):
            resolve_plan({'claims':[{'topic':'projects','kind':'decision','subject':'user',
                'statement':'用户已决定发布 Atlas。','evidence_id':next(iter(spans))}]},spans,version=VERSION)
        self.assertEqual(next(iter(spans.values()))['quote'],'如果测试通过，我计划发布 Atlas。')

    def test_legacy_span_shape_and_condition_rejection_unchanged(self):
        text='如果测试通过，我计划发布 Atlas。我对另一独立项目 Orion 的要求是：保留证据。'
        for version in ('2026-10-01.14','2026-10-02.15','2026-10-02.16'):
            with self.subTest(version=version):
                request,spans,_=self.prepared(text,version)
                self.assertEqual(len(spans),1)
                self.assertEqual(next(iter(spans.values()))['quote'],text)
                self.assertEqual('source_visibility' in request,version=='2026-10-02.16')

    def test_requirement_does_not_support_completed_or_adopted_decision(self):
        # This guard is not an entailment validator: unchanged lexical abstention
        # on a plain requirement remains a semantic-review boundary, not approval.
        self.assertIsNone(modality_problem('我需要项目 Atlas 保留证据。','用户计划项目 Atlas 保留证据。','plan'))
        self.assertIsNotNone(modality_problem('我希望项目 Atlas 保留证据。','用户已决定项目 Atlas 保留证据。','decision'))
        self.assertIsNone(modality_problem('我已决定项目 Atlas 保留证据。','用户已决定项目 Atlas 保留证据。','decision'))

if __name__=='__main__':unittest.main()

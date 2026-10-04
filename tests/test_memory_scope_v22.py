"""Synthetic contrasts; lexical coverage is not real extraction quality."""
import unittest
from pipeline.memory_center.core import Invalid
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
from pipeline.memory_center.modality import scoped_evidence_ranges_v22

V='2026-10-04.22'
class ScopeV22Tests(unittest.TestCase):
    def spans(self,text,role='user'):
        return prepare_request('conversation',[{'id':'synthetic','role':role,'text':text}],version=V)[1]
    def claim(self, spans, sid, statement):
        return resolve_plan({'claims':[{'topic':'projects','kind':'plan','subject':'user','statement':statement,'evidence_id':sid}]},spans,version=V)['claims'][0]
    def test_frozen_different_project_wish_delivered_both_orders(self):
        wish='我希望项目 Atlas 保留每条原始证据。'
        condition='如果独立评测通过，我计划发布项目 Orion。'
        for text in (wish+condition,condition+wish):
            with self.subTest(text=text):
                spans=self.spans(text); self.assertEqual(len(spans),2)
                self.assertEqual(''.join(s['quote']for s in spans.values()),text)
                ws=next(k for k,v in spans.items() if v['quote']==wish)
                cs=next(k for k,v in spans.items() if v['quote']==condition)
                self.assertEqual(self.claim(spans,ws,'用户希望项目 Atlas 保留每条原始证据。')['modality'],'wish')
                with self.assertRaises(Invalid):self.claim(spans,cs,'用户计划发布项目 Orion。')
                self.assertEqual(self.claim(spans,cs,'如果独立评测通过，用户计划发布项目 Orion。')['modality'],'conditional')
    def test_same_project_pronoun_shared_condition_not_released(self):
        for text in (
            '我希望项目 Atlas 保留证据。如果独立评测通过，我计划发布项目 Atlas。',
            '如果独立评测通过，我计划发布项目 Atlas。我希望项目 Atlas 保留证据。',
            '我希望项目 Atlas 保留证据。如果独立评测通过，它会自动发布。',
            '如果独立评测通过，我计划发布项目 Atlas。我希望它保留证据。',
            '我希望项目 Atlas 保留证据。前提是独立评测通过。',
            '如果独立评测通过，两项共同执行：我计划发布项目 Orion。我希望项目 Atlas 保留证据。',
            '我希望项目 Atlas 保留证据。如果项目 Atlas 评测通过，我计划发布项目 Orion。',
            '我希望项目 Atlas 保留证据。如果通过，我计划发布项目 Orion 并接入 Atlas。',
            '我希望项目 Atlas 保留证据。只有独立评测通过，我计划发布项目 Orion。',
            '如果通过，要求如下：\n1. 我希望项目 Atlas 保留证据。\n2. 我计划发布项目 Orion。',
            '同事说：“我希望项目 Atlas 保留证据。如果通过，我计划发布项目 Orion。”',
        ):
            with self.subTest(text=text):self.assertEqual(scoped_evidence_ranges_v22(text),[(0,len(text))])
    def test_roles_not_owner_inferred(self):
        text='我希望项目 Atlas 保留证据。如果通过，我计划发布项目 Orion。'
        self.assertEqual(self.spans(text,'assistant'),{})
        req,_,_=prepare_request('conversation',[{'id':'external','role':'external','text':text}],version=V)
        self.assertEqual(req['messages'][0]['role'],'external')
    def test_cross_message_condition_and_role_are_reviewed_not_released(self):
        from pipeline.memory_center.scope_review import prepare_scope_review
        for first_role in ('user','external','assistant'):
            messages=[{'id':'prior','role':first_role,'text':'如果独立评测通过，才执行这些要求。'},
                      {'id':'next','role':'user','text':'我希望项目 Atlas 保留证据。'}]
            packet=prepare_scope_review('conversation',messages,version=V)
            target=next(t for t in packet['review_targets']if t['message_id']=='next')
            self.assertIn('neighbor_condition_requires_semantic_review',target['reason_codes'])
            self.assertEqual(packet['messages'][0]['role'],first_role)
            self.assertFalse(packet['automatic_scope_release'])

    def test_v21_qualifier_guard_retained(self):
        spans=self.spans('从现在起，以下全部规则长期适用，直到我明确更改：必须保留原文；禁止公开原件。')
        with self.assertRaises(Invalid):
            resolve_plan({'claims':[{'topic':'preferences','kind':'claim','subject':'user','statement':'用户要求必须保留原文。','evidence_id':next(iter(spans))}]},spans,version=V)

"""Synthetic v19 adapter/guard contracts, not provider semantic-quality evidence."""
import unittest

import test_memory_generation_v14 as fixture
from pipeline.memory_center.core import Invalid, encoded, validate_plan
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
from pipeline.memory_center.model import PROMPT_VERSION


class AtomicV19Test(unittest.TestCase):
    environment = fixture.GenerationV14Test.environment
    invoke = fixture.GenerationV14Test.invoke

    def test_two_independent_constraints_can_share_one_exact_span(self):
        text = '合成项目 Atlas 的长期要求：保留人工审核历史；禁止自动覆盖已有结论。'
        messages = [{'id': 'atomic', 'role': 'user', 'text': text,
                     'source_title': 'Synthetic constraint review', 'created_at': '2026-01-02'}]

        def respond(payload):
            spans = payload['messages'][0]['evidence_spans']
            self.assertEqual(len(spans), 1)
            sid = spans[0]['evidence_id']
            return {'claims': [
                {'topic': 'projects', 'kind': 'claim', 'subject': 'Atlas',
                 'statement': '用户要求合成项目 Atlas 长期保留人工审核历史。', 'evidence_id': sid},
                {'topic': 'projects', 'kind': 'claim', 'subject': 'Atlas',
                 'statement': '用户要求合成项目 Atlas 禁止自动覆盖已有结论。', 'evidence_id': sid},
            ]}

        (plan, usage), calls = self.invoke(messages, respond)
        validated = validate_plan(plan, {'source_type': 'conversation', 'trusted_user': False,
            'payload': encoded(messages), 'processing_method_version': PROMPT_VERSION})
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(validated), 2)
        self.assertEqual({item['quote'] for item in validated}, {text})
        self.assertEqual({item['message_id'] for item in validated}, {'atomic'})
        self.assertTrue(all(item['status'] == 'source_reported' for item in validated))
        self.assertFalse(usage['quality_assessment']['quality_approved'])
        self.assertEqual(usage['condition_scope_guard_version'], 'condition-scope-v2-explicit')

    def test_v19_does_not_relax_wish_or_conditional_commitment_guards(self):
        for text, statement in (
            ('我希望合成项目未来保留历史。', '用户已决定合成项目保留历史。'),
            ('如果审核通过，我计划开放合成展厅。', '用户已决定开放合成展厅。'),
        ):
            with self.subTest(text=text):
                messages = [{'id': 'wish', 'role': 'user', 'text': text}]
                _, spans, _ = prepare_request('conversation', messages, version=PROMPT_VERSION)
                claim = {'topic': 'projects', 'kind': 'decision', 'subject': 'user',
                         'statement': statement, 'evidence_id': next(iter(spans))}
                with self.assertRaises(Invalid):
                    resolve_plan({'claims': [claim]}, spans, version=PROMPT_VERSION)
                raw = {k: v for k, v in claim.items() if k != 'evidence_id'}
                raw.update(message_id='wish', quote=text)
                with self.assertRaises(Invalid):
                    validate_plan({'claims': [raw]}, {'source_type': 'conversation',
                        'trusted_user': False, 'payload': encoded(messages),
                        'processing_method_version': PROMPT_VERSION})

    def test_unnamed_new_span_can_remain_unnamed_despite_title_and_neighbor(self):
        messages = [
            {'id': 'named', 'role': 'user', 'text': '如果测试通过，我计划发布 Atlas。'},
            {'id': 'unnamed', 'role': 'user',
             'text': '我对另一个独立项目的要求是：长期保留每条原始证据。',
             'source_title': 'Synthetic Atlas conversation'},
        ]

        def respond(payload):
            spans = payload['messages'][1]['evidence_spans']
            self.assertEqual(len(spans), 1)
            selected = spans[0]
            self.assertNotIn('Atlas', selected['text'])
            return {'claims': [{'topic': 'projects', 'kind': 'claim',
                'subject': 'unknown-project',
                'statement': '用户要求另一个独立项目长期保留每条原始证据，项目名称未知。',
                'evidence_id': selected['evidence_id']}]}

        (plan, usage), _ = self.invoke(messages, respond)
        claim = plan['claims'][0]
        self.assertNotIn('Atlas', claim['quote'])
        # A title remains an archive label; it does not supply the semantic name.
        semantic = claim['statement'].split('。', 1)[1]
        self.assertNotIn('Atlas', semantic)
        self.assertEqual(claim['subject'], 'unknown-project')
        self.assertIn('项目名称未知', semantic)
        self.assertFalse(usage['quality_assessment']['quality_approved'])


if __name__ == '__main__':
    unittest.main()

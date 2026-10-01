"""Adapter integration with synthetic responses; not a model quality benchmark."""
import io
import json
import unittest
from unittest.mock import patch

from pipeline.memory_center.model import Model, ModelOutputError, PROMPT, PROMPT_VERSION


class GenerationV14Test(unittest.TestCase):
    environment = {
        'QIU_MEMORY_LLM_BASE': 'https://synthetic.invalid/v1',
        'QIU_MEMORY_LLM_KEY': 'synthetic-test-key',
        'QIU_MEMORY_LLM_MODEL': 'synthetic-model',
    }

    def invoke(self, messages, respond):
        captured = []

        class FakeOpener:
            def open(self, request, timeout):
                body = json.loads(request.data)
                captured.append(body)
                plan = respond(json.loads(body['messages'][1]['content']))
                return io.BytesIO(json.dumps({
                    'choices': [{'finish_reason': 'stop', 'message': {
                        'content': json.dumps(plan, ensure_ascii=False)}}],
                    'usage': {'prompt_tokens': 40, 'completion_tokens': 10, 'total_tokens': 50},
                }).encode())

        with patch.dict('os.environ', self.environment, clear=True), \
                patch('pipeline.memory_center.model.build_opener', return_value=FakeOpener()):
            result = Model().extract_source({
                'source_type': 'conversation',
                'payload': json.dumps(messages, ensure_ascii=False),
            })
        return result, captured

    def test_new_prompt_reaches_provider_with_exact_scope_and_user_evidence(self):
        title = 'Synthetic Alpha / 范围： A  B'
        text = '我希望未来为合成项目增加离线导出；持续约束是所有导出都应保留出处。'
        messages = [
            {'id': 'u1', 'role': 'user', 'text': text,
             'source_title': title, 'created_at': '2026-01-02'},
            {'id': 'a1', 'role': 'assistant', 'text': '已决定实施，已经完成。',
             'source_title': title, 'created_at': '2026-01-02'},
        ]

        def respond(payload):
            user, assistant = payload['messages']
            self.assertEqual(user['source_title'], title)
            self.assertEqual(user['created_at'], '2026-01-02')
            self.assertEqual(assistant['evidence_spans'], [])
            self.assertEqual(assistant['route'], 'assistant_reference')
            span = user['evidence_spans'][0]
            self.assertEqual(span['text'], text)
            return {'claims': [{
                'topic': 'projects', 'kind': 'plan', 'subject': 'user',
                'statement': f'2026-01-02，在“{title}”对话中，用户希望未来增加离线导出。',
                'evidence_id': span['evidence_id'],
            }]}

        (plan, usage), requests = self.invoke(messages, respond)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['messages'][0], {'role': 'system', 'content': PROMPT})
        self.assertEqual(PROMPT_VERSION, '2026-10-01.14')
        self.assertEqual(usage['method_version'], PROMPT_VERSION)
        self.assertEqual(usage['total_tokens'], 50)
        self.assertEqual(plan['claims'][0]['quote'], text)
        self.assertEqual(plan['claims'][0]['message_id'], 'u1')
        self.assertEqual(plan['claims'][0]['kind'], 'plan')

    def test_provider_cannot_introduce_unprovided_evidence_and_usage_survives(self):
        messages = [{'id': 'u2', 'role': 'user', 'text': '合成项目的公开说明必须注明出处。'}]
        with self.assertRaises(ModelOutputError) as raised:
            self.invoke(messages, lambda payload: {'claims': [{
                'evidence_id': 'invented-assistant-evidence', 'statement': '已完成。'}]})
        self.assertEqual(raised.exception.usage['method_version'], '2026-10-01.14')
        self.assertEqual(raised.exception.usage['total_tokens'], 50)

    def test_no_extractable_source_avoids_network_and_reports_new_method(self):
        with patch.dict('os.environ', {}, clear=True), \
                patch('pipeline.memory_center.model.build_opener') as opener:
            plan, usage = Model().extract_source({
                'source_type': 'conversation',
                'payload': json.dumps([{'id': 'u3', 'role': 'user', 'text': '继续'}]),
            })
        opener.assert_not_called()
        self.assertEqual(plan, {'claims': []})
        self.assertTrue(usage['model_skipped'])
        self.assertEqual(usage['method_version'], '2026-10-01.14')
        self.assertEqual(usage['total_tokens'], 0)


if __name__ == '__main__':
    unittest.main()

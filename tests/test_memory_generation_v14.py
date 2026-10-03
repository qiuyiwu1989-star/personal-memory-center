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

    def invoke(self, messages, respond, source_metadata=None):
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
                'source_type': 'conversation', 'source_metadata':source_metadata,
                'payload': json.dumps(messages, ensure_ascii=False),
            })
        return result, captured

    def test_quality_review_is_persistable_metadata_without_adoption(self):
        messages=[{'id':'synthetic-review','role':'user','text':'我的合成项目名叫 Atlas；希望未来支持离线查询。'}]
        def respond(payload):
            return {'claims':[{'topic':'projects','kind':'plan','subject':'synthetic-project',
                'statement':'用户的合成项目名叫 Atlas，用户希望未来支持离线查询。',
                'evidence_id':payload['messages'][0]['evidence_spans'][0]['evidence_id']}]}
        (plan,usage),calls=self.invoke(messages,respond)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(plan['claims']),1)
        self.assertFalse(usage['quality_assessment']['quality_approved'])
        self.assertIn(plan['claims'][0]['statement'],usage['quality_review_notes'])
        self.assertNotIn('statement',usage['quality_assessment']['items'][0])
        self.assertEqual(usage['method_version'],PROMPT_VERSION)

    def test_quality_review_failure_preserves_provider_usage(self):
        from pipeline.memory_center.model import ModelOutputError
        messages=[{'id':'synthetic-review-fail','role':'user','text':'我希望合成项目长期保留原始出处。'}]
        def respond(payload):
            return {'claims':[{'topic':'projects','kind':'plan','subject':'synthetic-project',
                'statement':'用户希望合成项目长期保留原始出处。',
                'evidence_id':payload['messages'][0]['evidence_spans'][0]['evidence_id']}]}
        with patch('pipeline.memory_center.extraction_quality.review',side_effect=RuntimeError('synthetic-private-detail')):
            with self.assertRaises(ModelOutputError) as raised:self.invoke(messages,respond)
        self.assertEqual(raised.exception.usage['total_tokens'],50)
        self.assertNotIn('synthetic-private-detail',str(raised.exception))

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
        self.assertEqual(PROMPT_VERSION, '2026-10-03.18')
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
        self.assertEqual(raised.exception.usage['method_version'], '2026-10-03.18')
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
        self.assertEqual(usage['method_version'], '2026-10-03.18')
        self.assertEqual(usage['total_tokens'], 0)


    def test_v18_ordinary_constraints_stay_visible_with_temporary_task(self):
        # This verifies input plumbing and a synthetic response, not whether a
        # provider follows the coverage checklist or selects correct memories.
        messages = [
            {'id':'design','role':'user','text':'合成项目 Atlas 的长期边界：不要自动公开私有内容。'},
            {'id':'request','role':'user','text':'请为今天的评审写一段开场白。'},
        ]
        def respond(payload):
            design, transient = payload['messages']
            self.assertEqual(design['evidence_spans'][0]['priority_hint'],'ordinary')
            self.assertIn('不要自动公开私有内容',design['evidence_spans'][0]['text'])
            self.assertEqual(transient['route'],'conversation')
            return {'claims':[{'topic':'projects','kind':'claim','subject':'Atlas',
                'statement':'用户要求合成项目 Atlas 不要自动公开私有内容。',
                'evidence_id':design['evidence_spans'][0]['evidence_id']}]}
        (plan, usage), _ = self.invoke(messages, respond)
        self.assertEqual(len(plan['claims']),1)
        self.assertEqual(plan['claims'][0]['message_id'],'design')
        self.assertFalse(usage['quality_assessment']['quality_approved'])

    def test_v18_keeps_v17_scoped_input_and_locator_contract(self):
        from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
        from pipeline.memory_center.core import encoded, validate_plan
        messages=[{'id':'scope','role':'user',
            'text':'如果测试通过，我计划发布 Atlas。另外，我对另一个独立项目 Orion 的要求是：保留每条原始证据。',
            'source_title':'Synthetic scoped projects','created_at':'2026-01-02'}]
        outputs=[]
        for version in ('2026-10-03.17','2026-10-03.18'):
            request, spans, routes=prepare_request('conversation',messages,version=version,
                source_metadata={'visibility':'complete_visible','attachments_verified':True})
            self.assertEqual(len(spans),2)
            self.assertEqual(request['source_visibility'],{'status':'complete_visible',
                'declaration_only':True,'attachments_verified':False})
            sid=list(spans)[1]
            resolved=resolve_plan({'claims':[{'topic':'projects','kind':'claim','subject':'Orion',
                'statement':'用户对独立项目 Orion 要求保留每条原始证据。',
                'evidence_id':sid}]},spans,version=version)
            result=validate_plan(resolved,{'source_type':'conversation','trusted_user':False,
                'payload':encoded(messages),'processing_method_version':version})
            self.assertIn('来源消息日期：2026-01-02',result[0]['statement'])
            self.assertIn('来源对话：Synthetic scoped projects。',result[0]['statement'])
            self.assertEqual(result[0]['status'],'source_reported')
            self.assertEqual(result[0]['quote'],messages[0]['text'][result[0]['start']:result[0]['end']])
            outputs.append((request,spans,routes,result))
        self.assertEqual(outputs[0],outputs[1])

    def test_v18_preserves_v17_condition_and_commitment_rejection(self):
        from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
        from pipeline.memory_center.core import encoded, validate_plan, Invalid
        for text, statement in (
            ('如果评测通过，我计划开放 Atlas。','用户已决定开放 Atlas。'),
            ('我希望合成项目保留原始证据。','用户已决定合成项目保留原始证据。'),
        ):
            messages=[{'id':'wish','role':'user','text':text}]
            for version in ('2026-10-03.17','2026-10-03.18'):
                with self.subTest(version=version,text=text):
                    _, spans, _=prepare_request('conversation',messages,version=version)
                    claim={'topic':'projects','kind':'decision','subject':'Atlas',
                        'statement':statement,'evidence_id':next(iter(spans))}
                    with self.assertRaises(Invalid):
                        resolve_plan({'claims':[claim]},spans,version=version)
                    # Validate independently: bypassing the resolver must not
                    # bypass the method-version guard in core.
                    raw={k:v for k,v in claim.items() if k!='evidence_id'}
                    raw.update(message_id='wish',quote=text)
                    with self.assertRaises(Invalid):
                        validate_plan({'claims':[raw]},{'source_type':'conversation',
                            'trusted_user':False,'payload':encoded(messages),
                            'processing_method_version':version})

    def test_v18_core_still_requires_historical_labels_and_summary_time(self):
        from pipeline.memory_center.core import encoded, validate_plan, Invalid
        messages=[{'id':'dated','role':'user','text':'合成项目 Atlas 要长期保留证据。',
            'source_title':'Synthetic requirements','created_at':'2026-01-02'}]
        claim={'topic':'projects','kind':'claim','subject':'Atlas','message_id':'dated',
            'quote':messages[0]['text'],'statement':'用户要求合成项目 Atlas 长期保留证据。'}
        for version in ('2026-10-03.17','2026-10-03.18'):
            with self.subTest(version=version):
                source={'source_type':'conversation','trusted_user':False,'payload':encoded(messages),
                    'processing_method_version':version}
                with self.assertRaisesRegex(Invalid,'来源日期'):
                    validate_plan({'claims':[claim]},source)
                dated=dict(claim,statement='2026-01-02，'+claim['statement'])
                with self.assertRaisesRegex(Invalid,'对话标题'):
                    validate_plan({'claims':[dated]},source)
                source['source_type']='imported_summary'
                summarized=dict(claim,statement='摘要记载合成项目 Atlas 长期保留证据。')
                with self.assertRaisesRegex(Invalid,'原始时间未知'):
                    validate_plan({'claims':[summarized]},source)


if __name__ == '__main__':
    unittest.main()

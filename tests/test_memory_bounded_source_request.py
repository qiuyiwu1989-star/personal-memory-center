"""Synthetic sources only: runnable original-ID request integrity contracts."""
import copy
import unittest
from pipeline.memory_center.core import Invalid
from pipeline.memory_center.long_source_plan import plan_long_source
from pipeline.memory_center.bounded_source_request import (
    plan_bounded_source_requests, verified_bounded_source_request)
from pipeline.memory_center.extraction_input import resolve_plan

METHOD = '2026-10-04.22'


class BoundedSourceRequestTests(unittest.TestCase):
    def envelope(self, text):
        return {'source_key': 'synthetic-request', 'scope': 'synthetic:inbox',
            'source_type': 'conversation', 'source_metadata': {'visibility': 'visible_only'},
            'messages': [{'id': 'original', 'role': 'user', 'text': text}]}

    def prepare(self, envelope, **options):
        archive = plan_long_source(**envelope)
        return archive, plan_bounded_source_requests(envelope, archive, version=METHOD, **options)

    def test_small_request_preserves_original_ids_roles_quotes_and_offsets(self):
        env = self.envelope('我的长期目标是改善合成项目。')
        archive, packet = self.prepare(env)
        bundle = packet['requests'][0]
        sid, span = next(iter(bundle['spans'].items()))
        self.assertEqual(span['message_id'], 'original')
        self.assertEqual(env['messages'][0]['text'][span['start']:span['end']], span['quote'])
        self.assertEqual(bundle['request']['messages'][0]['id'], 'original')
        self.assertEqual(bundle['request']['messages'][0]['role'], 'user')
        self.assertTrue(bundle['context_complete'])
        self.assertFalse(bundle['quality_approved'])
        self.assertFalse(bundle['automatic_extraction_authorized'])
        self.assertEqual(verified_bounded_source_request(env, archive, bundle['request_id'], version=METHOD), bundle)
        resolved = resolve_plan({'claims': [{'evidence_id': sid,
            'statement': '我的长期目标是改善合成项目。', 'kind': 'goal'}]}, bundle['spans'], version=METHOD)
        self.assertEqual(resolved['claims'][0]['message_id'], 'original')

    def test_reference_tail_is_bounded_without_turning_into_evidence(self):
        env = self.envelope('我的长期目标是改善合成系统。\n你是助手，核心使命：' + '合成模板我决定上线。' * 10000)
        _, packet = self.prepare(env)
        bundle = packet['requests'][0]
        self.assertLess(bundle['request_bytes'], 65536)
        self.assertFalse(bundle['context_complete'])
        self.assertTrue(bundle['review_required'])
        self.assertEqual([span['quote'] for span in bundle['spans'].values()], ['我的长期目标是改善合成系统。'])
        self.assertEqual(bundle['request']['messages'][0]['reference_reason'], 'role_template')
        self.assertIsNotNone(bundle['request']['source_context'][0]['omitted_range'])

    def test_oversized_ordinary_condition_context_is_blocked_not_cut(self):
        env = self.envelope('如果通过审批，我才启动合成项目。' + '合成背景。' * 15000)
        _, packet = self.prepare(env)
        self.assertEqual(packet['requests'], [])
        self.assertTrue(any(row['reason'] == 'complete_context_exceeds_request_byte_limit' for row in packet['blocked']))

    def test_neighbors_roles_conditions_and_corrections_are_context_only(self):
        env = self.envelope('如果审批通过才上线。')
        env['messages'] += [{'id': 'assistant', 'role': 'assistant', 'text': '建议现在上线。'},
                            {'id': 'correction', 'role': 'user', 'text': '更正：审批没有通过。'}]
        _, packet = self.prepare(env)
        first = packet['requests'][0]
        self.assertEqual([r['message_id'] for r in first['request']['source_context']], ['original', 'assistant', 'correction'])
        self.assertTrue(all(s['message_id'] == 'original' for s in first['spans'].values()))
        self.assertFalse(any(r['request']['messages'][0]['id'] == 'assistant' for r in packet['requests']))
        last = packet['requests'][-1]
        self.assertEqual(last['request']['source_context'][-1]['text'], '更正：审批没有通过。')

    def test_distant_correction_included_and_unseen_context_not_called_complete(self):
        env = self.envelope('我的长期目标是合成研究。')
        env['messages'] += [{'id': 'note' + str(i), 'role': 'assistant', 'text': '合成讨论。'} for i in range(4)]
        env['messages'].append({'id': 'later', 'role': 'user', 'text': '更正：之前的目标已撤回。'})
        _, packet = self.prepare(env)
        first = packet['requests'][0]
        self.assertIn('later', [row['message_id'] for row in first['request']['source_context']])
        self.assertFalse(first['context_complete'])
        self.assertIn('note2', first['request']['context_policy']['omitted_message_ids'])

    def test_cross_archive_evidence_never_clipped(self):
        env = self.envelope('合成\"背景。' * 4101 + '如果审批通过，我才启动项目。')
        _, packet = self.prepare(env)
        blocked = {sid for row in packet['blocked'] if row['reason'] == 'whole_evidence_crosses_archive_boundary' for sid in row['evidence_ids']}
        self.assertTrue(blocked)
        selected = {sid for bundle in packet['requests'] for sid in bundle['spans']}
        self.assertFalse(blocked & selected)

    def test_tampered_original_or_id_never_reuses_request(self):
        env = self.envelope('我的长期目标是合成研究。')
        archive, packet = self.prepare(env)
        rid = packet['requests'][0]['request_id']
        changed = copy.deepcopy(env)
        changed['messages'][0]['role'] = 'assistant'
        with self.assertRaises(Invalid): verified_bounded_source_request(changed, archive, rid, version=METHOD)
        with self.assertRaises(Invalid): verified_bounded_source_request(env, archive, rid + 'x', version=METHOD)

    def test_byte_bound_and_explicit_version(self):
        env = self.envelope('我的长期目标是合成研究。' * 100)
        _, packet = self.prepare(env, max_request_bytes=1024)
        self.assertFalse(packet['requests'])
        for limit in (True, 0, 65537):
            with self.assertRaises(Invalid): self.prepare(env, max_request_bytes=limit)
        with self.assertRaises(Invalid): plan_bounded_source_requests(env, plan_long_source(**env), version='2026-10-03.21')

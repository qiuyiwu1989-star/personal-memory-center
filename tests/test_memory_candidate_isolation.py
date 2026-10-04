"""Synthetic fixtures only; no model, persistence or private material."""
import copy
import hashlib
import json
import unittest
from pipeline.memory_center.candidate_isolation import diagnose_candidates
from pipeline.memory_center.core import Invalid
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan

VERSION = '2026-10-03.21'


class IsolationTests(unittest.TestCase):
    def fixture(self, messages=None):
        messages = messages or [
            {'id': 'synthetic-a', 'role': 'user', 'text': '我希望保存所有证据。'},
            {'id': 'synthetic-b', 'role': 'user', 'text': '我决定每次保存审阅日志。'},
        ]
        _, spans, _ = prepare_request('conversation', messages, version=VERSION)
        source = {'source_type': 'conversation', 'trusted_user': True,
                  'payload': json.dumps(messages, ensure_ascii=False)}
        ids = list(spans)
        plan = {'claims': [
            {'evidence_id': ids[0], 'statement': '用户决定保存所有证据。', 'subject': '用户', 'kind': 'decision', 'topic': 'preferences'},
            {'evidence_id': ids[-1], 'statement': '用户决定每次保存审阅日志。', 'subject': '用户', 'kind': 'decision', 'topic': 'preferences'},
        ]}
        return plan, spans, source

    def diagnose(self, plan, spans, source, **kw):
        return diagnose_candidates(plan, spans, source, version=VERSION, opt_in=True, **kw)

    def test_explicit_opt_in_and_version_required(self):
        plan, spans, source = self.fixture()
        for value in (False, None, 1, 'true'):
            with self.assertRaises(Invalid):
                diagnose_candidates(plan, spans, source, version=VERSION, opt_in=value)
        with self.assertRaises(Invalid):
            diagnose_candidates(plan, spans, source, version='future', opt_in=True)

    def test_failed_candidate_keeps_sibling_and_original_order(self):
        plan, spans, source = self.fixture()
        original = copy.deepcopy((plan, spans, source))
        receipt = self.diagnose(plan, spans, source)
        self.assertNotIn('claims', receipt)
        self.assertFalse(receipt['adoption_allowed'])
        self.assertEqual([i['ordinal'] for i in receipt['diagnostic_items']], [0, 1])
        self.assertEqual([i['state'] for i in receipt['diagnostic_items']], ['quarantined', 'guard_passed_requires_review'])
        self.assertTrue(receipt['diagnostic_items'][0]['reasons'])
        self.assertEqual((plan, spans, source), original)
        with self.assertRaises(Invalid):
            resolve_plan(plan, spans, version=VERSION)  # Production remains all-or-nothing.

    def test_whole_source_and_exact_locator_are_retained(self):
        plan, spans, source = self.fixture()
        receipt = self.diagnose(plan, spans, source)
        self.assertEqual(receipt['source_payload_sha256'], hashlib.sha256(source['payload'].encode()).hexdigest())
        self.assertEqual(receipt['source_context'], json.loads(source['payload']))
        for item in receipt['diagnostic_items']:
            locator = item['locator']
            message = next(m for m in receipt['source_context'] if m['id'] == locator['message_id'])
            self.assertEqual(message['text'][locator['start']:locator['end']], spans[locator['evidence_id']]['quote'])
        receipt['source_context'][0]['text'] = 'mutated'
        self.assertNotIn('mutated', source['payload'])

    def test_unknown_and_conflicting_evidence_is_quarantined(self):
        plan, spans, source = self.fixture()
        for patch in ({'evidence_id': 'unknown'}, {'message_id': 'not-original'}, {'quote': 'fabricated'}):
            changed = copy.deepcopy(plan)
            changed['claims'][0].update(patch)
            receipt = self.diagnose(changed, spans, source)
            self.assertEqual(receipt['diagnostic_items'][0]['state'], 'quarantined')
            self.assertEqual(receipt['diagnostic_items'][1]['state'], 'guard_passed_requires_review')

    def test_illegal_structure_rejects_entire_batch(self):
        plan, spans, source = self.fixture()
        for malformed in ({}, {'claims': {}}, {'claims': [None]}, {'claims': plan['claims'] * 7}):
            with self.assertRaises(Invalid):
                self.diagnose(malformed, spans, source)
        for patch in ({'statement': []}, {'topic': 'bad'}, {'subject': ''}, {'quote': 3}, {'kind': 'bad'}):
            changed = copy.deepcopy(plan)
            changed['claims'][0].update(patch)
            with self.assertRaises(Invalid):
                self.diagnose(changed, spans, source)

    def test_broken_source_binding_rejects_entire_batch(self):
        plan, spans, source = self.fixture()
        for patch in ({'start': -1}, {'end': True}, {'quote': 'invented'}, {'message_id': 'unknown'}, {'message_id': []}, {'_source_title': 'forged title'}, {'_created_at': '2001-01-01'}, {'_source_type': 'imported_summary'}):
            changed = copy.deepcopy(spans)
            changed[next(iter(changed))].update(patch)
            with self.assertRaises(Invalid):
                self.diagnose(plan, changed, source)
        changed = dict(source, payload=source['payload'][:-1])
        with self.assertRaises(Invalid):
            self.diagnose(plan, spans, changed)

    def test_batch_assistant_limit_not_evaded(self):
        # Imported summaries allow assistant source rows; guard status remains derived.
        messages = [{'id': 'synthetic-' + str(i), 'role': 'assistant', 'text': '摘要记载原始时间未知：可考虑保留资料。'} for i in range(3)]
        _, spans, _ = prepare_request('document', messages, version=VERSION)
        source = {'source_type': 'document', 'payload': json.dumps(messages), 'trusted_user': False}
        claims = [{'evidence_id': sid, 'statement': '可考虑保留资料。', 'subject': '助手', 'kind': 'suggestion', 'topic': 'topics'} for sid in spans]
        receipt = self.diagnose({'claims': claims}, spans, source)
        self.assertTrue(receipt['batch_reasons'])
        self.assertEqual([i['state'] for i in receipt['diagnostic_items']], ['batch_review_required'] * 3)
        self.assertEqual([i['resolved_candidate']['status'] for i in receipt['diagnostic_items']], ['agent_suggested'] * 3)

    def test_external_document_preserves_source_reported_attribution(self):
        messages = [{'id': 'synthetic-external', 'role': 'external',
                     'text': '外部顾问建议保留审阅日志。'}]
        _, spans, _ = prepare_request('document', messages, version=VERSION)
        source = {'source_type': 'document', 'payload': json.dumps(messages),
                  'trusted_user': True}
        plan = {'claims': [{'evidence_id': next(iter(spans)),
                           'statement': '外部顾问建议保留审阅日志。',
                           'subject': '外部顾问', 'kind': 'suggestion', 'topic': 'topics'}]}
        receipt = self.diagnose(plan, spans, source)
        item = receipt['diagnostic_items'][0]
        self.assertEqual(item['state'], 'guard_passed_requires_review')
        self.assertEqual(item['resolved_candidate']['status'], 'source_reported')
        self.assertEqual(receipt['source_context'][0]['role'], 'external')
        self.assertFalse(receipt['adoption_allowed'])

    def test_invalid_source_shape_duplicate_ids_and_system_role_reject(self):
        plan, spans, source = self.fixture()
        messages = json.loads(source['payload'])
        for invalid in ({'messages': messages}, [], messages * 51,
                        messages + [messages[0]],
                        [dict(messages[0], role='system'), messages[1]],
                        [dict(messages[0], id=''), messages[1]],
                        [dict(messages[0], text='   '), messages[1]]):
            with self.assertRaises(Invalid):
                self.diagnose(plan, spans, dict(source, payload=json.dumps(invalid)))

    def test_empty_success_is_distinct_from_quarantine(self):
        _, spans, source = self.fixture()
        receipt = self.diagnose({'claims': []}, spans, source)
        self.assertEqual(receipt['original_count'], 0)
        self.assertEqual(receipt['diagnostic_items'], [])
        self.assertEqual(receipt['batch_reasons'], [])


if __name__ == '__main__':
    unittest.main()

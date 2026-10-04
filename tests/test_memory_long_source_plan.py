"""Synthetic only; no private source fixtures or model calls."""
import copy
import json
import tempfile
import subprocess
import sys
from pathlib import Path
import unittest

from pipeline.memory_center.core import Invalid, Store, encoded
from pipeline.memory_center.long_source_plan import plan_long_source, verify_long_source_plan


class LongSourcePlanTests(unittest.TestCase):
    def plan(self, messages):
        return plan_long_source('synthetic:meeting', messages, scope='synthetic:inbox',
                                source_metadata={'locator': 'synthetic original', 'visibility': 'complete_visible'})

    def test_long_meeting_lossless_and_roles_explicit(self):
        messages = [{'id': 'meeting', 'role': 'external', 'text': '甲：如果批准预算才做。\n乙：这是建议。\n' * 3200},
                    {'id': 'correction', 'role': 'user', 'text': '更正：尚未批准。'}]
        plan = self.plan(messages)
        self.assertGreater(len(plan['segments']), 3)
        for index, message in enumerate(messages):
            parts = [s for s in plan['segments'] if s['message_index'] == index]
            self.assertEqual(''.join(s['payload']['messages'][0]['text'] for s in parts), message['text'])
            self.assertTrue(all(s['payload']['messages'][0]['role'] == message['role'] for s in parts))
        self.assertTrue(verify_long_source_plan(plan, messages)['literal_coverage_verified'])
        self.assertFalse(plan['quality_approved'])

    def test_emoji_offsets_and_escaped_payload_limit(self):
        messages = [{'id': 'unicode', 'role': 'external', 'text': '🦞\\"\n' * 13000}]
        plan = self.plan(messages)
        for s in plan['segments']:
            text = s['payload']['messages'][0]['text']
            self.assertEqual(text, messages[0]['text'][s['start']:s['end']])
            self.assertLessEqual(len(text), 20000)
            self.assertLessEqual(len(encoded(s['payload']['messages'])), 24000)
            self.assertLessEqual(len(s['payload']['source_metadata']['locator']), 1000)

    def test_ascii_conservative_review_limit(self):
        plan = self.plan([{'id': 'long', 'role': 'user', 'text': 'x' * 21000}])
        self.assertEqual(len(plan['segments']), 2)

    def test_stable_retries_and_changed_source(self):
        original = [{'id': 'm', 'role': 'user', 'text': 'Synthetic source ' * 2000}]
        first = self.plan(original)
        self.assertEqual(first, self.plan(copy.deepcopy(original)))
        changed = copy.deepcopy(original)
        changed[0]['text'] += '!'
        self.assertNotEqual(first['segments'][0]['segment_id'], self.plan(changed)['segments'][0]['segment_id'])
        self.assertNotIn('parent_source_key', original[0])

    def test_cross_boundary_condition_is_never_released(self):
        messages = [{'id': 'm', 'role': 'user', 'text': '如果预算批准，' + '合成背景。' * 4100 + '才启动项目。'}]
        plan = self.plan(messages)
        self.assertGreater(len(plan['segments']), 1)
        for segment in plan['segments']:
            self.assertIn('condition_scope_requires_semantic_review', segment['review_reasons'])
            self.assertEqual(segment['context_navigation']['purpose'], 'navigation_only_not_evidence')
        self.assertFalse(plan['automatic_scope_release'])

    def test_corrupted_receipts_refused(self):
        messages = [{'id': 'm', 'role': 'external', 'text': 'Synthetic ' * 5000}]
        original = self.plan(messages)
        mutations = [lambda p: p['segments'].pop(),
                     lambda p: p['segments'][0].__setitem__('start', 1),
                     lambda p: p['segments'].reverse(),
                     lambda p: p['segments'][0]['payload']['messages'][0].__setitem__('role', 'user'),
                     lambda p: p['segments'][0]['context_navigation'].__setitem__('purpose', 'evidence'),
                     lambda p: p['ledger'].__setitem__('covered_characters', 0),
                     lambda p: p.__setitem__('automatic_scope_release', True),
                     lambda p: p['segments'][0].__setitem__('text_sha256', '0' * 64)]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                plan = copy.deepcopy(original)
                mutate(plan)
                with self.assertRaises(Invalid):
                    verify_long_source_plan(plan, messages)
        changed = copy.deepcopy(messages)
        changed[0]['text'] += '.'
        with self.assertRaises(Invalid):
            verify_long_source_plan(original, changed)

    def test_real_archive_retry_and_global_locator(self):
        messages = [{'id': 'm', 'role': 'external', 'text': 'Synthetic meeting ' * 2400}]
        plan = self.plan(messages)
        principal = {'id': 'synthetic', 'owner': 'synthetic-owner',
                     'scopes': ['synthetic:inbox'], 'actions': ['read', 'write'], 'trusted_user': False}
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            for segment in plan['segments']:
                payload = segment['payload']
                locator = json.loads(json.loads(payload['source_metadata']['locator'])['original_locator'])
                self.assertEqual(locator['global_start'], segment['global_start'])
                self.assertEqual(locator['original_message_id'], 'm')
                self.assertFalse(store.ingest(principal, payload)['duplicate'])
                self.assertTrue(store.ingest(principal, payload)['duplicate'])
            with store.db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0], 0)
                self.assertEqual({r[0] for r in db.execute('SELECT state FROM jobs')}, {'archived'})
            def no_model(*args):
                raise AssertionError('model must not run')
            self.assertFalse(store.process_one(no_model))

    def test_cli_private_exclusive_output(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.json', Path(directory) / 'plan.json'
            source.write_text(json.dumps({'source_key': 'synthetic', 'scope': 'synthetic:inbox',
                'messages': [{'id': 'm', 'role': 'external', 'text': 'Synthetic private fixture'}]}))
            command = [sys.executable, str(repo / 'scripts/plan_long_source.py'), '--input', str(source), '--output', str(output)]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn('Synthetic private fixture', run.stdout)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            command[-1] = str(repo / 'never-private-source-plan.json')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            self.assertFalse((repo / 'never-private-source-plan.json').exists())

    def test_whitespace_and_unknown_authors_are_not_guessed(self):
        valid = [{'id': 'm', 'role': 'external', 'text': '\n' + '合成记录 ' * 6000 + '   '}]
        self.assertTrue(verify_long_source_plan(self.plan(valid), valid)['literal_coverage_verified'])
        for message in [{'id': 'm', 'role': 'unknown', 'text': 'Source'},
                        {'id': 'm', 'role': 'external', 'text': ' ' * 30000},
                        {'id': 'm', 'role': 'external', 'text': 'a' + ' ' * 30000}]:
            with self.assertRaises(Invalid):
                self.plan([message])
        with self.assertRaises(Invalid):
            self.plan([valid[0], valid[0]])


if __name__ == '__main__':
    unittest.main()

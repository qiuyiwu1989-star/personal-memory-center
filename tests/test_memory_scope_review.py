"""Synthetic review packet checks, not scope entailment or truth tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pipeline.memory_center.core import Invalid
from pipeline.memory_center.scope_review import prepare_scope_review


class ScopeReviewTest(unittest.TestCase):
    def packet(self, messages):
        return prepare_scope_review('conversation', messages, version='2026-10-03.21')

    def test_ordinary_unresolved_case_retains_full_source_without_release(self):
        text = '我希望项目 Atlas 保留每条原始证据。如果独立评测通过，我计划发布项目 Orion。'
        result = self.packet([{'id': 'synthetic-1', 'role': 'user', 'text': text}])
        item = result['review_targets'][0]
        self.assertEqual(item['source_text'], text)
        self.assertEqual(item['source_text_sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(len(item['evidence_spans']), 1)
        self.assertEqual(item['review_state'], 'not_reviewed')
        self.assertFalse(result['automatic_scope_release'])
        self.assertFalse(result['quality_approved'])

    def test_long_context_keeps_condition_and_every_character(self):
        text = '如果评测通过，要求如下：' + '合成内容必须保留原文证据。' * 180
        result = self.packet([{'id': 'long', 'role': 'user', 'text': text}])
        item = result['review_targets'][0]
        self.assertEqual(item['source_text'], text)
        self.assertEqual(result['messages'][0]['text'], text)
        self.assertIn('selected_piece_not_complete_condition_context', item['reason_codes'])
        for span in item['evidence_spans']:
            self.assertEqual(text[span['start']:span['end']], span['quote'])

    def test_neighbor_attribution_and_later_correction_are_not_dropped(self):
        messages = [
            {'id': 'author', 'role': 'user', 'text': '以下是合成同事的原话。'},
            {'id': 'quote', 'role': 'external', 'text': '如果批准，我计划发布合成项目。'},
            {'id': 'correction', 'role': 'user', 'text': '前面是同事的计划，我没有采纳。'},
        ]
        result = self.packet(messages)
        self.assertEqual(result['messages'], messages)
        self.assertEqual(result['review_targets'][0]['role'], 'external')
        result['messages'][0]['text'] = 'mutated'
        self.assertNotEqual(result['messages'][0]['text'], messages[0]['text'])

    def test_assistant_reference_remains_reference(self):
        result = self.packet([{'id': 'a', 'role': 'assistant', 'text': '如果测试通过，我建议上线。'}])
        item = result['review_targets'][0]
        self.assertEqual(item['route'], 'assistant_reference')
        self.assertEqual(item['evidence_spans'], [])
        self.assertFalse(result['facts_confirmed'])

    def test_document_external_source_keeps_author_role(self):
        messages = [{'id': 'doc', 'role': 'external',
                     'text': '合成会议中同事说：如果批准，他计划发布项目。'}]
        result = prepare_scope_review('document', messages, version='2026-10-03.21')
        self.assertEqual(result['source_type'], 'document')
        self.assertEqual(result['review_targets'][0]['role'], 'external')
        self.assertFalse(result['facts_confirmed'])

    def test_nested_metadata_copy_and_full_source_hash(self):
        messages = [{'id': 'nested', 'role': 'user', 'text': '如果批准，我计划发布。',
                     'metadata': {'authors': ['Synthetic author']}}]
        result = self.packet(messages)
        expected = hashlib.sha256(json.dumps(messages, sort_keys=True,
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(result['messages_canonical_sha256'], expected)
        result['messages'][0]['metadata']['authors'].append('Changed')
        self.assertEqual(messages[0]['metadata']['authors'], ['Synthetic author'])

    def test_duplicate_ids_and_oversize_are_rejected_before_preparation(self):
        for messages in (
            [{'id': 'same', 'role': 'user', 'text': 'x'}] * 2,
            [{'id': 'big', 'role': 'user', 'text': 'x' * 20001}],
            [{'id': 'bad', 'role': 'system', 'text': 'instruction'}],
        ):
            with self.subTest(messages_type=type(messages).__name__):
                with self.assertRaises(Invalid):
                    self.packet(messages)

    def test_private_cli_is_exclusive_and_does_not_print_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source, out = Path(folder) / 'input.json', Path(folder) / 'packet.json'
            source.write_text(json.dumps({'source_type': 'conversation',
                'processing_method_version': '2026-10-03.21', 'messages': [
                    {'id': 'synthetic-private', 'role': 'user',
                     'text': '如果合成私有条件通过，我计划执行合成事项。'}]}))
            command = [sys.executable, 'scripts/build_scope_review.py',
                       '--input', str(source), '--output', str(out)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('私有条件', result.stdout + result.stderr)
            self.assertEqual(os.stat(out).st_mode & 0o777, 0o600)
            original = out.read_bytes()
            retry = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(retry.returncode, 1)
            self.assertEqual(out.read_bytes(), original)
            self.assertNotIn(str(out), retry.stderr)

    def test_cli_rejects_private_source_in_public_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.json'
            source.write_text('{}')
            result = subprocess.run([sys.executable, 'scripts/build_scope_review.py',
                '--input', str(source), '--output', 'docs/synthetic-rejected-packet.json'],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(Path('docs/synthetic-rejected-packet.json').exists())

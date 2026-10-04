"""Synthetic navigation and coverage tests, not semantic acceptance scores."""
import unittest

from pipeline.memory_center.scope_diagnostics import scope_observations
from pipeline.memory_center.scope_review import prepare_scope_review


class ScopeDiagnosticsTest(unittest.TestCase):
    def packet(self, text, role='user', version='2026-10-03.21'):
        return prepare_scope_review('conversation', [
            {'id': 'synthetic-scope', 'role': role, 'text': text}], version=version)

    def assert_lossless(self, text, result):
        self.assertEqual(''.join(unit['text'] for unit in result['display_units']), text)
        for field in ('display_units', 'condition_occurrences', 'project_surface_mentions'):
            for item in result[field]:
                self.assertEqual(text[item['start']:item['end']], item['text'])
        self.assertFalse(result['display_units_are_evidence_spans'])
        self.assertFalse(result['automatic_scope_release'])
        self.assertEqual(result['scope_relationship'], 'not_established')

    def test_frozen_ordinary_case_is_navigable_but_not_released(self):
        text = '我希望项目 Atlas 保留每条原始证据。如果独立评测通过，我计划发布项目 Orion。'
        result = scope_observations(text)
        self.assert_lossless(text, result)
        self.assertEqual(len(result['display_units']), 2)
        self.assertEqual([p['surface_name'] for p in result['project_surface_mentions']], ['Atlas', 'Orion'])
        self.assertIn('distinct_project_surface_names_not_independence', result['reason_codes'])
        self.assertEqual(len(self.packet(text)['review_targets'][0]['evidence_spans']), 1)

    def test_postposed_condition_remains_unresolved(self):
        text = '我计划发布项目 Atlas。前提是独立评测通过。'
        result = scope_observations(text)
        self.assert_lossless(text, result)
        self.assertIn('condition_free_display_unit_not_unconditional_evidence', result['reason_codes'])
        self.assertEqual(result['condition_occurrences'][0]['text'], '前提')

    def test_quotation_list_and_reference_cannot_release(self):
        for text in ('如果通过，要求如下：\n1. 我希望它保留证据。\n2. 项目 Orion 发布。',
                     '同事说：“如果通过，我计划发布项目 Atlas。”用户希望项目 Orion 保留证据。'):
            with self.subTest(text=text):
                result = scope_observations(text)
                self.assert_lossless(text, result)
                self.assertIn('quoted_or_grouped_context_requires_review', result['reason_codes'])
                self.assertFalse(result['quality_approved'])

    def test_english_condition_offsets_are_unicode_offsets(self):
        text = '合成😀。If approved, I plan to release Atlas; unless cancelled, keep evidence.'
        result = scope_observations(text)
        self.assert_lossless(text, result)
        self.assertEqual([item['text'] for item in result['condition_occurrences']], ['If', 'unless'])

    def test_long_condition_coverage_does_not_erase_truncation_risk(self):
        text = '如果评测通过，要求如下：' + '合成内容必须保留原文证据。' * 180
        packet = self.packet(text)
        item = packet['review_targets'][0]
        self.assertEqual(item['evidence_characters'], len(text))
        self.assertIn('selected_piece_not_complete_condition_context', item['reason_codes'])
        self.assertFalse(packet['evidence_coverage']['is_quality_score'])
        self.assert_lossless(text, item['scope_observations'])

    def test_zero_evidence_is_explicit_even_without_condition(self):
        text = '合成助手的一段建议，仅供参考。'
        packet = self.packet(text, 'assistant')
        self.assertEqual(packet['evidence_coverage']['evidence_characters'], 0)
        self.assertEqual(packet['evidence_coverage']['zero_evidence_message_ids'], ['synthetic-scope'])
        item = packet['review_targets'][0]
        self.assertIn('source_without_extractable_evidence_not_quality_pass', item['reason_codes'])
        self.assertEqual(item['source_text'], text)
        self.assertFalse(packet['quality_approved'])

    def test_v17_runtime_evidence_boundaries_remain_unchanged(self):
        text = '我希望项目 Atlas 保留证据。如果通过，我计划发布项目 Orion。'
        packet = self.packet(text, version='2026-10-03.17')
        self.assertEqual(len(packet['review_targets'][0]['evidence_spans']), 1)
        self.assertEqual(packet['method_version'], '2026-10-03.17')

    def test_empty_surface_and_ordinary_text_grant_no_quality(self):
        for text in ('', '合成正文无条件。'):
            result = scope_observations(text)
            self.assert_lossless(text, result)
            self.assertFalse(result['quality_approved'])


if __name__ == '__main__':
    unittest.main()

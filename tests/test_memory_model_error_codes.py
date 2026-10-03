import unittest
from unittest.mock import patch

from pipeline.memory_center.model import Model, ModelOutputError


class ModelErrorCodeTests(unittest.TestCase):
    def assert_measured_receipt(self, actual, measured):
        self.assertEqual(actual, measured | {
            'source_visibility': {'status': 'unknown', 'declaration_only': True,
                                  'attachments_verified': False},
            'condition_scope_guard_version': 'condition-scope-v2-explicit',
        })
        for field, value in measured.items():
            self.assertEqual(actual[field], value)

    def test_resolution_failure_keeps_measured_usage_and_code(self):
        usage = {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
        source = {'source_type': 'conversation', 'payload': '[{"id":"synthetic-1","role":"user","text":"合成示例：本项目使用纸质问卷。"}]'}
        with patch.object(Model, '_call', return_value=({'claims': [{'span_id': 'not-in-source'}]}, usage)):
            with self.assertRaises(ModelOutputError) as caught:
                Model().extract_source(source)
        self.assertEqual(caught.exception.code, 'source_span_contract')
        self.assert_measured_receipt(caught.exception.usage, usage)
        self.assertNotIn('source_visibility', usage)

    def test_diagnostic_failure_is_separate_from_resolution(self):
        usage = {'total_tokens': 15}
        source = {'source_type': 'conversation', 'payload': '[{"id":"synthetic-1","role":"user","text":"合成示例：本项目使用纸质问卷。"}]'}
        with patch.object(Model, '_call', return_value=({'claims': []}, usage)), patch('pipeline.memory_center.extraction_quality.review', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(ModelOutputError) as caught:
                Model().extract_source(source)
        self.assertEqual(caught.exception.code, 'quality_diagnostic')
        self.assert_measured_receipt(caught.exception.usage, usage)
        self.assertNotIn('source_visibility', usage)

    def test_legacy_callers_keep_default(self):
        self.assertEqual(ModelOutputError('synthetic', {}).code, 'output_contract')


if __name__ == '__main__':
    unittest.main()

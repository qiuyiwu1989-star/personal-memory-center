"""Synthetic readiness checks are offline and do not imply actual client access."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from pipeline.memory_center.core import Invalid
from scripts.check_memory_integration import inspect_input, main, run_self_test


class IntegrationReadinessTest(unittest.TestCase):
    def body(self):
        return {'source_key': 'synthetic://private-title-marker',
                'scope': 'agent:synthetic-inbox', 'source_type': 'document',
                'source_metadata': {'author': 'synthetic-private-author-marker'},
                'messages': [{'id': 'external-1', 'role': 'external',
                              'text': 'synthetic-private-body-marker🙂\\\n'}]}

    def test_in_process_protocol_checks_archive_roles_retry_versions_and_permissions(self):
        report = run_self_test()
        self.assertEqual(report['model_calls'], 0)
        self.assertEqual(report['records'], 0)
        self.assertEqual(report['remote_network_calls'], 0)
        self.assertFalse(report['actual_client_verified'])
        self.assertFalse(report['delete_propagation_verified'])
        self.assertIn('revocation-next-request', report['checks_passed'])

    def test_input_inspection_digests_sensitive_data_without_logging_it(self):
        body = self.body()
        result = inspect_input(body)
        serialized = json.dumps(result)
        self.assertNotIn('private-body-marker', serialized)
        self.assertNotIn('private-author-marker', serialized)
        self.assertNotIn('private-title-marker', serialized)
        self.assertEqual(result['roles'], {'user': 0, 'assistant': 0, 'external': 1})
        self.assertEqual(result, inspect_input(json.loads(json.dumps(body))))
        changed = dict(body, messages=[dict(body['messages'][0], role='assistant')])
        self.assertNotEqual(result['payload_sha256'], inspect_input(changed)['payload_sha256'])
        self.assertFalse(result['confirmed_memory'])

    def test_no_default_scope_identity_or_processing_override(self):
        for field in ('scope', 'source_key', 'messages'):
            body = self.body()
            del body[field]
            with self.subTest(missing=field), self.assertRaises(Invalid):
                inspect_input(body)
        for field, value in (('trusted_user', True), ('processing_policy', 'extract'), ('owner', 'synthetic')):
            with self.subTest(override=field), self.assertRaises(Invalid):
                inspect_input(dict(self.body(), **{field: value}))

    def test_cli_redacts_invalid_payload_path_and_error_details(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'synthetic-input.json'
            file.write_text(json.dumps(dict(self.body(), private_field='synthetic-private-error-marker')))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(['--check-input', str(file)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue()), {'ok': False, 'error_type': 'Invalid'})
            self.assertNotIn(directory, output.getvalue())
            self.assertNotIn('private-error-marker', output.getvalue())


if __name__ == '__main__':
    unittest.main()

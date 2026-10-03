"""Synthetic readiness checks are offline and do not imply actual client access."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from pipeline.memory_center.core import Invalid
from scripts.check_memory_integration import inspect_input, inspect_tools, main, run_self_test


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

    def tools(self):
        fields = {'query': 'string', 'scope': 'string', 'max_chars': 'integer',
                  'offset': 'integer', 'window_limit': 'integer', 'retrieval_mode': 'string'}
        def tool(name, keys):
            return {'name': name, 'inputSchema': {'type': 'object', 'required': ['query'],
                'properties': {key: {'type': fields[key]} for key in keys}}}
        return [tool('memory_context', ['query', 'scope', 'max_chars']),
                tool('memory_search', ['query', 'scope', 'max_chars']),
                tool('memory_candidate_search', list(fields))]

    def test_schema_probe_detects_window_without_relying_on_tool_count(self):
        listing = self.tools() + [{'name': 'unrelated-synthetic-tool'}]
        report = inspect_tools({'jsonrpc': '2.0', 'result': {'tools': listing}})
        self.assertTrue(report['progressive_window_ready'])
        self.assertEqual(report['candidate_read_mode'], 'window')
        self.assertFalse(report['permissions_verified'])
        self.assertFalse(report['actual_client_verified'])
        self.assertEqual(report['network_calls'], 0)

    def test_old_host_reports_narrow_query_compatibility_without_inventing_offset(self):
        report = inspect_tools(self.tools()[:2])
        self.assertTrue(report['trusted_context_ready'])
        self.assertFalse(report['progressive_window_ready'])
        self.assertEqual(report['candidate_read_mode'], 'legacy_narrow_query')
        self.assertEqual(report['capabilities']['memory_candidate_search']['reason'], 'tool_missing')
        self.assertIn('no_implicit_paging_or_scope_expansion', report['compatibility_note'])

    def test_same_named_incompatible_tool_is_not_accepted(self):
        for mutation in ('wrong_type', 'missing_offset', 'unknown_required'):
            tools = self.tools()
            schema = tools[2]['inputSchema']
            if mutation == 'wrong_type':
                schema['properties']['window_limit']['type'] = 'string'
            elif mutation == 'missing_offset':
                del schema['properties']['offset']
            else:
                schema['required'].append('synthetic_unknown_argument')
            with self.subTest(mutation=mutation):
                report = inspect_tools(tools)
                self.assertFalse(report['progressive_window_ready'])
                self.assertEqual(report['candidate_read_mode'], 'legacy_narrow_query')
                self.assertEqual(report['capabilities']['memory_candidate_search']['reason'], 'schema_incompatible')

    def test_window_availability_does_not_hide_missing_trusted_context(self):
        report = inspect_tools(self.tools()[1:])
        self.assertFalse(report['trusted_context_ready'])
        self.assertFalse(report['progressive_window_ready'])
        self.assertEqual(report['candidate_read_mode'], 'window')

    def test_malformed_or_duplicate_discovery_is_rejected(self):
        for listing in (None, {'tools': 'synthetic'}, [{'name': 42}], self.tools() * 2):
            with self.subTest(listing=listing), self.assertRaises(Invalid):
                inspect_tools(listing)

    def test_cli_inspects_schema_offline_without_emitting_unrelated_description(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'synthetic-tools.json'
            listing = self.tools()
            listing[0]['description'] = 'synthetic-private-tool-description'
            file.write_text(json.dumps({'tools': listing}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(['--check-tools', str(file)])
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report['progressive_window_ready'])
            self.assertNotIn('private-tool-description', output.getvalue())
            self.assertNotIn(directory, output.getvalue())

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

"""Synthetic single-reader onboarding over actual loopback HTTP; no model."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import uvicorn
from pipeline.memory_center.core import Store
from pipeline.memory_center.service import create_app

spec = importlib.util.spec_from_file_location('single_reader', Path(__file__).resolve().parents[1] / 'scripts/check_agent_memory_connection.py')
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


class AgentConnectionTest(unittest.TestCase):
    def test_clean_environment_only_connection(self):
        base = dict(MEMORY_MCP_URL='https://example.invalid/mcp', MEMORY_AGENT_TOKEN='synthetic-reader')
        self.assertEqual(probe.connection(base)[2], 'personal')
        for url in ('http://example.invalid/mcp', 'https://u:p@example.invalid/mcp', 'https://example.invalid/mcp?token=x'):
            with self.assertRaises(ValueError): probe.connection(dict(base, MEMORY_MCP_URL=url))

    def test_failure_output_redacts_private_details(self):
        output = io.StringIO()
        with patch.object(probe.sys, 'argv', ['check']), patch.object(probe, 'connection', side_effect=ValueError('private-secret')), contextlib.redirect_stdout(output):
            self.assertEqual(probe.main(), 1)
        self.assertNotIn('private-secret', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['writes'], 0)

    def test_real_tcp_empty_context_explicit_candidates_and_denial(self):
        class NoModel:
            configured = False
            def extract(self, *args): raise AssertionError('Unexpected model')
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            grant = dict(id='synthetic-reader', owner='synthetic-owner', scopes=['personal'], actions=['read'], trusted_user=False,
                         token_sha256=hashlib.sha256(b'synthetic-reader').hexdigest())
            listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(128)
            endpoint = 'http://127.0.0.1:' + str(listener.getsockname()[1]) + '/mcp/'
            server = uvicorn.Server(uvicorn.Config(create_app(store, lambda: [grant], NoModel(), run_worker=False), log_level='critical', access_log=False))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True); thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline: time.sleep(.02)
                self.assertTrue(server.started)
                result = probe.probe(endpoint, 'synthetic-reader', 'personal')
                self.assertEqual(result['read_kind'], 'verified_context')
                self.assertTrue(result['empty_is_valid'])
                self.assertFalse(result['instance_acceptance'])
                evidence = probe.probe(endpoint, 'synthetic-reader', 'personal', '合成检索')
                self.assertEqual(evidence['read_kind'], 'candidate_evidence')
                with self.assertRaises(ValueError): probe.probe(endpoint, 'synthetic-reader', 'unauthorized')
                with self.assertRaises(ValueError): probe.probe(endpoint, 'synthetic-reader', 'personal', '')
            finally:
                server.should_exit = True; thread.join(timeout=10); listener.close()
                self.assertFalse(thread.is_alive())


if __name__ == '__main__': unittest.main()

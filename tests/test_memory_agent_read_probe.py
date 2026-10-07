"""Synthetic probe connection policy and failure output redaction."""
import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('memory_read_probe',Path(__file__).resolve().parents[1]/'scripts/check_agent_memory_read.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class AgentReadProbeTest(unittest.TestCase):
    def environment(self,url='https://example.invalid/mcp/'):
        return dict(MEMORY_MCP_URL=url,MEMORY_READER_TOKEN_A='synthetic-a',MEMORY_READER_TOKEN_B='synthetic-b')
    def test_only_secure_clean_endpoints(self):
        self.assertEqual(probe.connection(self.environment())[2],'personal')
        for url in ('http://example.invalid/mcp/','https://user:secret@example.invalid/mcp/','https://example.invalid/mcp/?token=secret','https://example.invalid/mcp/#secret'):
            with self.assertRaises(ValueError):probe.connection(self.environment(url))
        self.assertEqual(probe.connection(self.environment('http://127.0.0.1:1234/mcp/'))[2],'personal')
    def test_independent_credentials(self):
        env=self.environment();env['MEMORY_READER_TOKEN_B']=env['MEMORY_READER_TOKEN_A']
        with self.assertRaises(ValueError):probe.connection(env)
    def test_failure_does_not_echo_exception_or_token(self):
        output=io.StringIO()
        with patch.dict(probe.os.environ,self.environment(),clear=True),patch.object(probe,'probe',side_effect=RuntimeError('synthetic-a private text')),contextlib.redirect_stdout(output):
            self.assertEqual(probe.main(),1)
        self.assertEqual(json.loads(output.getvalue())['error_type'],'RuntimeError')
        self.assertNotIn('synthetic-a',output.getvalue());self.assertNotIn('private text',output.getvalue())

    def test_handshake_and_independent_stateful_session_headers(self):
        calls=[]
        def handle(request):
            payload=json.loads(request.content);token=request.headers['authorization'];calls.append((token,payload['method']))
            session='session-a' if token.endswith('synthetic-a') else 'session-b'
            if payload['method']=='initialize':
                return probe.httpx.Response(200,headers={'mcp-session-id':session},json={'jsonrpc':'2.0','id':payload['id'],'result':{'protocolVersion':'2025-06-18'}})
            self.assertEqual(request.headers['mcp-session-id'],session)
            self.assertEqual(request.headers['mcp-protocol-version'],'2025-06-18')
            if payload['method']=='notifications/initialized': return probe.httpx.Response(202)
            self.assertEqual(payload['method'],'tools/call')
            return probe.httpx.Response(200,json={'jsonrpc':'2.0','id':payload['id'],'result':{'structuredContent':{'records':[],'context_revision':'synthetic-revision'}}})
        client=probe.httpx.Client(transport=probe.httpx.MockTransport(handle))
        with patch.object(probe.httpx,'Client',return_value=client):
            result=probe.probe('https://example.invalid/mcp/',['synthetic-a','synthetic-b'],'personal')
        self.assertEqual(result['initialized_readers'],2)
        self.assertEqual([c[1] for c in calls],['initialize','notifications/initialized','initialize','notifications/initialized','tools/call','tools/call','tools/call','tools/call'])
        self.assertEqual([c[0] for c in calls[4:]],['Bearer synthetic-a','Bearer synthetic-b']*2)

    def test_sse_fails_explicitly(self):
        transport=probe.httpx.MockTransport(lambda request:probe.httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'data: {}'))
        with probe.httpx.Client(transport=transport) as client:
            with self.assertRaisesRegex(ValueError,'SSE unsupported'):
                probe.request_json(client,'https://example.invalid/mcp/',{},dict(id=1))

    def test_oversized_transfer_stops_before_entire_body(self):
        chunks=[]
        class Large(probe.httpx.SyncByteStream):
            def __iter__(self):
                for index in range(1000):
                    chunks.append(index);yield b'x'*4096
        transport=probe.httpx.MockTransport(lambda request:probe.httpx.Response(200,headers={'content-type':'application/json'},stream=Large()))
        with probe.httpx.Client(transport=transport) as client:
            with self.assertRaisesRegex(ValueError,'exceeded probe budget'):
                probe.request_json(client,'https://example.invalid/mcp/',{},dict(id=1))
        self.assertLess(len(chunks),51)

if __name__ == '__main__':unittest.main()

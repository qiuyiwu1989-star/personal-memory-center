"""Offline upstream/downstream readiness checks; never contacts a remote service.

--self-test uses synthetic data and ephemeral in-process MCP, not an actual client.
--check-input prepares payloads but outputs only aggregate counts and SHA256 digests.
--check-tools inspects an offline tools/list export; it never installs or grants access.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.memory_center.core import Invalid, Store, encoded
from pipeline.memory_center.import_adapter import prepare_imports

INPUT_FIELDS = {'source_key', 'scope', 'source_type', 'source_metadata', 'messages'}


READ_SCHEMAS = {
    'memory_context': {'query': 'string', 'scope': 'string', 'max_chars': 'integer'},
    'memory_candidate_search': {'query': 'string', 'scope': 'string', 'max_chars': 'integer',
        'offset': 'integer', 'window_limit': 'integer', 'retrieval_mode': 'string'},
    'memory_search': {'query': 'string', 'scope': 'string', 'max_chars': 'integer'},
    'memory_archive_search': {'query': 'string', 'scope': 'string', 'max_chars': 'integer'},
    'memory_archive_source_get': {'locator': 'object', 'scope': 'string', 'offset': 'integer', 'max_chars': 'integer'},
}


def inspect_tools(body):
    """Probe actual schema capabilities, independent of tool count and token grants."""
    if isinstance(body, dict) and 'result' in body:
        body = body['result']
    listing = body.get('tools') if isinstance(body, dict) else body
    if not isinstance(listing, list) or any(not isinstance(t, dict) for t in listing):
        raise Invalid('Expected tools/list export')
    names = [t.get('name') for t in listing]
    if any(not isinstance(n, str) for n in names) or len(names) != len(set(names)):
        raise Invalid('Invalid or duplicate tool names')
    tools = {t['name']: t for t in listing}
    capabilities = {}
    for name, expected in READ_SCHEMAS.items():
        tool = tools.get(name)
        if tool is None:
            capabilities[name] = {'available': False, 'reason': 'tool_missing'}
            continue
        schema = tool.get('inputSchema', {})
        properties = schema.get('properties', {}) if isinstance(schema, dict) else {}
        if not isinstance(properties, dict):
            properties = {}
        incompatible = [key for key, kind in expected.items()
            if not isinstance(properties.get(key), dict) or properties[key].get('type') != kind]
        # An unknown mandatory parameter cannot be supplied from this contract.
        required = schema.get('required', []) if isinstance(schema, dict) else []
        if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
            required = ['invalid_required_schema']
        supported = set(expected)
        incompatible.extend(key for key in required if key not in supported)
        capabilities[name] = {'available': not incompatible,
            'reason': 'schema_compatible' if not incompatible else 'schema_incompatible',
            'incompatible_fields': sorted(set(incompatible))}
    context_ready = capabilities['memory_context']['available']
    window_ready = capabilities['memory_candidate_search']['available']
    legacy_ready = capabilities['memory_search']['available']
    return {'mode': 'offline-schema-inspection', 'network_calls': 0, 'model_calls': 0,
        'capabilities': capabilities, 'trusted_context_ready': context_ready,
        'progressive_window_ready': context_ready and window_ready,
        'candidate_read_mode': ('window' if window_ready else
            'legacy_narrow_query' if legacy_ready else 'unavailable'),
        'permissions_verified': False, 'actual_client_verified': False,
        'compatibility_note': ('window_available' if window_ready else
            'window_unavailable_no_implicit_paging_or_scope_expansion')}


def inspect_input(body):
    """Validate and summarize preparation without returning private contents."""
    if not isinstance(body, dict) or set(body) - INPUT_FIELDS:
        raise Invalid('Unknown input fields; grants and processing policy are not client input')
    if not {'source_key', 'scope', 'messages'} <= set(body):
        raise Invalid('Missing explicit parent key, scope or messages')
    parts = prepare_imports(**body)
    roles = {role: sum(m['role'] == role for m in body['messages'])
             for role in ('user', 'assistant', 'external')}
    return {'mode': 'offline-preparation', 'network_calls': 0, 'model_calls': 0,
            'input_messages': len(body['messages']), 'roles': roles,
            'archive_parts': len(parts), 'processing_policy': 'archive',
            'max_serialized_messages_chars': max(len(encoded(p['messages'])) for p in parts),
            'payload_sha256': [hashlib.sha256(encoded(p).encode()).hexdigest() for p in parts],
            'confirmed_memory': False}


def run_self_test():
    """Exercise deployed API implementation locally with no credentials/network."""
    from starlette.testclient import TestClient
    from pipeline.memory_center.service import create_app
    from pipeline.memory_center.governance import review

    class NoModel:
        configured = False
        calls = 0
        def extract(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError('Archive-only integration must not invoke a model')

    scope = 'agent:synthetic-integration-inbox'
    messages = [
        {'id': 'external-1', 'role': 'external', 'text': '合成第三方发言🙂\\\n"引文"' * 4000},
        {'id': 'assistant-1', 'role': 'assistant', 'text': '合成助手建议，尚未被采纳。'},
        {'id': 'user-1', 'role': 'user', 'text': '合成本人原话；传输角色不构成身份确认。'}]
    args = dict(source_key='synthetic://integration/document-1', scope=scope,
                messages=messages, source_type='document',
                source_metadata={'original_ref': 'synthetic://integration/raw-1',
                                 'visibility': 'visible_only', 'locator': 'synthetic-speaker-1'})
    parts = prepare_imports(**args)
    assert ''.join(m['text'] for p in parts for m in p['messages'] if m['role'] == 'external') == messages[0]['text']
    assert parts == prepare_imports(**args)
    changed = dict(args, messages=[dict(messages[0], text=messages[0]['text'] + '合成更正。')] + messages[1:])
    changed_parts = prepare_imports(**changed)
    assert {p['source_key'] for p in parts} != {p['source_key'] for p in changed_parts}
    assert inspect_input(args)['roles'] == {'user': 1, 'assistant': 1, 'external': 1}

    token = 'synthetic-integration-secret'
    grant = {'id': 'synthetic-integration-agent', 'owner': 'synthetic-owner', 'scopes': [scope],
             'actions': ['read', 'write', 'source_read'], 'archive_only': True,
             'trusted_user': False, 'token_sha256': hashlib.sha256(token.encode()).hexdigest()}
    active = [grant]
    model = NoModel()
    with tempfile.TemporaryDirectory() as directory:
        store = Store(directory)
        app = create_app(store, lambda: list(active), model, run_worker=False)
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'}
        with TestClient(app, base_url='http://127.0.0.1:5078') as client:
            def rpc(method, params):
                return client.post('/mcp/', headers=headers, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            def call(name, arguments):
                response = rpc('tools/call', {'name': name, 'arguments': arguments})
                assert response.status_code == 200
                return response.json()['result']
            def value(result):
                assert not result.get('isError', False)
                return result.get('structuredContent') or json.loads(result['content'][0]['text'])

            listing = rpc('tools/list', {}).json()['result']['tools']
            assert {'memory_import', 'memory_import_status', 'memory_context', 'memory_source_get'} <= {t['name'] for t in listing}
            capabilities = inspect_tools(listing)
            assert capabilities['progressive_window_ready']
            assert capabilities['capabilities']['memory_archive_source_get']['available']
            receipts = []
            # Simulates an unknown network outcome: discard first reply, then retry
            # exact payload after constructing a fresh local caller invocation.
            for part in parts:
                initial = value(call('memory_import', part))
                retry = value(call('memory_import', json.loads(encoded(part))))
                assert retry['duplicate'] and retry['id'] == initial['id'] and retry['job_id'] == initial['job_id']
                receipts.append(retry)
                status = value(call('memory_import_status', {'job_id': retry['job_id']}))
                assert status['state'] == 'archived' and 'index_status' in status
                raw = value(call('memory_source_get', {'source_id': retry['id'],
                    'message_id': part['messages'][0]['id'], 'max_chars': 1600}))
                assert raw['message']['role'] == part['messages'][0]['role']
                assert len(encoded(raw)) <= 1600
            old_ids = {r['id'] for r in receipts}
            for part in changed_parts:
                value(call('memory_import', part))
            for name, payload in (
                ('memory_import', dict(parts[0], scope='personal')),
                ('memory_import', dict(parts[0], processing_policy='extract')),
                ('memory_reextract', {'source_id': receipts[0]['id'], 'request_key': 'synthetic-reextract'}),
                ('memory_context', {'scope': 'personal', 'query': ''})):
                assert call(name, payload).get('isError') is True
            empty = value(call('memory_context', {'scope': scope, 'query': '', 'max_chars': 1600}))
            assert not empty['records']
            candidates = value(call('memory_candidate_search', {'scope': scope, 'query': '',
                'max_chars': 1600, 'offset': 0, 'window_limit': 8, 'retrieval_mode': 'lexical-v1'}))
            assert candidates['kind'] == 'candidate_reports' and candidates['facts_confirmed'] is False
            assert not candidates['records'] and len(encoded(candidates)) <= 1600
            assert call('memory_candidate_search', {'scope': 'personal', 'query': ''}).get('isError') is True
            for function, body in ((store.correct, {'statement': '合成更正', 'revision': 1}),
                                   (lambda p, rid, b: review(store, p, rid, b), {'state': 'verified', 'revision': 0})):
                try:
                    function(grant, 'synthetic-unavailable-record', body)
                except PermissionError:
                    pass
                else:
                    raise AssertionError('Third-party correction/confirmation must be denied')
            active[0] = dict(grant, actions=['read', 'write'])
            assert call('memory_source_get', {'source_id': receipts[0]['id'],
                'message_id': parts[0]['messages'][0]['id']}).get('isError') is True
            active[0] = dict(grant, actions=['read'])
            assert call('memory_import', parts[0]).get('isError') is True
            active.clear()
            assert rpc('tools/call', {'name': 'memory_context', 'arguments': {'scope': scope, 'query': ''}}).status_code == 401
        assert not store.process_one(model) and model.calls == 0
        with store.db() as db:
            source_ids = {r['id'] for r in db.execute('SELECT id FROM sources')}
            assert old_ids <= source_ids
            assert db.execute('SELECT count(*) FROM records').fetchone()[0] == 0
            assert db.execute('SELECT count(*) FROM extraction_runs').fetchone()[0] == 0
            assert {r[0] for r in db.execute('SELECT trusted_user FROM sources')} == {0}
        return {'synthetic': True, 'mode': 'in-process-mcp-self-test', 'checks_passed': [
            'schema-capabilities', 'empty-trusted-not-candidate-fallback', 'candidate-window-cross-scope-denied', 'lossless-unicode-packing', 'explicit-roles', 'retry-same-receipt',
            'new-version-retains-old', 'archive-vs-index-status', 'bounded-original-read',
            'cross-scope-denied', 'model-entry-denied', 'owner-correction-confirmation-denied',
            'trusted-context-empty', 'source-read-capability-denied', 'read-only-write-denied',
            'revocation-next-request'],
            'archive_parts': len(parts), 'sources_after_versions': len(source_ids),
            'records': 0, 'model_calls': model.calls, 'remote_network_calls': 0,
            'actual_client_verified': False, 'delete_propagation_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--self-test', action='store_true')
    modes.add_argument('--check-input', type=Path)
    modes.add_argument('--check-tools', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            result = run_self_test()
        elif args.check_tools:
            result = inspect_tools(json.loads(args.check_tools.read_text()))
        else:
            result = inspect_input(json.loads(args.check_input.read_text()))
    except Exception as exc:
        # Provider errors, validation bodies and local paths are not printed.
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps({'ok': True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())

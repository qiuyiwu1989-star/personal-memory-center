"""Synthetic MCP contract acceptance over real loopback HTTP; never uses live data.

Runs a disposable server on an OS-selected 127.0.0.1 port. No worker, remote
service, production configuration or model is used. External client compatibility
and production readiness are deliberately not asserted by this check.
"""
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_contract():
    import httpx
    import uvicorn
    from pipeline.memory_center.core import Store, encoded
    from pipeline.memory_center.service import create_app

    class NoModel:
        calls = 0
        configured = False
        def extract(self, *args, **kwargs):
            self.calls += 1
            raise AssertionError('Models are forbidden in the synthetic contract')

    checks = []
    def check(condition, name):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    token = 'synthetic-loopback-only-credential'
    scope = 'agent:synthetic-contract-inbox'
    active = [{'id': 'synthetic-client', 'owner': 'synthetic-owner',
               'scopes': [scope], 'actions': ['read', 'write', 'source_read'],
               'archive_only': True, 'trusted_user': False,
               'token_sha256': hashlib.sha256(token.encode()).hexdigest()}]
    model = NoModel()
    with tempfile.TemporaryDirectory() as directory:
        store = Store(directory)
        from pipeline.memory_center.source_lifecycle import setup as setup_withdrawal
        setup_withdrawal(store)  # Explicitly migrate only the disposable synthetic DB.
        app = create_app(store, lambda: list(active), model, run_worker=False)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='critical', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            check(server.started, 'loopback-server-started')
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10,
                              trust_env=False, headers={'Authorization': 'Bearer ' + token,
                                  'Accept': 'application/json, text/event-stream'}) as client:
                sequence = 0
                def rpc(method, params):
                    nonlocal sequence
                    sequence += 1
                    return client.post('/mcp/', json={'jsonrpc': '2.0', 'id': sequence,
                        'method': method, 'params': params})
                def call(name, arguments):
                    response = rpc('tools/call', {'name': name, 'arguments': arguments})
                    check(response.status_code == 200, 'tool-http-200')
                    return response.json()['result']
                def value(result):
                    check(not result.get('isError', False), 'tool-success')
                    return result.get('structuredContent') or json.loads(result['content'][0]['text'])
                def deny(name, arguments, label):
                    result = call(name, arguments)
                    check(result.get('isError') is True, label)

                init = rpc('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                    'clientInfo': {'name': 'synthetic-http-contract', 'version': '1'}})
                check(init.status_code == 200 and 'result' in init.json(), 'initialize')
                check('mcp-session-id' not in init.headers, 'stateless-no-session-header')
                client.headers['MCP-Protocol-Version'] = init.json()['result']['protocolVersion']
                notification = client.post('/mcp/', json={'jsonrpc': '2.0',
                    'method': 'notifications/initialized'})
                check(notification.status_code == 202, 'initialized-notification')
                tools = rpc('tools/list', {}).json()['result']['tools']
                schemas = {t['name']: t['inputSchema'] for t in tools}
                fields = schemas['memory_import']['properties']
                check('source_metadata' in fields and 'parent_source_key' not in fields,
                      'parent-key-is-metadata-not-top-level')
                check({'memory_import', 'memory_import_status', 'memory_context',
                       'memory_source_get', 'memory_reextract'} <= set(schemas), 'tools-list')

                body = {'source_key': 'synthetic://doc#v1', 'scope': scope,
                    'source_type': 'document', 'source_metadata': {
                        'original_ref': 'synthetic://original', 'original_date': '2026-10-05',
                        'author': 'synthetic-author', 'locator': 'page:1', 'parser_version': 'synthetic-v1',
                        'parent_source_key': 'synthetic://doc', 'visibility': 'visible_only'},
                    'messages': [{'id': 'u1', 'role': 'user', 'text': '合成本人原话🙂'},
                                 {'id': 'a1', 'role': 'assistant', 'text': '合成建议，未确认。'},
                                 {'id': 'e1', 'role': 'external', 'text': '合成第三方观点。'}]}
                receipt = value(call('memory_import', body))
                check(set(receipt) == {'id', 'job_id', 'duplicate'} and not receipt['duplicate'],
                      'archive-receipt-id-and-job-id')
                retry = value(call('memory_import', json.loads(json.dumps(body))))
                check(retry['duplicate'] and retry['id'] == receipt['id']
                      and retry['job_id'] == receipt['job_id'], 'exact-retry-idempotent')
                state = value(call('memory_import_status', {'job_id': receipt['job_id']}))
                check(state['state'] == 'archived' and state['usage'] is None, 'archive-no-model-usage')
                for message in body['messages']:
                    raw = value(call('memory_source_get', {'source_id': receipt['id'],
                        'message_id': message['id'], 'max_chars': 1600}))
                    check(raw['message']['role'] == message['role'], 'roles-preserved-' + message['role'])
                empty = value(call('memory_context', {'scope': scope, 'query': '', 'max_chars': 1600}))
                check(empty['records'] == [] and empty['total'] == 0
                      and 'context_revision' in empty, 'archived-is-not-verified-context')
                changed = json.loads(json.dumps(body))
                changed['messages'][0]['text'] += '合成版本更正。'
                newer = value(call('memory_import', changed))
                check(newer['id'] != receipt['id'], 'same-key-changed-digest-new-source')

                for name in ('memory_source_withdrawal_preview', 'memory_source_withdraw'):
                    deny(name, {'source_id': receipt['id'], 'scope': scope},
                         'agent-source-withdrawal-denied')
                writer = active[0]
                active[0] = dict(writer, actions=['read'])
                deny('memory_import', body, 'read-only-import-denied')
                deny('memory_source_withdraw', {'source_id': receipt['id'], 'scope': scope},
                     'read-only-source-withdrawal-denied')
                active[0] = writer

                # Synthetic verified fixture: seed a candidate directly, then use
                # the owner's governance API. This is not model extraction.
                from pipeline.memory_center.governance import review
                rid = 'synthetic-verified-record'
                with store.db() as db:
                    db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (rid, 'synthetic-owner', scope, 'preferences', 'preference', 'user',
                         body['messages'][0]['text'], 'source_reported', receipt['id'], 'u1',
                         body['messages'][0]['text'], 'active', 1, None, time.time()))
                owner_token = 'synthetic-owner-loopback-credential'
                owner = dict(active[0], id='synthetic-owner-client', trusted_user=True,
                    token_sha256=hashlib.sha256(owner_token.encode()).hexdigest())
                active.append(owner)
                review(store, owner, rid, {'revision': 0, 'state': 'verified',
                    'holder': 'owner:synthetic-owner', 'subject_id': 'owner:synthetic-owner',
                    'as_of': '2000-01-01', 'priority': 'P2'})
                before = value(call('memory_context', {'scope': scope, 'query': '', 'max_chars': 4000}))
                check(any(row['id'] == rid for row in before['records']), 'synthetic-verified-visible-before-withdrawal')
                client.headers['Authorization'] = 'Bearer ' + owner_token
                impact = value(call('memory_source_withdrawal_preview', {'source_id': receipt['id'], 'scope': scope}))
                check(impact['withdrawal_supported'] and impact['counts']['records'] == 1,
                      'owner-source-impact-preview')
                withdrawn = value(call('memory_source_withdraw', {'source_id': receipt['id'], 'scope': scope,
                    'reason': 'synthetic withdrawal acceptance'}))
                again = value(call('memory_source_withdraw', {'source_id': receipt['id'], 'scope': scope}))
                check(withdrawn['state'] == 'withdrawn' and withdrawn['archive_retained']
                      and again['duplicate'] and again['withdrawn_at'] == withdrawn['withdrawn_at'],
                      'owner-source-withdrawal-idempotent')
                client.headers['Authorization'] = 'Bearer ' + token
                after = value(call('memory_context', {'scope': scope, 'query': '', 'max_chars': 4000}))
                check(not after['records'] and after['context_revision'] != before['context_revision'],
                      'withdrawal-hides-context-and-changes-revision')
                deny('memory_source_get', {'source_id': receipt['id'], 'message_id': 'u1'},
                     'withdrawn-original-hidden-from-agent')
                with store.db() as db:
                    check(db.execute('SELECT count(*) FROM records WHERE id=?', (rid,)).fetchone()[0] == 1
                          and db.execute('SELECT count(*) FROM sources WHERE id=?', (receipt['id'],)).fetchone()[0] == 1,
                          'withdrawal-retains-audit-record-and-archive')

                for bad_scope in ('personal', 'agent:synthetic-other-inbox'):
                    deny('memory_import', dict(body, scope=bad_scope), 'cross-scope-write-denied')
                    deny('memory_context', {'scope': bad_scope, 'query': ''}, 'cross-scope-read-denied')
                deny('memory_import', dict(body, processing_policy='extract'), 'extract-denied')
                deny('memory_reextract', {'source_id': receipt['id'], 'request_key': 'synthetic-run'},
                     'reextract-denied')
                deny('memory_import', dict(body, source_metadata={'unsupported': 'synthetic'}),
                     'unknown-metadata-denied')
                deny('memory_import', dict(body, source_metadata={'visibility': 'unrestricted'}),
                     'invalid-visibility-denied')
                deny('memory_import', dict(body, messages=[dict(body['messages'][0], role='system')]),
                     'instruction-role-denied')
                deny('memory_import', dict(body, messages=body['messages'] * 34), 'over-100-messages-denied')
                deny('memory_import', dict(body, source_key='🙂' * 301), 'source-key-over-300-denied')
                unicode_key = value(call('memory_import', dict(body, source_key='🙂' * 300)))
                check(bool(unicode_key['id']), 'source-key-300-codepoints-accepted')
                boundary = [{'id': 'boundary', 'role': 'external', 'text': '🙂'}]
                overhead = len(encoded(boundary)) - 1
                boundary[0]['text'] = '🙂' * (24000 - overhead)
                check(len(encoded(boundary)) == 24000, 'normalized-json-codepoint-count')
                value(call('memory_import', dict(body, source_key='synthetic://boundary', messages=boundary)))
                too_long = [dict(boundary[0], text=boundary[0]['text'] + '🙂')]
                deny('memory_import', dict(body, source_key='synthetic://over-boundary', messages=too_long),
                     '24001-normalized-chars-denied')
                active[0] = dict(active[0], actions=['read', 'write'])
                deny('memory_source_get', {'source_id': receipt['id'], 'message_id': 'u1'},
                     'source-read-action-required')
                active.clear()
                check(rpc('tools/list', {}).status_code == 401, 'revocation-next-request-401')
            check(not store.process_one(model) and model.calls == 0, 'no-model-calls')
            with store.db() as db:
                check(db.execute('SELECT count(*) FROM records').fetchone()[0] == 1,
                      'no-memory-auto-promotion')
                check(db.execute('SELECT count(*) FROM extraction_runs').fetchone()[0] == 0,
                      'no-extraction-runs')
            return {'ok': True, 'synthetic': True, 'transport': 'real-loopback-http',
                    'checks_passed': sorted(set(checks)), 'model_calls': model.calls,
                    'remote_network_calls': 0, 'external_client_verified': False,
                    'production_verified': False, 'source_withdrawal_verified': True,
                    'synthetic_fixture_records': 1}
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
            if thread.is_alive():
                raise RuntimeError('Synthetic server did not stop')


def main():
    try:
        report = run_contract()
    except Exception as exc:
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__}))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

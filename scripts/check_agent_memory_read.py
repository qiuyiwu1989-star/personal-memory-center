#!/usr/bin/env python3
"""Read-only runtime probe. Credentials are environment-only; stdout contains no memory text."""
import hashlib
import json
import os
import sys
from urllib.parse import urlsplit
import httpx


def connection(environment):
    endpoint = environment.get('MEMORY_MCP_URL', '')
    parts = urlsplit(endpoint)
    if (parts.scheme not in ('https', 'http') or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or (parts.scheme == 'http' and parts.hostname not in ('127.0.0.1', 'localhost', '::1'))):
        raise ValueError('MCP URL must be HTTPS (or loopback HTTP), without credentials, query, or fragment')
    tokens = [environment.get(key, '') for key in ('MEMORY_READER_TOKEN_A', 'MEMORY_READER_TOKEN_B')]
    if any(not token or len(token)>480 or any(c.isspace() for c in token) for token in tokens):
        raise ValueError('Provide two valid environment-only reader credentials')
    if tokens[0] == tokens[1]: raise ValueError('Reader credentials must be independent')
    scope = environment.get('MEMORY_READ_SCOPE', 'personal')
    if not scope or len(scope)>160: raise ValueError('Invalid scope')
    return endpoint, tokens, scope


SUPPORTED_PROTOCOLS = ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25')
RESPONSE_LIMIT = 200000


def request_json(client, endpoint, headers, payload, notification=False):
    """Bound decoded transfer before parsing; JSON-only Streamable HTTP, never SSE."""
    with client.stream('POST', endpoint, headers=headers, json=payload) as reply:
        allowed = (200, 202, 204) if notification else (200,)
        if reply.status_code not in allowed:
            raise ValueError('MCP rejected request')
        mime = reply.headers.get('content-type', '').split(';')[0].strip().lower()
        if mime == 'text/event-stream':
            raise ValueError('SSE unsupported by this JSON-only probe')
        if not notification and mime != 'application/json':
            raise ValueError('Expected MCP JSON response')
        content = bytearray()
        for chunk in reply.iter_bytes(chunk_size=4096):
            if len(content)+len(chunk)>RESPONSE_LIMIT:
                raise ValueError('Response exceeded probe budget')
            content.extend(chunk)
        session = reply.headers.get('mcp-session-id')
        if session and (len(session)>1024 or any(c.isspace() for c in session)):
            raise ValueError('Invalid MCP session header')
        if notification and not content: return None, session
        if mime != 'application/json': raise ValueError('Expected MCP JSON response')
        data = json.loads(content)
        if not isinstance(data, dict) or data.get('jsonrpc') != '2.0' or 'error' in data:
            raise ValueError('Invalid MCP JSON-RPC response')
        if not notification and data.get('id') != payload.get('id'):
            raise ValueError('MCP response id mismatch')
        return data, session


def probe(endpoint, tokens, scope):
    fingerprints = []
    summary = None
    readers = []
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        for token in tokens:
            headers = {'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
            initialized, session = request_json(client, endpoint, headers,
                {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':SUPPORTED_PROTOCOLS[-1],
                 'capabilities':{},'clientInfo':{'name':'memory-read-acceptance','version':'1.1'}}})
            version = initialized.get('result', {}).get('protocolVersion')
            if version not in SUPPORTED_PROTOCOLS: raise ValueError('Unsupported negotiated protocol')
            headers['MCP-Protocol-Version'] = version
            if session: headers['Mcp-Session-Id'] = session
            request_json(client, endpoint, headers, {'jsonrpc':'2.0','method':'notifications/initialized'}, notification=True)
            readers.append((headers, version))
        for index in (0, 1, 0, 1):
            headers, version = readers[index]
            reply, session = request_json(client, endpoint, headers,
                {'jsonrpc':'2.0','id':2+len(fingerprints),'method':'tools/call','params':{'name':'memory_context','arguments':{'scope':scope,'query':'','max_chars':6000}}})
            if session and session != headers.get('Mcp-Session-Id'):
                raise ValueError('MCP session changed unexpectedly')
            result = reply.get('result', {})
            if result.get('isError'): raise ValueError('MCP tool rejected request')
            data = result.get('structuredContent') or json.loads(result['content'][0]['text'])
            if not isinstance(data.get('records'),list) or not data.get('context_revision'):
                raise ValueError('Missing context records or revision contract')
            records = data['records']
            if any(not r.get('source_id') or not r.get('message_id') or not r.get('revision') for r in records):
                raise ValueError('Context lacks provenance or record version')
            canonical = json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            fingerprints.append(hashlib.sha256(canonical).hexdigest())
            summary = {'records_in_bounded_response':len(records),'context_revision':data['context_revision'],
                       'empty_is_valid':not records,'model_calls':0,'writes':0}
    consistent = len(set(fingerprints))==1
    return dict(summary, independent_readers=2, repeated_reads=4, initialized_readers=2,
                negotiated_protocols=[r[1] for r in readers], consistent=consistent,
                result='pass' if consistent else 'inconclusive_concurrent_change_or_visibility',
                response_sha256=fingerprints[0] if consistent else None)


def main():
    try:
        result=probe(*connection(os.environ))
    except Exception as error:
        # Never echo response bodies, exception strings, URL, headers, or environment.
        print(json.dumps({'result':'failed','error_type':type(error).__name__,'writes':0,'model_calls':0}))
        return 1
    print(json.dumps(result,ensure_ascii=False));return 0 if result['consistent'] else 2

if __name__ == '__main__': sys.exit(main())

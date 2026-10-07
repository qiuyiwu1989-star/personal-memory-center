#!/usr/bin/env python3
"""Single-reader MCP smoke check. No writes, models, memory text or secret output."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_agent_memory_read import request_json, SUPPORTED_PROTOCOLS


def connection(environment):
    endpoint = environment.get('MEMORY_MCP_URL', '')
    parts = urlsplit(endpoint)
    if (parts.scheme not in ('https', 'http') or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment
            or (parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('Invalid endpoint')
    token = environment.get('MEMORY_AGENT_TOKEN', '')
    if not token or len(token) > 480 or any(c.isspace() for c in token):
        raise ValueError('Invalid environment credential')
    scope = environment.get('MEMORY_READ_SCOPE', 'personal')
    if not scope.strip() or len(scope) > 160:
        raise ValueError('Invalid scope')
    return endpoint, token, scope


def probe(endpoint, token, scope, candidate_query=None):
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream'}
        result, session = request_json(client, endpoint, headers, {
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': SUPPORTED_PROTOCOLS[-1], 'capabilities': {},
                'clientInfo': {'name': 'memory-single-reader-check', 'version': '1.0'}}})
        version = result.get('result', {}).get('protocolVersion')
        if version not in SUPPORTED_PROTOCOLS:
            raise ValueError('Unsupported protocol')
        headers['MCP-Protocol-Version'] = version
        if session:
            headers['Mcp-Session-Id'] = session
        request_json(client, endpoint, headers, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, notification=True)
        listing, _ = request_json(client, endpoint, headers, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        tools = {tool['name']: tool for tool in listing.get('result', {}).get('tools', [])}
        name = 'memory_candidate_search' if candidate_query is not None else 'memory_context'
        if name not in tools:
            raise ValueError('Required tool unavailable')
        args = {'scope': scope, 'query': candidate_query or '', 'max_chars': 4000 if candidate_query is not None else 1600}
        if candidate_query is not None:
            if not candidate_query.strip():
                raise ValueError('Candidate query must be explicit and nonblank')
            args.update(offset=0, window_limit=32, retrieval_mode='lexical-v1')
        reply, _ = request_json(client, endpoint, headers, {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}})
        result = reply.get('result', {})
        if result.get('isError'):
            raise ValueError('Tool denied or rejected request')
        data = result.get('structuredContent') or json.loads(result['content'][0]['text'])
        if not isinstance(data.get('records'), list):
            raise ValueError('Missing bounded records')
        if candidate_query is None and not data.get('context_revision'):
            raise ValueError('Missing context revision')
        if candidate_query is not None and (data.get('kind') != 'candidate_reports' or data.get('facts_confirmed') is not False):
            raise ValueError('Missing candidate trust boundary')
        return {'result': 'pass', 'read_kind': 'candidate_evidence' if candidate_query is not None else 'verified_context',
                'records_in_bounded_response': len(data['records']), 'empty_is_valid': not data['records'],
                'truncated': data.get('truncated', False), 'negotiated_protocol': version,
                'model_calls': 0, 'writes': 0, 'instance_acceptance': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-query', help='Explicit evidence investigation; never automatic fallback')
    args = parser.parse_args()
    try:
        result = probe(*connection(os.environ), candidate_query=args.candidate_query)
    except Exception as error:
        print(json.dumps({'result': 'failed', 'error_type': type(error).__name__, 'model_calls': 0, 'writes': 0}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

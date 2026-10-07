"""Small authenticated feature negotiation; no implicit migration or model use."""
from .core import permit


def describe(store, principal, scope):
    permit(principal, scope, 'read')
    from .candidate_intake import available
    with store.db() as db:
        candidate_ready = available(store, db)
    actions = set(principal.get('actions', []))
    owner = principal.get('trusted_user') is True
    isolated = (principal.get('scopes') == [scope] and isinstance(scope, str)
                and scope.startswith('agent:') and scope.endswith('-inbox')
                and len(scope) > len('agent:-inbox'))
    can_submit = ({'read', 'source_read', 'write'} <= actions
                  and (owner or ('candidate_write' in actions and isolated)))
    return {
        'contract_version': 'memory-interfaces-v1', 'scope': scope,
        'candidate_intake': {
            'available': candidate_ready, 'authorized': bool(can_submit),
            'migration_required': None if candidate_ready else '010_candidate_intake',
            'max_claims': 20, 'max_quote_chars': 2000, 'max_statement_chars': 1200,
            'offset_unit': 'unicode_codepoint', 'end_exclusive': True,
            'same_principal_source_required': not owner, 'facts_confirmed': False,
        },
        'context': {'mcp_tool': 'memory_context', 'rest_method': 'GET', 'rest_path': '/task-context',
                    'verified_only': True, 'default_max_chars': 1600, 'max_chars': 16000},
        'legacy_context': {'rest_method': 'POST', 'rest_path': '/context', 'verified_only': False},
        'changes': {'available': True, 'coverage': 'current_record_metadata_only',
                    'not_event_delta': True, 'default_max_chars': 4000,
                    'refresh_after_seconds': 300},
        'archive': {'authorized': 'write' in actions, 'mcp_default_policy': 'archive',
                    'rest_default_policy': 'archive' if principal.get('archive_only', False) is not False else 'extract',
                    'explicit_policy_recommended': 'archive',
                    'max_messages': 100, 'max_serialized_chars': 24000},
        'read_model_calls': 0,
    }

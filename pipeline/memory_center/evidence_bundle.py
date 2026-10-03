"""Read-only task evidence groups under one serialized JSON budget."""
from .core import Invalid, encoded, permit
from . import governance, reading, source_discovery


def bundle(store, principal, scope, query, max_chars=6000, retrieval_mode='lexical-v1'):
    """Compose distinct trust levels; never promote candidates or widen access.

    The whole response, including metadata and JSON escaping, fits max_chars.
    Candidate counts never take priority over original provenance. Preserve
    whole trusted records and at least one original locator when they fit.
    Explicit source-discovery indexing remains a separate write operation.
    """
    if type(max_chars) is not int or not 1500 <= max_chars <= 16000:
        raise Invalid('证据包预算需为 1500–16000 字符')
    if not isinstance(query, str) or len(query) > 500:
        raise Invalid('证据包查询上限 500 字符')
    permit(principal, scope, 'read')
    trusted = governance.context(store, principal, scope, query, 16000, retrieval_mode)
    trusted.update(kind='trusted_context', status='available')
    snapshot = store.snapshot(principal, scope, query, limit=1000000,
                              governance_filter='candidate', retrieval_mode=retrieval_mode, include_jobs=False)
    reports = reading.search_page(snapshot, max_chars=16000)
    reports.update(kind='candidate_reports', status='available', facts_confirmed=False)
    try:
        permit(principal, scope, 'source_read')
    except PermissionError:
        original = {'status': 'unavailable', 'reason': 'source_read_not_authorized',
                    'kind': 'source_evidence', 'facts_confirmed': False}
    else:
        try:
            original = source_discovery.search(store, principal, scope, query, max_chars=16000)
            original['status'] = 'available'
        except Invalid as exc:
            # An individually oversized source locator cannot be returned at
            # any supported budget. Never truncate it into an unusable locator.
            if str(exc) != '原文元信息超过预算，请提高 max_chars':
                raise
            original = {'status': 'unavailable', 'reason': 'source_metadata_exceeds_budget',
                        'kind': 'source_evidence', 'facts_confirmed': False}
    result = {
        'kind': 'task_evidence_bundle', 'policy': 'preserve-provenance-v2',
        'retrieval': retrieval_mode,
        'trusted_context': trusted, 'source_reports': reports, 'original_evidence': original,
        'unresolved_questions': [
            '候选与原文仅作为证据，不能替代已核实上下文。',
            '缺失结果不证明不存在；需检查授权范围、索引覆盖与检索词。',
            '观点归属、成立时间及当前有效性仍需按来源核实。',
        ],
        'truncated': False,
    }
    def remove(group,field):
        group[field].pop();group['truncated']=True
        if field=='results':group['next_offset']=group['offset']+len(group[field]) if group['total'] else None
    # Keep all locators intact; candidate reports are optional under pressure.
    # Once a single evidence item remains, reduce trusted item count before it.
    # A budget that cannot hold even one complete locator must say so explicitly.
    while len(encoded(result))>max_chars:
        if reports.get('records'):remove(reports,'records')
        elif len(original.get('results',[]))>1:remove(original,'results')
        elif len(trusted.get('records',[]))>1:remove(trusted,'records')
        elif original.get('results'):
            remove(original,'results')
            original['omitted_reason']='complete_evidence_item_exceeds_remaining_budget'
        elif trusted.get('records'):remove(trusted,'records')
        else:break
    result['truncated'] = any(g.get('truncated', False) or g.get('next_offset') is not None
                              for g in (trusted, reports, original))
    if len(encoded(result)) > max_chars:
        raise Invalid('证据包元信息超过预算')
    return result

"""Explicit diagnostic isolation; never an ingestible extraction plan.

This module invokes no model or persistence. Passing mechanical guards does not
establish entailment, ownership, current validity or approval.
"""
import copy
import hashlib
import json

from .core import Invalid, validate_plan
from .extraction_input import resolve_plan

ISOLATION_VERSION = 'candidate-isolation-diagnostic-v1'


def _structure(plan):
    if not isinstance(plan, dict) or not isinstance(plan.get('claims'), list) or len(plan['claims']) > 12:
        raise Invalid('隔离诊断：非法 claims 结构，整批拒绝')
    for claim in plan['claims']:
        if not isinstance(claim, dict):
            raise Invalid('隔离诊断：记忆项必须为对象，整批拒绝')
        for field, maximum in [('statement', 1200), ('subject', 160), ('evidence_id', 100)]:
            if not isinstance(claim.get(field), str) or not 1 <= len(claim[field]) <= maximum:
                raise Invalid('隔离诊断：字段类型或长度非法，整批拒绝')
        if claim.get('topic') not in ('profile', 'preferences', 'people', 'areas', 'projects', 'topics'):
            raise Invalid('隔离诊断：主题分类非法，整批拒绝')
        if claim.get('kind') not in ('identity', 'preference', 'relationship', 'decision', 'plan', 'event', 'claim', 'suggestion'):
            raise Invalid('隔离诊断：记忆类型非法，整批拒绝')
        for field in ('message_id', 'quote'):
            if field in claim and not isinstance(claim[field], str):
                raise Invalid('隔离诊断：独立证据字段类型非法，整批拒绝')


def diagnose_candidates(plan, spans, source, *, version, opt_in=False):
    """Return private, source-complete review data with original 0-based ordinals.

    Unknown evidence and contradictory locators are isolated; malformed JSON
    structure and broken server/source span bindings reject the entire batch.
    Even guard-passed items cannot be submitted as an extraction plan. Aggregate
    guard failures mark all remaining items for review, never discard siblings
    to evade a batch limit. Caller must store this receipt privately if desired.
    """
    if opt_in is not True:
        raise Invalid('候选隔离仅允许显式启用的诊断调用')
    if version != '2026-10-03.21':
        raise Invalid('隔离诊断：方法版本未验收，整批拒绝')
    _structure(plan)
    if not isinstance(source, dict) or not isinstance(source.get('payload'), str) or not isinstance(spans, dict):
        raise Invalid('隔离诊断：完整来源或服务端片段缺失，整批拒绝')
    try:
        messages = json.loads(source['payload'])
    except (ValueError, TypeError):
        raise Invalid('隔离诊断：来源 JSON 非法，整批拒绝') from None
    if not isinstance(messages, list) or not 1 <= len(messages) <= 100 or any(not isinstance(m, dict) or not isinstance(m.get('id'), str) or not 1 <= len(m['id']) <= 100 or not isinstance(m.get('text'), str) or not m['text'].strip() or m.get('role') not in ('user', 'assistant', 'external') for m in messages):
        raise Invalid('隔离诊断：来源消息结构非法，整批拒绝')
    by_id = {m['id']: m for m in messages}
    if len(by_id) != len(messages):
        raise Invalid('隔离诊断：重复来源消息 ID，整批拒绝')
    for sid, span in spans.items():
        if not isinstance(sid, str) or not isinstance(span, dict):
            raise Invalid('隔离诊断：服务端片段结构非法，整批拒绝')
        message_id = span.get('message_id')
        message = by_id.get(message_id) if isinstance(message_id, str) else None
        start, end = span.get('start'), span.get('end')
        if (message is None or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(message['text']) or span.get('quote') != message['text'][start:end]):
            raise Invalid('隔离诊断：服务端片段未逐字绑定完整来源，整批拒绝')
        for field, expected in (('_source_title', message.get('source_title')), ('_created_at', message.get('created_at')), ('_source_type', source.get('source_type'))):
            if field in span and span[field] != expected:
                raise Invalid('隔离诊断：服务端片段元数据与完整来源冲突，整批拒绝')
    checked_source = dict(source, processing_method_version=version)
    # An absent trusted-user declaration is never upgraded by the diagnostic.
    checked_source.setdefault('trusted_user', False)
    if type(checked_source['trusted_user']) is not bool or checked_source.get('source_type') not in ('conversation', 'imported_summary', 'document'):
        raise Invalid('隔离诊断：来源类型或信任声明非法，整批拒绝')
    items = []
    passed = []
    for ordinal, claim in enumerate(plan['claims']):
        span = spans.get(claim['evidence_id'])
        item = {'ordinal': ordinal, 'original_candidate': copy.deepcopy(claim),
                'locator': ({'message_id': span['message_id'], 'start': span['start'], 'end': span['end'], 'evidence_id': claim['evidence_id']} if span else None),
                'selected_span': copy.deepcopy(span),
                'state': 'quarantined', 'reasons': []}
        stage = 'source_span_contract'
        try:
            resolved = resolve_plan({'claims': [claim]}, spans, version=version)
            stage = 'candidate_contract'
            candidate = validate_plan(resolved, checked_source)[0]
        except Invalid as exc:
            item['reasons'].append({'stage': stage, 'code': 'guard_rejected', 'explanation': str(exc)})
        else:
            item['state'] = 'guard_passed_requires_review'
            item['resolved_candidate'] = candidate
            passed.append(candidate)
        items.append(item)
    batch_reasons = []
    try:
        validate_plan({'claims': passed}, checked_source)
    except Invalid as exc:
        reason = {'stage': 'aggregate_contract', 'code': 'batch_guard_rejected', 'explanation': str(exc)}
        batch_reasons.append(reason)
        for item in items:
            if item['state'] == 'guard_passed_requires_review':
                item['state'] = 'batch_review_required'
                item['reasons'].append(copy.deepcopy(reason))
    return {'diagnostic_version': ISOLATION_VERSION, 'method_version': version,
            'diagnostic_only': True, 'adoption_allowed': False,
            'source_payload_sha256': hashlib.sha256(source['payload'].encode('utf-8')).hexdigest(),
            'source_context': copy.deepcopy(messages),
            'source_binding': {'source_type': source['source_type'], 'trusted_user': checked_source['trusted_user']},
            'original_count': len(plan['claims']), 'diagnostic_items': items,
            'batch_reasons': batch_reasons}

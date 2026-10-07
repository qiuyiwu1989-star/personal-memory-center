"""Experimental complete-source routing projected onto verified archive segments.

Original roles are declarations, not verified identity. A complete span crossing
an archive boundary is never silently clipped into an independent claim.
"""
import copy
import hashlib
from .core import Invalid
from .extraction_input import prepare_request
from .long_source_plan import verify_long_source_plan
from .modality import CONDITION

VERSION = 'complete-source-context-v1'
METHOD = '2026-10-04.22'


def inherit_source_context(envelope, plan, *, version):
    if version != METHOD:
        raise Invalid('完整来源继承仅支持显式实验方法')
    if not isinstance(envelope, dict):
        raise Invalid('完整来源信封无效')
    messages = envelope.get('messages')
    verify_long_source_plan(plan, messages)
    for key in ('source_key', 'scope', 'source_type', 'source_metadata'):
        expected = envelope.get(key, 'document' if key == 'source_type' else None)
        if plan[key] != expected:
            raise Invalid('完整来源信封与归档计划不匹配')
    request, spans, routes = prepare_request(plan['source_type'], messages,
        version=version, source_metadata=plan['source_metadata'])
    complete = {message['id']: message for message in request['messages']}
    result = []
    projected_ids = set()
    for segment in plan['segments']:
        original = messages[segment['message_index']]
        prepared = complete[original['id']]
        contained, crossing = [], []
        for sid, span in spans.items():
            if span['message_id'] != original['id']:
                continue
            start, end = span['start'], span['end']
            if not 0 <= start < end <= len(original['text']) or original['text'][start:end] != span['quote']:
                raise Invalid('完整来源证据定位不匹配')
            if end <= segment['start'] or start >= segment['end']:
                continue
            locator = {'message_id': original['id'], 'message_index': segment['message_index'],
                'start': start, 'end': end,
                'global_start': segment['global_start'] + start - segment['start'],
                'global_end': segment['global_start'] + end - segment['start'],
                'offset_unit': 'unicode_codepoint', 'source_sha256': plan['source_canonical_sha256']}
            if start < segment['start'] or end > segment['end']:
                crossing.append({'evidence_id': sid, 'original_locator': locator,
                    'reason': 'whole_evidence_crosses_archive_boundary'})
                continue
            item = {'evidence_id': sid, 'quote': span['quote'], 'original_locator': locator,
                'segment_start': start - segment['start'], 'segment_end': end - segment['start']}
            if '_modality' in span:
                item['modality_hint'] = span['_modality']
            contained.append(item)
            projected_ids.add(sid)
        blockers = list(segment['review_reasons'])
        if crossing:
            blockers.append('whole_evidence_crosses_archive_boundary')
        if prepared['route'] in ('reference_document', 'mixed_reference_document', 'assistant_reference'):
            blockers.append('complete_source_reference_route_inherited')
        neighbor_indices = segment['context_navigation']['neighbor_message_indices']
        if any(CONDITION.search(messages[index]['text']) for index in neighbor_indices
               if index != segment['message_index']):
            blockers.append('neighbor_condition_requires_semantic_review')
        navigation = [{'message_index': index, 'message_id': messages[index]['id'],
            'declared_role': messages[index]['role'],
            'text_sha256': hashlib.sha256(messages[index]['text'].encode()).hexdigest(),
            'purpose': 'original_navigation_not_evidence'} for index in neighbor_indices]
        result.append({'segment_id': segment['segment_id'], 'complete_source_route': routes[original['id']],
            'reference_reason': prepared['reference_reason'],
            'declared_author_context': {key: copy.deepcopy(original[key]) for key in
                ('role', 'source_title', 'created_at') if key in original},
            'author_identity_verified': False, 'context_message_locators': navigation,
            'original_message_id': original['id'], 'evidence_spans': contained,
            'boundary_review_spans': crossing, 'review_reasons': blockers,
            'evidence_characters': sum(len(item['quote']) for item in contained),
            'automatic_extraction_authorized': False})
    return {'context_version': VERSION, 'method_version': version,
        'source_canonical_sha256': plan['source_canonical_sha256'],
        'source_visibility': copy.deepcopy(request.get('source_visibility')),
        'segments': result,
        'complete_source_evidence_characters': sum(len(span['quote']) for span in spans.values()),
        'inherited_evidence_characters': sum(item['evidence_characters'] for item in result),
        'boundary_blocked_evidence_characters': sum(len(span['quote']) for sid, span in spans.items() if sid not in projected_ids),
        'purpose': 'offline_review_projection_not_model_request',
        'quality_approved': False, 'automatic_scope_release': False,
        'model_calls': 0, 'contains_private_source_text': True}

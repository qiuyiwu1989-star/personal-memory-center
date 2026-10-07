"""Private, source-complete review packets; never a semantic approval gate.

Packets contain original text. They are not MCP responses or public reports.
No slicing decision, identity inference, model call or store mutation occurs.
"""
import hashlib
import copy
import json

from .core import Invalid
from .extraction_input import prepare_request
from .modality import CONDITION
from .scope_diagnostics import scope_observations


def prepare_scope_review(source_type, messages, *, version, source_metadata=None):
    if source_type not in ('conversation', 'imported_summary', 'document'):
        raise Invalid('范围复核来源类型无效')
    if not isinstance(messages, list) or len(messages) > 1000:
        raise Invalid('范围复核消息列表无效')
    seen = set()
    for message in messages:
        if (not isinstance(message, dict) or not isinstance(message.get('id'), str)
                or not message['id'] or message['id'] in seen
                or message.get('role') not in ('user', 'assistant', 'external')
                or not isinstance(message.get('text'), str)
                or len(message['text']) > 20000):
            raise Invalid('范围复核消息结构无效或超出正文上限')
        seen.add(message['id'])
    request, spans, routes = prepare_request(source_type, messages, version=version,
                                            source_metadata=source_metadata)
    checks = []
    source_characters = evidence_characters = 0
    zero_evidence_messages = []
    for position, message in enumerate(messages):
        text = message['text']
        related = [(sid, item) for sid, item in spans.items()
                   if item['message_id'] == message['id']]
        source_characters += len(text)
        # Binding is checked even for messages without conditional markers.
        # Coverage measures visible evidence only; it is never a quality score.
        for _, item in related:
            if (type(item['start']) is not int or type(item['end']) is not int
                    or not 0 <= item['start'] < item['end'] <= len(text)
                    or text[item['start']:item['end']] != item['quote']):
                raise Invalid('范围复核证据定位不匹配')
        intervals = sorted((item['start'], item['end']) for _, item in related)
        covered = 0
        previous_end = 0
        for begin, end in intervals:
            covered += max(0, end - max(begin, previous_end))
            previous_end = max(previous_end, end)
        evidence_characters += covered
        if text.strip() and not related:
            zero_evidence_messages.append(message['id'])
        reasons = []
        if text.strip() and not related:
            reasons.append('source_without_extractable_evidence_not_quality_pass')
        elif covered < len(text):
            reasons.append('source_not_fully_covered_by_evidence')
        neighbors = messages[max(0, position - 1):position] + messages[position + 1:position + 2]
        if version == '2026-10-04.22' and any(CONDITION.search(other['text']) for other in neighbors):
            reasons.append('neighbor_condition_requires_semantic_review')
        if CONDITION.search(text):
            reasons.append('condition_scope_requires_semantic_review')
            if any(CONDITION.search(text) and not CONDITION.search(item['quote'])
                   for _, item in related):
                reasons.append('selected_piece_not_complete_condition_context')
        if any(item['start'] > 0 or item['end'] < len(text) for _, item in related):
            reasons.append('piece_not_complete_message')
        if not reasons:
            continue
        anchors = []
        for sid, item in related:
            if text[item['start']:item['end']] != item['quote']:
                raise Invalid('范围复核证据定位不匹配')
            anchors.append({'evidence_id': sid, 'start': item['start'],
                            'end': item['end'], 'quote': item['quote']})
        checks.append({'message_position': position, 'message_id': message['id'],
                       'role': message['role'], 'source_text': text,
                       'source_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                       'route': routes[message['id']], 'reason_codes': reasons,
                       'scope_observations': scope_observations(text),
                       'source_characters': len(text), 'evidence_characters': covered,
                       'evidence_spans': anchors, 'review_state': 'not_reviewed'})
    # Neighboring messages remain in the packet so quotation authors, anaphora
    # and later corrections can be checked. Their presence grants no authority
    # to a selected span and cannot justify filling missing names or conditions.
    return {'packet_version': 'scope-review-v1', 'method_version': version,
            'source_type': source_type,
            'messages': copy.deepcopy(messages),
            'messages_canonical_sha256': hashlib.sha256(json.dumps(
                messages, sort_keys=True, ensure_ascii=False, separators=(',', ':')
            ).encode()).hexdigest(),
            'source_visibility': request.get('source_visibility'),
            'evidence_coverage': {'source_characters': source_characters,
                                  'evidence_characters': evidence_characters,
                                  'zero_evidence_message_ids': zero_evidence_messages,
                                  'is_quality_score': False},
            'review_targets': checks, 'quality_approved': False,
            'facts_confirmed': False, 'automatic_scope_release': False,
            'model_calls': 0, 'contains_private_source_text': True}


def prepare_long_source_review(envelope, plan, *, version):
    """Bind a complete original to archive segments and per-segment review.

    This private offline work packet never invokes a provider or authorizes
    independent segment extraction. Cross-segment context is navigation only;
    partial or conditional messages remain explicit review blockers. Coverage
    counts archive bytes and extracted evidence separately, never as quality.
    """
    from .long_source_plan import verify_long_source_plan
    from .input_coverage import audit_input_coverage
    if not isinstance(envelope, dict):
        raise Invalid('长来源复核信封无效')
    messages = envelope.get('messages')
    verification = verify_long_source_plan(plan, messages)
    for key in ('source_key', 'scope', 'source_type', 'source_metadata'):
        expected = envelope.get(key, 'document' if key == 'source_type' else None)
        if plan[key] != expected:
            raise Invalid('长来源信封与归档计划不匹配')
    original_coverage = audit_input_coverage(plan['source_type'], messages, version=version)
    original_rows = {row['message_id']: row for row in original_coverage['items']}
    inherited = None
    inherited_rows = {}
    if version == '2026-10-04.22':
        from .source_context import inherit_source_context
        inherited = inherit_source_context(envelope, plan, version=version)
        inherited_rows = {row['segment_id']: row for row in inherited['segments']}
    segments = []
    for segment in plan['segments']:
        payload = segment['payload']
        review = prepare_scope_review(payload['source_type'], payload['messages'],
                                      version=version, source_metadata=payload['source_metadata'])
        coverage = audit_input_coverage(payload['source_type'], payload['messages'], version=version)
        original_row = original_rows[segment['original_message_id']]
        review_reasons = list(segment['review_reasons'])
        if coverage['items'][0]['route'] != original_row['route']:
            review_reasons.append('segment_routing_differs_from_complete_source')
        segments.append({'segment_id': segment['segment_id'],
                         'original_locator': {key: segment[key] for key in
                             ('message_index', 'original_message_id', 'start', 'end', 'global_start', 'global_end')},
                         'context_navigation': copy.deepcopy(segment['context_navigation']),
                         'review_reasons': review_reasons,
                         'complete_source_route': original_row['route'],
                         'automatic_extraction_authorized': False,
                         'independent_segment_routing_purpose': 'diagnostic_only_not_authorized_extraction',
                         'review_packet': review, 'input_coverage': coverage,
                         'inherited_context': copy.deepcopy(inherited_rows.get(segment['segment_id']))})
    return {'packet_version': 'long-source-review-v1', 'method_version': version,
            'original_envelope': copy.deepcopy(envelope), 'archive_verification': verification,
            'complete_source_input_coverage': original_coverage,
            'source_canonical_sha256': plan['source_canonical_sha256'], 'segments': segments,
            'archive_characters': plan['source_characters'],
            'extraction_evidence_characters': (inherited['inherited_evidence_characters'] if inherited else
                sum(s['input_coverage']['evidence_characters'] for s in segments)),
            'independent_segment_evidence_characters': sum(s['input_coverage']['evidence_characters'] for s in segments),
            'source_context_inheritance': inherited,
            'unreviewed_segments': len(segments), 'quality_approved': False,
            'facts_confirmed': False, 'automatic_scope_release': False, 'model_calls': 0,
            'contains_private_source_text': True}

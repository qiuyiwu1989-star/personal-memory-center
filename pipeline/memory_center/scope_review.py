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

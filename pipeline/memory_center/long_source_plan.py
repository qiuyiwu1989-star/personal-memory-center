"""Offline archive segmentation with independently verified literal coverage.

Navigation to a complete source is not evidence and never releases conditions.
Offsets count Unicode codepoints in the concatenation of source message texts,
without inserted separators. The caller must retain the immutable original.
"""
import copy
import hashlib
import json

from .core import Invalid, encoded
from .import_adapter import prepare_imports, MAX_CHARS
from .modality import CONDITION

VERSION = 'long-source-plan-v1'
MAX_TEXT = 20000


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _segment_id(parent, digest, index, start, end):
    return 'seg:' + _sha(_canonical([VERSION, parent, digest, index, start, end]))


def _segment_metadata(metadata, digest, index, original_id, start, end, global_start):
    result = dict(metadata or {})
    locator = {'source_sha256': digest, 'message_index': index, 'original_message_id': original_id,
               'start': start, 'end': end, 'global_start': global_start,
               'global_end': global_start + end - start, 'offset_unit': 'unicode_codepoint'}
    if result.get('locator'):
        locator['upstream_locator'] = result['locator']
    result['locator'] = _canonical(locator)
    return result


def plan_long_source(source_key, messages, *, scope, source_type='document', source_metadata=None):
    # Reuse the existing adapter's strict envelope validation before any result.
    # A short validation projection avoids its legacy >20k text behaviour.
    if not isinstance(messages, list) or not messages or len(messages) > 1000:
        raise Invalid('长来源消息列表无效')
    probe = []
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get('text'), str):
            raise Invalid('长来源消息结构无效')
        probe.append(dict(message, text=next((c for c in message['text'] if not c.isspace()), '')))
        if not message['text'].strip():
            raise Invalid('不能无损归档纯空白消息')
    prepare_imports(source_key, probe, scope=scope, source_type=source_type,
                    source_metadata=source_metadata)
    digest = _sha(_canonical(messages))
    segments, base = [], 0
    for index, original in enumerate(messages):
        text = original['text']
        start = 0
        while start < len(text):
            # Fixed-length ID means binary search is monotonic in payload size.
            candidate_id = 'seg:' + '0' * 64
            low, high = 0, min(MAX_TEXT, len(text) - start)
            while low < high:
                middle = (low + high + 1) // 2
                message = dict(original, id=candidate_id, text=text[start:start + middle])
                if len(encoded([message])) <= MAX_CHARS:
                    low = middle
                else:
                    high = middle - 1
            if not low or not text[start:start + low].strip():
                raise Invalid('空白区间或元信息无法在协议限制内无损归档')
            end = start + low
            # Keep a final whitespace tail with its preceding nonblank text if
            # possible; otherwise refuse atomically instead of dropping it.
            if end < len(text) and not text[end:].strip():
                last_nonblank = max(i for i in range(start, end) if not text[i].isspace())
                end = last_nonblank
                if end <= start or not text[start:end].strip():
                    raise Invalid('末尾空白无法在协议限制内无损归档')
            sid = _segment_id(source_key, digest, index, start, end)
            message = dict(original, id=sid, text=text[start:end])
            parts = prepare_imports(source_key, [message], scope=scope, source_type=source_type,
                                    source_metadata=_segment_metadata(source_metadata, digest, index, original['id'],
                                                                      start, end, base + start))
            if len(parts) != 1 or parts[0]['messages'] != [message]:
                raise Invalid('分段与归档适配器不一致')
            navigation = {'purpose': 'navigation_only_not_evidence', 'message_index': index,
                          'original_message_id': original['id'], 'message_characters': len(text),
                          'message_sha256': _sha(text),
                          'neighbor_message_indices': list(range(max(0, index - 1), min(len(messages), index + 2)))}
            reasons = []
            if start or end < len(text):
                reasons.append('partial_message_requires_context_review')
            if CONDITION.search(text):
                reasons.append('condition_scope_requires_semantic_review')
            segments.append({'segment_id': sid, 'message_index': index,
                             'original_message_id': original['id'], 'start': start, 'end': end,
                             'global_start': base + start, 'global_end': base + end,
                             'text_sha256': _sha(message['text']), 'payload': parts[0],
                             'context_navigation': navigation, 'review_reasons': reasons})
            start = end
        base += len(text)
    result = {'planner_version': VERSION, 'source_key': source_key, 'source_type': source_type,
              'scope': scope, 'source_metadata': copy.deepcopy(source_metadata),
              'source_canonical_sha256': digest, 'source_characters': base,
              'offset_unit': 'unicode_codepoint', 'global_offset_definition': 'concatenated_message_texts_no_separator',
              'segments': segments, 'ledger': {'covered_characters': base, 'missing_characters': 0,
                                              'literal_coverage_only': True},
              'model_calls': 0, 'quality_approved': False, 'facts_confirmed': False,
              'automatic_scope_release': False, 'processing_policy': 'archive'}
    verify_long_source_plan(result, messages)
    return result


def verify_long_source_plan(plan, messages):
    """Rebind every segment to originals; reject missing/reordered/tampered parts.

    Receipt hashes alone are not authenticity. Validation requires the actual
    original messages; coverage is not model evidence or semantic validation.
    """
    try:
        if not isinstance(messages, list) or not messages or len(messages) > 1000:
            raise Invalid('完整原始消息无效')
        if (plan['planner_version'] != VERSION or plan['offset_unit'] != 'unicode_codepoint'
                or plan['global_offset_definition'] != 'concatenated_message_texts_no_separator'
                or plan['source_canonical_sha256'] != _sha(_canonical(messages))
                or any(plan[key] is not False for key in ('quality_approved', 'facts_confirmed', 'automatic_scope_release'))
                or plan['model_calls'] != 0 or plan['processing_policy'] != 'archive'):
            raise Invalid('分段收据绑定或安全状态不匹配')
        segment_index = global_base = 0
        for index, original in enumerate(messages):
            start, text = 0, original['text']
            while start < len(text):
                segment = plan['segments'][segment_index]
                end = segment['end']
                if (any(type(segment[k]) is not int for k in ('start', 'end', 'message_index', 'global_start', 'global_end')) or not start < end <= len(text)
                        or segment['start'] != start or segment['message_index'] != index
                        or segment['original_message_id'] != original['id']
                        or segment['global_start'] != global_base + start
                        or segment['global_end'] != global_base + end):
                    raise Invalid('分段覆盖缺口或重叠')
                sid = _segment_id(plan['source_key'], plan['source_canonical_sha256'], index, start, end)
                expected_message = dict(original, id=sid, text=text[start:end])
                if (segment['segment_id'] != sid or segment['text_sha256'] != _sha(text[start:end])
                        or len(text[start:end]) > MAX_TEXT or not text[start:end].strip()):
                    raise Invalid('分段内容或标识不匹配')
                expected_payload = prepare_imports(plan['source_key'], [expected_message],
                    scope=plan['scope'], source_type=plan['source_type'],
                    source_metadata=_segment_metadata(plan['source_metadata'], plan['source_canonical_sha256'],
                                                      index, original['id'], start, end, global_base + start))
                if (len(expected_payload) != 1 or segment['payload'] != expected_payload[0]
                        or len(encoded(segment['payload']['messages'])) > MAX_CHARS):
                    raise Invalid('分段归档载荷不匹配')
                expected_navigation = {'purpose': 'navigation_only_not_evidence', 'message_index': index,
                    'original_message_id': original['id'], 'message_characters': len(text),
                    'message_sha256': _sha(text),
                    'neighbor_message_indices': list(range(max(0, index - 1), min(len(messages), index + 2)))}
                reasons = (['partial_message_requires_context_review'] if start or end < len(text) else [])
                if CONDITION.search(text):
                    reasons.append('condition_scope_requires_semantic_review')
                if segment['context_navigation'] != expected_navigation or segment['review_reasons'] != reasons:
                    raise Invalid('上下文导航或条件复核状态不匹配')
                start = end
                segment_index += 1
            global_base += len(text)
        if (segment_index != len(plan['segments']) or plan['source_characters'] != global_base
                or plan['ledger'] != {'covered_characters': global_base, 'missing_characters': 0,
                                      'literal_coverage_only': True}):
            raise Invalid('覆盖账本不匹配')
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise Invalid('分段收据结构无效') from exc
    return {'literal_coverage_verified': True, 'quality_approved': False,
            'source_characters': global_base, 'segment_count': segment_index}

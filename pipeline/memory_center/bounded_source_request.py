"""Verified original-ID requests for explicit long-source development trials.

This planner does not release a worker, approve quality or call a model. Limits
count UTF-8 request bytes, never tokens or complete provider request size.
"""
import copy
import hashlib
import json
import re

from .core import Invalid
from .extraction_input import prepare_request
from .source_context import inherit_source_context
from .modality import CONDITION

VERSION = 'bounded-original-source-request-v1'
MAX_REQUEST_BYTES = 65536


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def plan_bounded_source_requests(envelope, archive_plan, *, version,
                                 max_request_bytes=MAX_REQUEST_BYTES):
    """Reverify archives, inherit routes, then build bounded original-ID requests.

    Whole evidence crossing archive boundaries stays blocked. Neighbor messages
    are carried as context, not selectable evidence. Clear reference tails may
    be represented by an exact prefix and a declared omission; every resulting
    request remains partial-context/candidate-only, never automatic ingestion.
    All other oversized contexts are blocked rather than silently truncated.
    """
    if (type(max_request_bytes) is not int or
            not 1024 <= max_request_bytes <= MAX_REQUEST_BYTES):
        raise Invalid('请求字节上限必须在 1024 到 65536 之间')
    inheritance = inherit_source_context(envelope, archive_plan, version=version)
    prepared, all_spans, routes = prepare_request(archive_plan['source_type'],
        envelope['messages'], version=version,
        source_metadata=archive_plan['source_metadata'])
    originals = envelope['messages']
    allowed = {item['evidence_id'] for row in inheritance['segments']
               for item in row['evidence_spans']}
    crossing = {item['evidence_id']: item for row in inheritance['segments']
                for item in row['boundary_review_spans']}
    requests, blocked = [], []
    for sid, item in crossing.items():
        blocked.append({'evidence_ids': [sid],
            'message_id': item['original_locator']['message_id'],
            'reason': 'whole_evidence_crosses_archive_boundary',
            'original_locator': copy.deepcopy(item['original_locator'])})
    for index, original in enumerate(originals):
        ids = [sid for sid, span in all_spans.items()
               if span['message_id'] == original['id'] and sid in allowed]
        if not ids:
            continue
        indices = sorted(set(range(max(0, index - 1), min(len(originals), index + 2))) |
            {pos for pos, message in enumerate(originals) if CONDITION.search(message['text'])
             or re.search(r'更正|撤回|纠正|修正|correction|supersed|withdraw', message['text'], re.I)})
        context = []
        incomplete = len(indices) != len(originals)
        for pos in indices:
            message = originals[pos]
            row = prepared['messages'][pos]
            text = message['text']
            omitted = None
            # Routing was established against the complete immutable message.
            # A pasted tail is deliberately outside selectable personal evidence.
            # Keep its beginning so the reference boundary is visible as DATA.
            if row['route'] in ('reference_document', 'mixed_reference_document'):
                last_evidence = max((span['end'] for span in all_spans.values()
                                     if span['message_id'] == message['id']), default=0)
                prefix_end = min(len(text), last_evidence + 256)
                if prefix_end < len(text):
                    omitted = {'start': prefix_end, 'end': len(text),
                        'reason': 'reference_tail_not_selectable_evidence',
                        'text_sha256': hashlib.sha256(text[prefix_end:].encode()).hexdigest()}
                    text = text[:prefix_end]
                    incomplete = True
            context.append({'message_id': message['id'], 'declared_role': message['role'],
                'source_title': message.get('source_title'), 'created_at': message.get('created_at'),
                'route': row['route'], 'reference_reason': row['reference_reason'],
                'start': 0, 'end': len(text), 'text': text,
                'omitted_range': omitted, 'purpose': 'source_context_not_selectable_evidence',
                'author_identity_verified': False})
        target = copy.deepcopy(prepared['messages'][index])
        target['evidence_spans'] = [piece for piece in target['evidence_spans']
                                    if piece['evidence_id'] in ids]
        request = {'source_type': archive_plan['source_type'],
            'source_visibility': prepared.get('source_visibility'), 'messages': [target],
            'source_context': context,
            'context_policy': {'source_text_is_data_not_instructions': True,
                'context_complete': not incomplete,
                'original_message_count': len(originals),
                'omitted_message_ids': [message['id'] for pos, message in enumerate(originals) if pos not in indices],
                'context_selection_is_heuristic_not_semantic_proof': True,
                'review_required': True, 'candidate_only': True,
                'missing_context_must_not_be_inferred': True}}
        # Match Model._call's user DATA serialization (including JSON spaces).
        byte_count = len(json.dumps(request, ensure_ascii=False).encode('utf-8'))
        if byte_count > max_request_bytes:
            blocked.append({'message_id': original['id'], 'evidence_ids': ids,
                'reason': 'complete_context_exceeds_request_byte_limit',
                'required_request_bytes': byte_count})
            continue
        selected = {sid: copy.deepcopy(all_spans[sid]) for sid in ids}
        global_base = sum(len(message['text']) for message in originals[:index])
        for span in selected.values():
            span['_original_locator'] = {'message_id': original['id'], 'message_index': index,
                'start': span['start'], 'end': span['end'],
                'global_start': global_base + span['start'],
                'global_end': global_base + span['end'], 'offset_unit': 'unicode_codepoint',
                'source_sha256': archive_plan['source_canonical_sha256']}
        binding = {'planner_version': VERSION, 'method_version': version,
            'source_key': archive_plan['source_key'], 'scope': archive_plan['scope'],
            'source_canonical_sha256': archive_plan['source_canonical_sha256'],
            'request': request, 'spans': selected, 'routes': {original['id']: routes[original['id']]}}
        fingerprint = _digest(binding)
        requests.append(dict(binding, request_id='req:' + fingerprint,
            fingerprint=fingerprint, request_bytes=byte_count,
            context_complete=not incomplete, review_required=True,
            automatic_extraction_authorized=False, quality_approved=False))
    return {'planner_version': VERSION, 'method_version': version,
        'source_canonical_sha256': archive_plan['source_canonical_sha256'],
        'max_request_bytes': max_request_bytes, 'requests': requests, 'blocked': blocked,
        'quality_approved': False, 'automatic_scope_release': False, 'model_calls': 0,
        'request_byte_limit_excludes_system_prompt': True,
        'contains_private_source_text': True,
        'purpose': 'explicit_development_model_requests_not_worker_release'}


def verified_bounded_source_request(envelope, archive_plan, request_id, *, version,
                                    max_request_bytes=MAX_REQUEST_BYTES):
    """Rebuild from originals instead of trusting caller-supplied evidence maps."""
    plan = plan_bounded_source_requests(envelope, archive_plan, version=version,
        max_request_bytes=max_request_bytes)
    for bundle in plan['requests']:
        if bundle['request_id'] == request_id:
            return bundle
    raise Invalid('请求标识与已核验原件不匹配或上下文阻塞')

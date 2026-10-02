"""Deterministic client-side payload preparation; no network, model or approval."""
import hashlib
import json

from .core import Invalid, encoded

VERSION = 'memory-import-adapter-v1'
MAX_CHARS = 24000
MAX_MESSAGES = 100
FIELDS = {'id', 'role', 'text', 'source_title', 'created_at'}
from .source_metadata import FIELDS as META, validate as validate_metadata


def prepare_imports(source_key, messages, *, scope, source_type='document', source_metadata=None):
    """Return archive-only memory_import kwargs, preserving every input character.

    source_key identifies the parent document/conversation (never an access token).
    Existing roles are required, not inferred. Content changes create new part keys.
    Character offsets refer to Python/Unicode codepoints, not bytes or JS UTF-16.
    """
    if not isinstance(source_key, str) or not 1 <= len(source_key) <= 300:
        raise Invalid('稳定父来源标识需 1–300 字符')
    if not isinstance(scope, str) or not scope.strip():
        raise Invalid('需显式指定授权范围；适配器不创建权限')
    if source_type not in ('conversation', 'document', 'imported_summary'):
        raise Invalid('不支持的来源类型')
    if source_metadata is not None and not isinstance(source_metadata, dict):
        raise Invalid('来源元信息必须是对象')
    metadata = dict(source_metadata or {})
    metadata = validate_metadata(metadata)
    if not isinstance(messages, list) or not messages:
        raise Invalid('消息列表不能为空')
    ids = set()
    for message in messages:
        if not isinstance(message, dict) or set(message) - FIELDS:
            raise Invalid('未知消息字段不能静默丢弃；请显式解析')
        mid = message.get('id')
        if not isinstance(mid, str) or not 1 <= len(mid) <= 100 or mid in ids:
            raise Invalid('原始消息 id 需唯一且为 1–100 字符')
        ids.add(mid)
        if message.get('role') not in ('user', 'assistant', 'external'):
            raise Invalid('消息角色必须显式保留；不推断身份')
        if not isinstance(message.get('text'), str) or not message['text'].strip():
            raise Invalid('正文不能为空')
        for field in ('source_title', 'created_at'):
            if field in message and (not isinstance(message[field], str) or len(message[field]) > 300):
                raise Invalid('标题或日期无效；不编造日期')

    results, pending = [], []
    start_index = 0

    def emit(batch, locator):
        envelope = dict(metadata)
        if metadata.get('locator'):
            locator['original_locator'] = metadata['locator']
        if metadata.get('parser_version'):
            locator['original_parser_version'] = metadata['parser_version']
        if metadata.get('parent_source_key'):
            locator['upstream_parent_source_key'] = metadata['parent_source_key']
        envelope.update(parent_source_key=source_key, parser_version=VERSION,
                        locator=json.dumps(locator, ensure_ascii=False, sort_keys=True))
        if any(len(value) > 1000 for value in envelope.values()):
            raise Invalid('保留原定位后的元信息超过 1000 字符；请使用短的稳定原文定位')
        digest = hashlib.sha256(encoded([source_key, scope, source_type, batch, envelope]).encode()).hexdigest()
        results.append({'source_key': 'part:' + digest, 'scope': scope, 'source_type': source_type,
                        'processing_policy': 'archive', 'source_metadata': envelope,
                        'messages': batch})

    def flush(end_index):
        nonlocal pending
        if pending:
            emit(pending, {'message_start': start_index, 'message_end': end_index,
                           'offset_unit': 'unicode_codepoint'})
            pending = []

    for index, message in enumerate(messages):
        message = dict(message)
        if len(encoded([message])) <= MAX_CHARS:
            if pending and (len(pending) == MAX_MESSAGES or len(encoded(pending + [message])) > MAX_CHARS):
                flush(index)
            if not pending:
                start_index = index
            pending.append(message)
            continue
        flush(index)
        text, offset = message['text'], 0
        while offset < len(text):
            chunk_id = 'chunk:' + hashlib.sha256(message['id'].encode()).hexdigest()[:32] + ':' + str(offset)
            base = dict(message, id=chunk_id)
            low, high = 0, len(text) - offset
            while low < high:
                middle = (low + high + 1) // 2
                if len(encoded([dict(base, text=text[offset:offset + middle])])) <= MAX_CHARS:
                    low = middle
                else:
                    high = middle - 1
            if not low or not text[offset:offset + low].strip():
                raise Invalid('无法无损归档此空白区间；协议拒绝纯空白消息，不会截断')
            # A trailing whitespace-only final chunk cannot be accepted by Store.
            # Fail atomically rather than discard those original characters.
            emit([dict(base, text=text[offset:offset + low])],
                 {'message_index': index, 'original_message_id': message['id'],
                  'char_start': offset, 'char_end': offset + low,
                  'original_char_count': len(text), 'offset_unit': 'unicode_codepoint'})
            offset += low
    flush(len(messages))
    return results

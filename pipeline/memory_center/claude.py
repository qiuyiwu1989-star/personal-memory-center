"""Parse visible Claude content; flattened text may contain thinking/tool traces.

Archives remain byte-for-byte originals. This projection changes only new input
planning, never rewrites an existing source or its message locator.
"""
import json

PARSER_VERSION = 'claude-visible-text-2026-10-01.2'


def visible_blocks(raw):
    """Yield (locator, text); structured content is authoritative when present."""
    content = raw.get('content')
    if isinstance(content, list):
        for index, block in enumerate(content):
            if isinstance(block, dict) and block.get('type') == 'text':
                text = block.get('text')
                if isinstance(text, str) and text.strip():
                    yield f't{index}', text
        return
    # Older exports may omit content entirely. Explicit malformed content is not
    # permission to fall back to flattened text containing excluded block types.
    if 'content' in raw:
        return
    text = raw.get('text')
    if isinstance(text, str) and text.strip():
        yield 'legacy', text


def messages(conversation, part_chars=12000):
    title = str(conversation.get('name') or '未命名对话')[:120]
    for index, raw in enumerate(conversation.get('chat_messages') or []):
        if not isinstance(raw, dict):
            continue
        role = {'human': 'user', 'assistant': 'assistant'}.get(raw.get('sender'), 'external')
        original_id = str(raw.get('uuid') or ('message-'+str(index)))[:75]
        date = str(raw.get('created_at') or '')[:80]
        for locator, body in visible_blocks(raw):
            start=part=0
            while start<len(body):
                end=min(len(body),start+part_chars)
                # JSON escaping can double a source's size; split on serialized
                # text budget as well as characters, preserving every character.
                if len(json.dumps(body[start:end],ensure_ascii=False))>17000:
                    low,high=start+1,end
                    while low<high:
                        middle=(low+high+1)//2
                        if len(json.dumps(body[start:middle],ensure_ascii=False))<=17000:low=middle
                        else:high=middle-1
                    end=low
                text=body[start:end]
                if text.strip():
                    yield {'id': f'{original_id}#{locator}p{part}', 'role': role,
                           'text': text, 'source_title': title, 'created_at': date}
                start=end;part+=1

"""Visible source discovery: lexical evidence, never validated personal memory.

Indexes only Store.sources; raw archives are not implicitly imported. No model,
new dependency, fact confirmation, source mutation, or permission widening.
"""
import hashlib
import json
from pathlib import Path
import re
import time
from .core import Invalid, encoded, permit
from .retrieval_ranking import score_record_v3

INDEX_VERSION = 'source-discovery-v1'
CHUNK_CHARS = 1000
CHUNK_OVERLAP = 100
_HIDDEN_TAG = re.compile(r'<(/?)(?:thinking|think|analysis)(?:\s[^>]*)?>', re.I)


def setup(store):
    with store.db() as db:
        db.executescript(Path(__file__).with_name('migrations').joinpath('005_source_discovery.sql').read_text())


def _permit(principal, scope, write=False):
    permit(principal, scope, 'read')
    permit(principal, scope, 'source_read')
    if write:
        permit(principal, scope, 'write')
    if not isinstance(principal.get('owner'), str) or not principal['owner']:
        raise Invalid('原文访问需要明确 owner')


def _hash(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def _visible(message):
    if not isinstance(message, dict) or message.get('role') not in ('user', 'assistant', 'external'):
        return None
    if str(message.get('type', '')).lower() in ('thinking', 'redacted_thinking', 'analysis'):
        return None
    text = message.get('text')
    if not isinstance(text, str):
        return None
    # Replace hidden spans at the same character positions, so locators still
    # address the source. The hidden bytes never enter the index or response.
    ranges = []
    depth = 0
    start = None
    for match in _HIDDEN_TAG.finditer(text):
        if not match.group(1):
            if depth == 0:
                start = match.start()
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                ranges.append((start, match.end()))
    if depth:
        ranges.append((start, len(text)))
    if not ranges:
        return text
    visible = list(text)
    for start, end in ranges:
        visible[start:end] = ' ' * (end-start)
    return ''.join(visible)


def _messages(source):
    try:
        payload = json.loads(source['payload'])
    except (ValueError, TypeError):
        return []
    return payload if isinstance(payload, list) else []


def _chunks(source):
    chunks = []
    messages_count = 0
    payload_fingerprint = _hash([source['payload'], source['source_type'], source['source_key']])
    for index, message in enumerate(_messages(source)):
        text = _visible(message)
        if text is None or not text.strip():
            continue
        message_id = message.get('id')
        if not isinstance(message_id, str) or not message_id:
            continue
        messages_count += 1
        start = 0
        while start < len(text):
            end = min(len(text), start + CHUNK_CHARS)
            chunk = text[start:end]
            if chunk.strip():
                chunk_id = _hash([INDEX_VERSION, source['owner'], source['scope'], source['id'],
                                  source['digest'], payload_fingerprint, message_id, index, start, end, chunk])
                chunks.append((chunk_id, source['id'], source['owner'], source['scope'], source['digest'],
                               message_id, index, message['role'], source['source_type'], source['source_key'],
                               str(message.get('source_title') or ''), str(message.get('created_at') or ''),
                               start, end, chunk))
            if end == len(text):
                break
            start = end - CHUNK_OVERLAP
    return messages_count, chunks


def rebuild(store, principal, scope, force=False):
    """Explicit local index update, idempotent by source version and fingerprint."""
    _permit(principal, scope, write=True)
    if type(force) is not bool:
        raise Invalid('force 必须是布尔值')
    counts = {'indexed_sources': 0, 'unchanged_sources': 0, 'messages': 0, 'chunks': 0, 'removed_sources': 0}
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        sources = [dict(row) for row in db.execute(
            'SELECT * FROM sources WHERE owner=? AND scope=? ORDER BY created,id', (principal['owner'], scope))]
        versions = {row['source_id']: dict(row) for row in db.execute(
            'SELECT * FROM source_discovery_versions WHERE owner=? AND scope=?', (principal['owner'], scope))}
        active = {source['id'] for source in sources}
        for sid in versions.keys() - active:
            db.execute('DELETE FROM source_discovery_chunks WHERE source_id=? AND owner=? AND scope=?', (sid, principal['owner'], scope))
            db.execute('DELETE FROM source_discovery_versions WHERE source_id=? AND owner=? AND scope=?', (sid, principal['owner'], scope))
            counts['removed_sources'] += 1
        for source in sources:
            fingerprint = _hash([source['payload'], source['source_type'], source['source_key']])
            previous = versions.get(source['id'])
            if not force and previous and previous['source_digest'] == source['digest'] and previous['payload_digest'] == fingerprint and previous['index_version'] == INDEX_VERSION:
                counts['unchanged_sources'] += 1
                continue
            messages_count, chunks = _chunks(source)
            db.execute('DELETE FROM source_discovery_chunks WHERE source_id=? AND owner=? AND scope=?', (source['id'], principal['owner'], scope))
            db.execute('DELETE FROM source_discovery_versions WHERE source_id=? AND owner=? AND scope=?', (source['id'], principal['owner'], scope))
            for chunk in chunks:
                db.execute('INSERT INTO source_discovery_chunks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', chunk)
            db.execute('INSERT INTO source_discovery_versions VALUES(?,?,?,?,?,?,?,?,?)',
                       (source['id'], source['owner'], source['scope'], source['digest'], fingerprint,
                        INDEX_VERSION, time.time(), messages_count, len(chunks)))
            counts['indexed_sources'] += 1
            counts['messages'] += messages_count
            counts['chunks'] += len(chunks)
    return dict(counts, index_version=INDEX_VERSION, confirmed_facts=0)


def _budget(max_chars):
    if type(max_chars) is not int or not 500 <= max_chars <= 16000:
        raise Invalid('原文返回预算需为 500–16000 字符')


def _locator(row):
    return {'chunk_id': row['id'], 'source_id': row['source_id'], 'source_digest': row['source_digest'],
            'message_id': row['message_id'], 'message_index': row['message_index']}


def search(store, principal, scope, query, max_chars=6000, offset=0, limit=20):
    """Bounded deterministic search; returns only currently readable index rows."""
    _permit(principal, scope)
    _budget(max_chars)
    if not isinstance(query, str) or len(query) > 1000:
        raise Invalid('原文查询需为不超过 1000 字符的文本')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise Invalid('原文检索分页无效')
    with store.db() as db:
        # Joining current sources prevents deleted/edited material from leaking
        # via a stale index. Rebuild is explicit, never a hidden read mutation.
        # Read each current source payload once, not once per chunk. The hash
        # guard still excludes payload-only drift before returning any result.
        fingerprints = {row['id']: _hash([row['payload'], row['source_type'], row['source_key']])
                        for row in db.execute('SELECT id,payload,source_type,source_key FROM sources WHERE owner=? AND scope=?',
                                              (principal['owner'], scope))}
        rows = [dict(row) for row in db.execute(
            'SELECT c.*,v.payload_digest FROM source_discovery_chunks c JOIN sources s ON s.id=c.source_id '
            'JOIN source_discovery_versions v ON v.source_id=c.source_id '
            'WHERE c.owner=? AND c.scope=? AND s.owner=? AND s.scope=? AND s.digest=c.source_digest '
            'AND v.index_version=? ORDER BY s.created DESC,c.source_id,c.message_index,c.start_char',
            (principal['owner'], scope, principal['owner'], scope, INDEX_VERSION))]
    scored = []
    for row in rows:
        fingerprint = fingerprints.get(row['source_id'])
        # Ensure payload-only drift is invalidated as well as declared digest.
        if row['payload_digest'] != fingerprint:
            continue
        score = score_record_v3({'statement': row['text'], 'source_title': row['source_title']}, query) if query.strip() else 0
        if not query.strip() or score > 0:
            scored.append((row, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    result = {'results': [], 'total': len(scored), 'offset': offset, 'next_offset': None,
              'index_version': INDEX_VERSION, 'kind': 'source_evidence', 'facts_confirmed': False}
    if offset > len(scored):
        raise Invalid('原文检索位置超过结果')
    for row, score in scored[offset:offset+limit]:
        item = {key: row[key] for key in ('source_id','source_digest','source_key','message_id','role','material_type','source_title','source_date','start_char','end_char')}
        item.update(locator=_locator(row), score=score, snippet=row['text'][:240], evidence_only=True)
        candidate = dict(result, results=result['results'] + [item])
        candidate['next_offset'] = offset + len(candidate['results']) if offset + len(candidate['results']) < len(scored) else None
        if len(encoded(candidate)) > max_chars:
            break
        result = candidate
    if not result['results'] and offset < len(scored):
        raise Invalid('原文元信息超过预算，请提高 max_chars')
    return result


def read(store, principal, scope, locator, offset=0, max_chars=4000):
    """Page visible message by stable version locator; stale locators fail closed."""
    _permit(principal, scope)
    _budget(max_chars)
    if not isinstance(locator, dict) or set(locator) != {'chunk_id','source_id','source_digest','message_id','message_index'}:
        raise Invalid('原文 locator 无效')
    if type(offset) is not int or offset < 0:
        raise Invalid('原文分页位置无效')
    with store.db() as db:
        row = db.execute('SELECT c.*,s.payload,s.source_type,v.payload_digest FROM source_discovery_chunks c '
                         'JOIN sources s ON s.id=c.source_id JOIN source_discovery_versions v ON v.source_id=c.source_id '
                         'WHERE c.id=? AND c.owner=? AND c.scope=? AND s.owner=? AND s.scope=? AND s.digest=c.source_digest AND v.index_version=?',
                         (locator['chunk_id'],principal['owner'],scope,principal['owner'],scope,INDEX_VERSION)).fetchone()
    if not row:
        raise Invalid('原文 locator 不存在或版本已变化')
    row = dict(row)
    if _locator(row) != locator or row['payload_digest'] != _hash([row['payload'],row['source_type'],row['source_key']]):
        raise Invalid('原文 locator 不存在或版本已变化')
    messages = _messages(row)
    index = locator['message_index']
    if type(index) is not int or index < 0 or index >= len(messages):
        raise Invalid('原文消息不存在')
    text = _visible(messages[index])
    if text is None or offset > len(text):
        raise Invalid('原文分页位置无效')
    result = {'locator': locator, 'role':row['role'], 'material_type':row['material_type'],
              'kind':'source_evidence','facts_confirmed':False,'text':'','offset':offset,
              'next_offset':None,'total_chars':len(text)}
    end = min(len(text), offset+max_chars)
    while True:
        result.update(text=text[offset:end], next_offset=end if end < len(text) else None)
        excess = len(encoded(result))-max_chars
        if excess <= 0:
            return result
        if end <= offset:
            raise Invalid('原文 locator 超过预算')
        end = max(offset, end-excess)

"""Read-only scope checkpoints for cache invalidation, not an event delta feed.

There is no globally monotonic event sequence in the current schema. Timestamp
paging can skip tied/backdated or concurrently committed events. Instead this
endpoint hashes current record metadata in a consistent read transaction and
pages that same metadata. Continuations fail if its revision changed. No source
or statement text is read, no LLM is called, and reads never create schema.

The scan is O(number of scoped records), with bounded Python page storage. A
PostgreSQL driver may buffer query rows. This is not historical sync, a deletion
ledger, or a security capability: authenticate and authorize every request.
"""
import base64
import datetime
import hashlib
import json
import re
from .core import Conflict, Invalid, encoded, permit
from .dependency_audit import _exists

_VERSION = 1
_REVISION = re.compile(r'^[0-9a-f]{64}$')
_TOKEN = re.compile(r'^[A-Za-z0-9_-]+$')
MAX_AGE_SECONDS = 300


def _binding(principal, scope):
    return hashlib.sha256(encoded([principal['owner'], principal['id'], scope]).encode()).hexdigest()[:24]


def _cursor(binding, revision, offset=None):
    # An opaque transport token, deliberately not described as signed. It has
    # no authority: tampering cannot grant another scope or bypass permit().
    value = {'v': _VERSION, 'b': binding, 'r': revision, 'o': offset}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def _decode(cursor, binding):
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= 1000 or not _TOKEN.fullmatch(cursor):
        raise Invalid('无效变更游标；请重新获取检查点')
    try:
        raw = base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True)
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {'v', 'b', 'r', 'o'}
                or type(value['v']) is not int or value['v'] != _VERSION
                or value['b'] != binding or not isinstance(value['r'], str)
                or not _REVISION.fullmatch(value['r'])
                or (value['o'] is not None and (type(value['o']) is not int or value['o'] < 1))
                or _cursor(binding, value['r'], value['o']) != cursor):
            raise ValueError()
    except (ValueError, TypeError, UnicodeError, KeyError):
        raise Invalid('无效或不属于当前身份及范围的变更游标；请重新获取检查点') from None
    return value


def _read_snapshot(store, principal, scope, binding, offset, limit):
    day = datetime.date.today().isoformat()  # Same calendar as governance.usable.
    digest = hashlib.sha256(encoded([_VERSION, binding, day]).encode())
    items = []
    total = 0
    with store.db() as db:
        # Neither statement takes a write lock or creates/repairs tables.
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY' if store.dsn else 'BEGIN')
        withdrawals = _exists(store, db, 'source_withdrawals')
        translations = _exists(store, db, 'record_translations')
        digest.update(encoded([withdrawals, translations]).encode())
        columns = ("r.id,r.source_id,r.lifecycle,r.revision,r.supersedes,r.created,"
                   "COALESCE(g.state,'candidate') state,COALESCE(g.revision,0) governance_revision,"
                   "g.as_of,g.valid_until,g.reviewed,g.holder,g.subject_id,g.priority,r.status")
        columns += ',sw.created withdrawn_at' if withdrawals else ',NULL withdrawn_at'
        columns += ',t.run_id translation_run,t.reviewed translated_at' if translations else ',NULL translation_run,NULL translated_at'
        sql = ('SELECT ' + columns + ' FROM records r JOIN sources s ON s.id=r.source_id '
               'AND s.owner=r.owner AND s.scope=r.scope LEFT JOIN record_governance g ON g.record_id=r.id ')
        if withdrawals:
            sql += 'LEFT JOIN source_withdrawals sw ON sw.source_id=s.id AND sw.owner=s.owner AND sw.scope=s.scope '
        if translations:
            sql += "LEFT JOIN record_translations t ON t.record_id=r.id AND t.language='zh' "
        sql += 'WHERE r.owner=? AND r.scope=? ORDER BY r.id'
        for raw in db.execute(sql, (principal['owner'], scope)):
            row = dict(raw)
            digest.update(encoded(row).encode())
            digest.update(b'\n')
            if offset <= total < offset + limit:
                items.append({
                    'id': row['id'], 'source_id': row['source_id'],
                    'lifecycle': row['lifecycle'], 'revision': row['revision'],
                    'governance_revision': row['governance_revision'], 'state': row['state'],
                    'supersedes': row['supersedes'], 'source_withdrawn': row['withdrawn_at'] is not None,
                    'as_of': row['as_of'], 'valid_until': row['valid_until'],
                })
            total += 1
    return digest.hexdigest(), day, total, items


def changes(store, principal, scope, cursor=None, max_chars=4000, limit=50):
    """Return a bounded current metadata manifest when a checkpoint changed.

    Save ``checkpoint`` after the final page; use ``next_cursor`` to continue.
    Unchanged checkpoints return no items. Stale page cursors raise Conflict:
    invalidate context and restart without a cursor. Checkpoint changes always
    require refetching governed context, even when there are zero current rows.
    Do not patch trusted memory from these unverified metadata items.

    Date transitions change the revision without an event. Poll/refetch at most
    every refresh_after_seconds, and always authorize before using cached data.
    The TTL is a conservative revalidation interval, never a validity guarantee.
    """
    permit(principal, scope, 'read')
    if not isinstance(scope, str) or not 1 <= len(scope) <= 300:
        raise Invalid('记忆范围需为 1–300 字符')
    if type(max_chars) is not int or not 1000 <= max_chars <= 16000:
        raise Invalid('变更摘要预算需为 1000–16000 字符')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise Invalid('变更摘要每页需为 1–100 项')
    binding = _binding(principal, scope)
    previous = _decode(cursor, binding) if cursor is not None else None
    offset = (previous['o'] or 0) if previous else 0
    revision, day, total, items = _read_snapshot(store, principal, scope, binding, offset, limit)
    if previous and previous['o'] is not None and (previous['r'] != revision or offset >= total):
        raise Conflict('变更分页快照已变化或游标失效；请失效缓存并从无游标重新读取')
    changed = not previous or previous['r'] != revision or previous['o'] is not None
    if not changed:
        items = []
    result = {
        'kind': 'scope_metadata_checkpoint', 'scope': scope, 'scope_revision': revision,
        'changed': changed, 'requires_context_refresh': changed,
        'coverage': 'current_record_metadata_only', 'effective_date': day,
        'refresh_after_seconds': MAX_AGE_SECONDS, 'total': total, 'items': [],
        'next_cursor': None, 'checkpoint': _cursor(binding, revision),
    }
    if changed:
        # Account for the complete envelope including the longer continuation
        # token before admitting each item. Never silently skip an oversized item.
        for item in items:
            next_offset = offset + len(result['items']) + 1
            more = next_offset < total
            candidate = dict(result, items=result['items'] + [item],
                             next_cursor=_cursor(binding, revision, next_offset) if more else None,
                             checkpoint=None if more else _cursor(binding, revision))
            if len(encoded(candidate)) > max_chars:
                break
            result = candidate
        if total > offset and not result['items']:
            raise Invalid('变更摘要预算不足以容纳首项；请提高 max_chars')
    if len(encoded(result)) > max_chars:
        raise Invalid('变更摘要超过响应预算；请提高 max_chars')
    return result

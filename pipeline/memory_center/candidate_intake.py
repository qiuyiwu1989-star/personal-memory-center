"""Source-bound upstream suggestions, never fact confirmation or extraction.

Offsets count Unicode code points (Python string slicing), with an exclusive
end. The original source/message remains authoritative evidence. Source roles
are reported attribution, not proof of who spoke or of semantic entailment.
Production migration is explicit; read calls never create or repair schema.
"""
import hashlib
import json
import math
from pathlib import Path
import time
from .core import Invalid, Conflict, encoded, permit, uid
from .dependency_audit import _exists
from .source_lifecycle import is_withdrawn

_TOPICS = frozenset(('profile', 'preferences', 'people', 'areas', 'projects', 'topics'))
_KINDS = frozenset(('identity', 'preference', 'relationship', 'decision', 'plan', 'event', 'claim', 'suggestion'))
_CLAIM_FIELDS = frozenset(('message_id', 'quote', 'start', 'end', 'statement', 'topic', 'kind', 'subject', 'client_candidate_id'))


def setup(store):
    with store.db() as db:
        db.executescript(Path(__file__).with_name('migrations').joinpath('010_candidate_intake.sql').read_text())


def available(store, db):
    return all(_exists(store, db, table) for table in ('candidate_intake_receipts', 'candidate_intake_evidence'))


def _identity(principal):
    if any(not isinstance(principal.get(key), str) or not 1 <= len(principal[key]) <= 160 for key in ('owner', 'id')):
        raise Invalid('候选提交身份无效')
    expires = principal.get('expires_at')
    if principal.get('enabled', True) is not True or (expires is not None and (
            isinstance(expires, bool) or not isinstance(expires, (int, float))
            or not math.isfinite(expires) or expires <= time.time())):
        raise PermissionError('凭据已撤销或过期')


def _authorize(principal, scope):
    _identity(principal)
    for action in ('read', 'source_read', 'write'):
        permit(principal, scope, action)
    if principal.get('trusted_user') is not True:
        permit(principal, scope, 'candidate_write')
        if (principal.get('scopes') != [scope] or not isinstance(scope, str)
                or not scope.startswith('agent:') or not scope.endswith('-inbox')
                or len(scope) <= len('agent:-inbox')):
            raise PermissionError('第三方候选只允许单独 Agent 收件范围')


def _text(value, maximum, field):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise Invalid(field + ' 缺失或超长')
    return value


def _request(body):
    if not isinstance(body, dict) or set(body) - {'request_key', 'source_id', 'claims'}:
        raise Invalid('候选提交字段无效；不接受审核、角色或范围覆盖')
    request = {'request_key': _text(body.get('request_key'), 160, 'request_key'),
               'source_id': _text(body.get('source_id'), 300, 'source_id'), 'claims': []}
    claims = body.get('claims')
    if not isinstance(claims, list) or not 1 <= len(claims) <= 20:
        raise Invalid('每次提交需 1–20 条候选')
    client_ids = set()
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) - _CLAIM_FIELDS:
            raise Invalid('候选字段无效；不接受归属、状态、有效时间或角色覆盖')
        item = {field: _text(claim.get(field), maximum, field) for field, maximum in (
            ('message_id', 100), ('quote', 2000), ('statement', 1200), ('subject', 160))}
        for field, choices in (('topic', _TOPICS), ('kind', _KINDS)):
            if not isinstance(claim.get(field), str) or claim[field] not in choices:
                raise Invalid('候选主题或类型无效')
            item[field] = claim[field]
        start, end = claim.get('start'), claim.get('end')
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise Invalid('证据 start/end 需为 Unicode 字符偏移，end 不含尾字符')
        item.update(start=start, end=end)
        if 'client_candidate_id' in claim:
            client_id = _text(claim['client_candidate_id'], 160, 'client_candidate_id')
            if client_id in client_ids:
                raise Invalid('同一请求内 client_candidate_id 必须唯一')
            item['client_candidate_id'] = client_id
            client_ids.add(client_id)
        request['claims'].append(item)
    return request


def _evidence(source, claims):
    try:
        payload = json.loads(source['payload'])
        if not isinstance(payload, list):
            raise ValueError()
        messages = {}
        for message in payload:
            if (not isinstance(message, dict) or not isinstance(message.get('id'), str)
                    or message['id'] in messages or not isinstance(message.get('text'), str)
                    or message.get('role') not in ('user', 'assistant', 'external')):
                raise ValueError()
            messages[message['id']] = message
    except (ValueError, TypeError):
        raise Invalid('归档消息结构无效，无法核对证据') from None
    bound = []
    for claim in claims:
        message = messages.get(claim['message_id'])
        if (not message or claim['end'] > len(message['text'])
                or message['text'][claim['start']:claim['end']] != claim['quote']):
            raise Invalid('证据偏移和引文必须逐字匹配完整来源消息')
        status = ('imported_summary' if source['source_type'] == 'imported_summary' else
                  'agent_suggested' if message['role'] == 'assistant' else 'source_reported')
        bound.append((claim, message['role'], status))
    return bound


def submit(store, principal, scope, body):
    """Atomically save one immutable receipt plus reviewable candidate records.

    Permissions and source eligibility are rechecked before idempotent replay.
    Even a trusted owner's submission here does not attest source authorship.
    All writers use the shared BEGIN IMMEDIATE transaction lock (the PostgreSQL
    adapter takes an advisory transaction lock), including source withdrawal.
    """
    _authorize(principal, scope)
    request = _request(body)
    digest = hashlib.sha256(encoded(request).encode()).hexdigest()
    identity = (principal['owner'], scope, principal['id'], request['request_key'])
    receipt_id = 'candidate-' + hashlib.sha256(encoded(identity).encode()).hexdigest()
    now = time.time()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not available(store, db):
            raise Invalid('候选提交需先应用独立的 010 迁移')
        source = db.execute('SELECT * FROM sources WHERE id=? AND owner=? AND scope=?',
                            (request['source_id'], principal['owner'], scope)).fetchone()
        if not source or (principal.get('trusted_user') is not True and source['principal'] != principal['id']):
            raise Invalid('来源不存在或不可访问')
        if is_withdrawn(store, db, source['id']):
            raise Conflict('来源已撤回，不再接受候选或重复提交')
        old = db.execute('SELECT digest,receipt FROM candidate_intake_receipts '
                         'WHERE owner=? AND scope=? AND principal=? AND request_key=?', identity).fetchone()
        if old:
            if old['digest'] != digest:
                raise Conflict('request_key 已用于不同内容，请使用新的请求键')
            return json.loads(old['receipt']) | {'duplicate': True}
        bound = _evidence(source, request['claims'])
        record_ids = [uid() for _ in bound]
        receipt = {'id': receipt_id, 'source_id': source['id'], 'record_ids': record_ids,
                   'count': len(record_ids), 'duplicate': False, 'candidate_only': True,
                   'facts_confirmed': False, 'model_calls': 0, 'created': now}
        db.execute('INSERT INTO candidate_intake_receipts '
                   '(id,owner,scope,principal,request_key,digest,source_id,receipt,created) '
                   'VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(owner,scope,principal,request_key) DO NOTHING',
                   (receipt_id, *identity, digest, source['id'], encoded(receipt), now))
        # Fail closed if a future DB adapter changes transaction locking.
        stored = db.execute('SELECT digest,receipt FROM candidate_intake_receipts '
                            'WHERE owner=? AND scope=? AND principal=? AND request_key=?', identity).fetchone()
        if stored['digest'] != digest:
            raise Conflict('request_key 已用于不同内容，请使用新的请求键')
        if json.loads(stored['receipt'])['record_ids'] != record_ids:
            return json.loads(stored['receipt']) | {'duplicate': True}
        for record_id, (claim, role, status) in zip(record_ids, bound):
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (record_id, principal['owner'], scope, claim['topic'], claim['kind'], claim['subject'],
                        claim['statement'], status, source['id'], claim['message_id'], claim['quote'],
                        'active', 1, None, now))
            db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (record_id, None, None, None, None, 'candidate', 'P3', 0, '', now))
            db.execute('INSERT INTO candidate_intake_evidence VALUES(?,?,?,?,?,?)',
                       (record_id, receipt_id, claim.get('client_candidate_id'), role, claim['start'], claim['end']))
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                       (uid(), record_id, principal['id'], 'candidate_submit', None, now))
    getattr(store, '_document_cache', {}).pop((principal['owner'], scope), None)
    return receipt


def listing(store, principal, scope, offset=0, limit=20):
    """Owner receipt metadata only, including current governance, without text.

    Read/source_read separation is explicit: this route never returns source
    titles, statements, quotations, request keys or raw source content.
    """
    _identity(principal)
    if principal.get('trusted_user') is not True:
        raise PermissionError('仅本人可查看候选提交台账')
    permit(principal, scope, 'read')
    if type(offset) is not int or not 0 <= offset <= 1000000 or type(limit) is not int or not 1 <= limit <= 100:
        raise Invalid('候选台账分页参数无效')
    with store.db() as db:
        if not available(store, db):
            return {'supported': False, 'receipts': [], 'total': None, 'offset': offset, 'limit': limit,
                    'next_offset': None, 'migration_required': '010_candidate_intake'}
        total = db.execute('SELECT count(*) n FROM candidate_intake_receipts WHERE owner=? AND scope=?',
                           (principal['owner'], scope)).fetchone()['n']
        rows = db.execute('SELECT id,source_id,principal,receipt,created FROM candidate_intake_receipts '
                          'WHERE owner=? AND scope=? ORDER BY created DESC,id DESC LIMIT ? OFFSET ?',
                          (principal['owner'], scope, limit, offset)).fetchall()
        receipts = []
        for row in rows:
            receipt = json.loads(row['receipt'])
            receipt.update(principal=row['principal'],
                           source_state='withdrawn' if is_withdrawn(store, db, row['source_id']) else 'active')
            receipt['records'] = [dict(record) for record in db.execute(
                'SELECT r.id,r.status,r.lifecycle,r.revision,g.state,g.revision governance_revision,'
                'e.message_role,e.client_candidate_id FROM candidate_intake_evidence e '
                'JOIN records r ON r.id=e.record_id LEFT JOIN record_governance g ON g.record_id=r.id '
                'WHERE e.receipt_id=? AND r.owner=? AND r.scope=? ORDER BY r.created,r.id',
                (row['id'], principal['owner'], scope))]
            receipts.append(receipt)
    return {'supported': True, 'receipts': receipts, 'total': total, 'offset': offset, 'limit': limit,
            'next_offset': offset + len(receipts) if offset + len(receipts) < total else None}

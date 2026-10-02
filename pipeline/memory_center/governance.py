"""Additive governance: legacy extraction is evidence, never implicit approval."""
import datetime
import hashlib
import json
import time
from .core import Invalid, Conflict, permit, encoded, uid
from .judgment_contract import normalize, validate_verified

SCHEMA = '''
CREATE TABLE IF NOT EXISTS record_governance(
 record_id TEXT PRIMARY KEY, holder TEXT, subject_id TEXT, as_of TEXT,
 valid_until TEXT, state TEXT NOT NULL, priority TEXT NOT NULL,
 revision INTEGER NOT NULL, note TEXT NOT NULL, reviewed REAL NOT NULL);
CREATE TABLE IF NOT EXISTS governance_events(
 id TEXT PRIMARY KEY, record_id TEXT NOT NULL, actor TEXT NOT NULL,
 previous TEXT NOT NULL, current TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS source_envelopes(
 source_id TEXT PRIMARY KEY, metadata TEXT NOT NULL, policy TEXT NOT NULL);
'''


def setup(store):
    with store.db() as db:
        db.executescript(SCHEMA)


def metadata(row, stored=None):
    if stored:
        return dict(stored)
    return {'record_id': row['id'], 'holder': None, 'subject_id': None,
            'as_of': None, 'valid_until': None,
            'state': 'owner_corrected' if row['message_id'] == 'correction' else 'candidate',
            'priority': 'P3', 'revision': 0, 'note': '', 'reviewed': None}


def review(store, principal, record_id, body):
    if principal.get('trusted_user') is not True:
        raise PermissionError('仅本人可核实归属和有效状态')
    if not isinstance(body, dict) or set(body) - (set(('revision','change_kind','previous_valid_until')) | set(('holder','subject_id','as_of','valid_until','state','priority','note'))):
        raise Invalid('治理字段无效')
    if type(body.get('revision')) is not int or body['revision'] < 0:
        raise Invalid('需要有效的治理 revision')
    if 'state' not in body:
        raise Invalid('治理状态无效')
    from .temporal import request as temporal_request
    change=temporal_request(body)
    values = normalize({key: value for key, value in body.items() if key not in ('revision','change_kind','previous_valid_until')})
    state, priority = values['state'], values['priority']
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM records WHERE id=? AND owner=?', (record_id, principal['owner'])).fetchone()
        if not row: raise Invalid('记录不存在')
        permit(principal, row['scope'], 'write')
        if row['lifecycle'] != 'active': raise Conflict('记录已被取代')
        validate_verified(db, row['owner'], row['scope'], values)
        old = metadata(row, db.execute('SELECT * FROM record_governance WHERE record_id=?', (record_id,)).fetchone())
        if body.get('revision') != old['revision']: raise Conflict('治理记录已变化，请刷新')
        new = old | values | dict(state=state, priority=priority, revision=old['revision']+1,
                   note=values['note'] or '', reviewed=time.time())
        db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(record_id) DO UPDATE SET '
                   'holder=excluded.holder,subject_id=excluded.subject_id,as_of=excluded.as_of,valid_until=excluded.valid_until,'
                   'state=excluded.state,priority=excluded.priority,revision=excluded.revision,note=excluded.note,reviewed=excluded.reviewed',
                   tuple(new[k] for k in ('record_id','holder','subject_id','as_of','valid_until','state','priority','revision','note','reviewed')))
        db.execute('INSERT INTO governance_events VALUES(?,?,?,?,?,?)',
                   (uid(),record_id,principal['id'],encoded(old),encoded(new),time.time()))
        from .temporal import record as audit_change
        audit_change(store,db,principal,row['scope'],record_id,record_id,row['revision'],new,
                    'governance:'+record_id+':'+str(new['revision']),change,previous_governance=old)
    return new


def usable(row, today=None):
    g = row['governance']
    date = today or datetime.date.today().isoformat()
    return (not g['as_of'] or g['as_of'] <= date) and row['lifecycle'] == 'active' and g['state'] in ('verified','owner_corrected') and (
        not g['valid_until'] or g['valid_until'] > (today or datetime.date.today().isoformat()))


def context(store, principal, scope, query, max_chars=1600, retrieval_mode='lexical-v1'):
    if type(max_chars) is not int or not 500 <= max_chars <= 16000:
        raise Invalid('读取预算需为 500–16000 字符')
    snapshot = store.snapshot(principal,scope,query,limit=1000000,retrieval_mode=retrieval_mode)
    from .retrieval_ranking import score_record, score_record_v3
    rows = sorted((r for r in snapshot['records'] if usable(r)),
                  key=lambda r:(-(score_record_v3(r,query) if retrieval_mode=='lexical-v3' else score_record(r,query)),r['governance']['priority'],r['id']) if query.strip() and retrieval_mode in ('lexical-v2','lexical-v3') else (0,r['governance']['priority']) + (r['id'],))
    # Fingerprint the full eligible result, including records omitted by the
    # response budget. It is a change detector, not a cache/security promise.
    versions = [{k: row.get(k) for k in ('id','statement','display_statement','source_id',
                 'message_id','revision','governance','status','subject','source_date')} for row in rows]
    revision = hashlib.sha256(encoded([principal['owner'],scope,query,retrieval_mode,max_chars,versions]).encode()).hexdigest()[:24]
    result = {'scope':scope, 'context_revision':revision, 'etag':'"'+revision+'"',
              'records': [], 'total': len(rows), 'truncated': bool(rows),
              'policy': 'verified-or-owner-corrected-v1', 'retrieval':retrieval_mode}
    if len(encoded(result)) > max_chars:
        raise Invalid('读取范围或检索标识超过响应预算')
    for row in rows:
        item = {k:row[k] for k in ('id','statement','source_id','message_id','revision','governance','status','subject','source_date')}
        if row.get('translated'):
            item['original_statement']=item['statement'];item['statement']=row['display_statement'];item['language']='zh'
        candidate = dict(result, records=result['records']+[item], truncated=len(result['records'])+1 < len(rows))
        if len(encoded(candidate)) <= max_chars: result['records'].append(item)
    result['truncated'] = len(result['records']) < len(rows)
    return result

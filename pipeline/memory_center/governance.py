"""Additive governance: legacy extraction is evidence, never implicit approval."""
import datetime
import json
import time
from .core import Invalid, Conflict, permit, encoded, uid

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
    if not principal.get('trusted_user'):
        raise PermissionError('仅本人可核实归属和有效状态')
    state = body.get('state')
    if state not in ('candidate', 'verified', 'historical', 'rejected'):
        raise Invalid('治理状态无效')
    priority = body.get('priority', 'P3')
    if priority not in ('P0', 'P1', 'P2', 'P3'):
        raise Invalid('优先级无效')
    values = {}
    for key in ('holder', 'subject_id', 'as_of', 'valid_until', 'note'):
        value = body.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > (1000 if key == 'note' else 160)):
            raise Invalid('治理字段无效')
        values[key] = value or None
    for key in ('as_of', 'valid_until'):
        if values[key]:
            try: datetime.date.fromisoformat(values[key])
            except ValueError: raise Invalid('有效日期需为 YYYY-MM-DD') from None
    if values['valid_until'] and values['as_of'] and values['valid_until'] < values['as_of']:
        raise Invalid('失效时间不能早于成立时间')
    if state == 'verified' and (not values['holder'] or not values['subject_id'] or not values['as_of']):
        raise Invalid('核实记忆需明确主张者、对象和成立日期；未知时保留候选')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM records WHERE id=? AND owner=?', (record_id, principal['owner'])).fetchone()
        if not row: raise Invalid('记录不存在')
        permit(principal, row['scope'], 'write')
        if row['lifecycle'] != 'active': raise Conflict('记录已被取代')
        if state == 'verified':
            from .entities import exists
            if not exists(db,row['owner'],row['scope'],values['holder']) or not exists(db,row['owner'],row['scope'],values['subject_id']):
                raise Invalid('核实前需登记主张者和对象的稳定实体 ID')
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
    return new


def usable(row, today=None):
    g = row['governance']
    date = today or datetime.date.today().isoformat()
    return (not g['as_of'] or g['as_of'] <= date) and row['lifecycle'] == 'active' and g['state'] in ('verified','owner_corrected') and (
        not g['valid_until'] or g['valid_until'] > (today or datetime.date.today().isoformat()))


def context(store, principal, scope, query, max_chars=1600):
    if type(max_chars) is not int or not 500 <= max_chars <= 16000:
        raise Invalid('读取预算需为 500–16000 字符')
    snapshot = store.snapshot(principal,scope,query,limit=1000000)
    rows = sorted((r for r in snapshot['records'] if usable(r)), key=lambda r:r['governance']['priority'])
    result = {'records': [], 'total': len(rows), 'truncated': bool(rows), 'policy': 'verified-or-owner-corrected-v1'}
    for row in rows:
        item = {k:row[k] for k in ('id','statement','source_id','message_id','revision','governance')}
        if row.get('translated'):
            item['original_statement']=item['statement'];item['statement']=row['display_statement'];item['language']='zh'
        candidate = dict(result, records=result['records']+[item], truncated=len(result['records'])+1 < len(rows))
        if len(encoded(candidate)) <= max_chars: result['records'].append(item)
    result['truncated'] = len(result['records']) < len(rows)
    return result

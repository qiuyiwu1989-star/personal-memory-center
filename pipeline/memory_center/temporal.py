"""Append-only human change audit; governance remains the effective-period source."""
import datetime
import time
from .core import Invalid, encoded, permit, uid
from .dependency_audit import _exists

KINDS={'metadata_update','evidence_update','interpretation_correction','viewpoint_change','withdrawal','legacy_unspecified'}
SCHEMA='''
CREATE TABLE IF NOT EXISTS memory_change_events(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL, record_id TEXT NOT NULL,
 previous_record_id TEXT, record_revision INTEGER NOT NULL, governance_revision INTEGER NOT NULL,
 change_kind TEXT NOT NULL, valid_from TEXT, valid_until TEXT, previous_valid_until TEXT,
 recorded_at REAL NOT NULL, previous_retired_at REAL, actor TEXT NOT NULL,
 request_key TEXT NOT NULL, UNIQUE(owner,scope,request_key));
CREATE TABLE IF NOT EXISTS scope_projection_state(
 owner TEXT NOT NULL, scope TEXT NOT NULL, generation INTEGER NOT NULL,
 refreshed_generation INTEGER NOT NULL, state TEXT NOT NULL, updated REAL NOT NULL,
 refreshed_at REAL, PRIMARY KEY(owner,scope));
'''


def setup(store):
    """Explicit local/rehearsal setup only; production uses separately applied SQL."""
    with store.db() as db:db.executescript(SCHEMA)


def request(body):
    kind=body.get('change_kind','legacy_unspecified')
    end=body.get('previous_valid_until')
    if not isinstance(kind,str) or kind not in KINDS:raise Invalid('change_kind 无效')
    if end is not None:
        try:
            if datetime.date.fromisoformat(end).isoformat()!=end:raise ValueError()
        except (ValueError,TypeError):raise Invalid('旧判断失效日期需为 YYYY-MM-DD') from None
        if kind!='viewpoint_change':raise Invalid('只有明确观点改变可注明旧判断事实失效日期')
    return {'change_kind':kind,'previous_valid_until':end}


def available(store,db):
    return _exists(store,db,'memory_change_events') and _exists(store,db,'scope_projection_state')


def record(store,db,principal,scope,rid,previous,record_revision,governance,request_key,change,now=None,previous_governance=None):
    if principal.get('trusted_user') is not True:raise PermissionError('仅本人可追加纠正时间审计')
    permit(principal,scope,'write')
    # Withdrawal is an explicit human action, never a state inferred by the UI.
    # Reject inconsistent API requests inside the same mutation transaction.
    if change['change_kind']=='withdrawal' and governance.get('state')!='rejected':
        raise Invalid('撤回记录需将治理状态明确设为不采纳')
    if not available(store,db):
        if change['change_kind']!='legacy_unspecified' or change['previous_valid_until'] is not None:
            raise Invalid('纠正时间审计需要先应用独立的 007 迁移')
        return False
    now=now if now is not None else time.time()
    # Explicit old fact-period end requires an actual previous version.
    if change['previous_valid_until'] and not previous:
        raise Invalid('新增判断没有旧版本，不能填写旧判断失效日期')
    # Explicit old fact-period end is audited, never inferred from system time.
    if change['previous_valid_until'] and previous:
        old=previous_governance if previous_governance is not None else db.execute('SELECT g.as_of FROM record_governance g JOIN records r ON r.id=g.record_id '
                       'WHERE r.id=? AND r.owner=? AND r.scope=?',(previous,principal['owner'],scope)).fetchone()
        if old and old['as_of'] and change['previous_valid_until']<old['as_of']:
            raise Invalid('旧事实失效日期不能早于旧成立日期')
    old=db.execute('SELECT id FROM memory_change_events WHERE owner=? AND scope=? AND request_key=?',
                   (principal['owner'],scope,request_key)).fetchone()
    if old:return False
    db.execute('INSERT INTO memory_change_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (uid(),principal['owner'],scope,rid,previous,record_revision,governance['revision'],
                change['change_kind'],governance.get('as_of'),governance.get('valid_until'),change['previous_valid_until'],
                now,now if previous else None,principal['id'],request_key))
    db.execute("INSERT INTO scope_projection_state VALUES(?,?,1,0,'dirty',?,NULL) ON CONFLICT(owner,scope) "
               "DO UPDATE SET generation=scope_projection_state.generation+1,state='dirty',updated=excluded.updated",
               (principal['owner'],scope,now))
    return True


def status(store,principal,scope):
    permit(principal,scope,'read')
    with store.db() as db:
        if not available(store,db):return {'scope':scope,'coverage':'legacy_incomplete','state':'unavailable','stale':None}
        row=db.execute('SELECT generation,refreshed_generation,state,updated,refreshed_at FROM scope_projection_state '
                       'WHERE owner=? AND scope=?',(principal['owner'],scope)).fetchone()
    if not row:return {'scope':scope,'coverage':'since-migration-only','state':'untracked','stale':None}
    return dict(row,scope=scope,coverage='since-migration-only',stale=row['generation']>row['refreshed_generation'])


def acknowledge(store,db,owner,scope):
    """Acknowledge deterministic projection refresh inside its write transaction."""
    if available(store,db):
        db.execute("UPDATE scope_projection_state SET refreshed_generation=generation,state='ready',refreshed_at=? "
                   'WHERE owner=? AND scope=? AND refreshed_generation<generation',(time.time(),owner,scope))

"""Explicit owner withdrawal: retain audit bytes, stop current evidence use.

No model calls, physical deletion, inferred multi-source merging or prefix bulk action.
Production schema activation is a separate migration operation.
"""
import json
import time
from pathlib import Path
from .core import Invalid, Conflict, permit, encoded
from .dependency_audit import _exists


def setup(store):
    with store.db() as db:
        db.executescript(Path(__file__).with_name('migrations').joinpath('009_source_lifecycle.sql').read_text())


def available(store, db):
    return _exists(store, db, 'source_withdrawals')


def active_sql(store, db, source_column='s.id'):
    # Column names are internal constants, never user input.
    return (' AND NOT EXISTS (SELECT 1 FROM source_withdrawals sw WHERE sw.source_id='
            +source_column+') ') if available(store, db) else ''


def is_withdrawn(store, db, source_id):
    return available(store, db) and bool(db.execute(
        'SELECT source_id FROM source_withdrawals WHERE source_id=?', (source_id,)).fetchone())


def _bulk_blocked(store, db, source_id):
    if not _exists(store, db, 'bulk_segments'):
        return False
    return bool(db.execute("SELECT bs.id FROM bulk_segments bs JOIN jobs j ON j.id=bs.job_id "
                           "WHERE j.source_id=? AND (bs.state NOT IN ('applied','failed') "
                           "OR bs.reserved_tokens>0 OR j.attempts>bs.attempts_counted "
                           "OR j.state IN ('received','processing','paused_budget')) LIMIT 1", (source_id,)).fetchone())


def _authorize(principal, scope):
    if principal.get('trusted_user') is not True:
        raise PermissionError('仅本人可撤回来源或查看撤回影响')
    permit(principal, scope, 'read')
    permit(principal, scope, 'write')


def preview(store, principal, scope, source_id, max_chars=6000):
    _authorize(principal, scope)
    from .dependency_audit import preview as dependencies
    # Owner read/write grant is sufficient here; this never returns source text.
    internal = dict(principal, actions=list(set(principal.get('actions', [])) | {'source_read'}))
    result = dependencies(store, internal, scope, source_id, max_chars)
    with store.db() as db:
        withdrawn = is_withdrawn(store, db, source_id)
        enabled = available(store, db)
        blocked = _bulk_blocked(store, db, source_id)
    result = result | {'withdrawal_supported':enabled, 'source_state':'withdrawn' if withdrawn else 'active',
                       'archive_retained':True, 'multi_source_action_supported':False,
                       'blockers':['bulk_processing_or_unsettled'] if blocked else []}
    while len(encoded(result)) > max_chars and result['objects']:
        result['objects'].pop()
        result['truncated'] = True
    if len(encoded(result)) > max_chars:
        raise Invalid('撤回预览摘要超过预算，请提高 max_chars')
    return result


def withdraw(store, principal, scope, source_id, reason=''):
    _authorize(principal, scope)
    if not isinstance(source_id, str) or not 1 <= len(source_id) <= 300:
        raise Invalid('来源不存在或不可访问')
    if not isinstance(reason, str) or len(reason) > 500:
        raise Invalid('撤回说明最多 500 字符')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not available(store, db):
            raise Invalid('来源撤回需先应用独立的 009 迁移')
        source = db.execute('SELECT id FROM sources WHERE id=? AND owner=? AND scope=?',
                            (source_id, principal['owner'], scope)).fetchone()
        if not source:
            raise Invalid('来源不存在或不可访问')
        old = db.execute('SELECT receipt FROM source_withdrawals WHERE source_id=?', (source_id,)).fetchone()
        if old:
            return json.loads(old['receipt']) | {'duplicate':True}
        if _bulk_blocked(store, db, source_id):
            raise Conflict('来源仍有历史批次处理或未结算预算，请待批次结算后再撤回')
        counts = {'records':db.execute('SELECT count(*) n FROM records WHERE source_id=? AND owner=? AND scope=?',
                    (source_id, principal['owner'], scope)).fetchone()['n'], 'jobs_cancelled':0, 'runs_cancelled':0}
        counts['jobs_cancelled'] = db.execute("SELECT count(*) n FROM jobs WHERE source_id=? AND state IN ('received','processing','paused_budget')",
                                              (source_id,)).fetchone()['n']
        db.execute("UPDATE jobs SET state='withdrawn',lease=NULL,lease_until=NULL,error='source_withdrawn' WHERE source_id=? AND state IN ('received','processing','paused_budget')", (source_id,))
        if _exists(store, db, 'extraction_runs'):
            counts['runs_cancelled'] = db.execute("SELECT count(*) n FROM extraction_runs WHERE source_id=? AND state IN ('received','processing','paused_budget','ready')", (source_id,)).fetchone()['n']
            db.execute("UPDATE extraction_runs SET state='withdrawn',lease=NULL,lease_until=NULL,error='source_withdrawn' WHERE source_id=? AND state IN ('received','processing','paused_budget','ready')", (source_id,))
        receipt = {'source_id':source_id, 'scope':scope, 'state':'withdrawn', 'archive_retained':True,
                   'counts':counts, 'context_invalidated':True, 'current_projection_invalidated':True,
                   'source_discovery_hidden':True, 'duplicate':False, 'withdrawn_at':time.time(),
                   'independent_sources_preserved':True}
        db.execute('INSERT INTO source_withdrawals VALUES(?,?,?,?,?,?,?)',
                   (source_id, principal['owner'], scope, principal['id'], reason, receipt['withdrawn_at'], encoded(receipt)))
    getattr(store, '_document_cache', {}).pop((principal['owner'], scope), None)
    return receipt

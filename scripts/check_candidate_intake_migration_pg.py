#!/usr/bin/env python3
"""Synthetic migration 010 rehearsal in an empty, explicitly local scratch DB.

QIU_MEMORY_INTAKE_SCRATCH_DSN must name memory_intake_scratch_<suffix> and an
explicit loopback/Unix-socket host. Never reads deployment DSNs, prints DSNs,
creates/drops databases, dispatches models, or connects to production. Caller
owns creation and disposal of the dedicated scratch database.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _local_scratch(dsn):
    import psycopg.conninfo
    if not isinstance(dsn, str) or not dsn:
        raise ValueError('An explicit scratch DSN is required')
    args = psycopg.conninfo.conninfo_to_dict(dsn)
    database = args.get('dbname', '')
    host = args.get('host', '')
    if (not re.fullmatch(r'memory_intake_scratch_[a-z0-9_]+', database)
            or not (host in ('localhost', '127.0.0.1', '::1') or host.startswith('/'))
            or ',' in host or 'service' in args
            or args.get('hostaddr', '127.0.0.1') not in ('127.0.0.1', '::1')):
        raise ValueError('An explicit local disposable scratch database is required')
    return database


def _counts(store):
    with store.db() as db:
        return {table: db.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] for table in (
            'sources', 'jobs', 'records', 'record_governance', 'events', 'model_attempts',
            'candidate_intake_receipts', 'candidate_intake_evidence')}


def _raises(exception, call):
    try:
        call()
    except exception:
        return
    raise AssertionError('Synthetic operation should have failed')


def check(dsn):
    import psycopg
    from pipeline.memory_center import candidate_intake, change_feed, governance, source_lifecycle
    from pipeline.memory_center.core import Store, Conflict, Invalid
    database = _local_scratch(dsn)
    migration = Path(__file__).resolve().parents[1] / 'pipeline/memory_center/migrations/010_candidate_intake.sql'
    with psycopg.connect(dsn, connect_timeout=5) as db:
        if db.execute('SELECT current_database()').fetchone()[0] != database:
            raise ValueError('Unexpected database')
        if db.execute("SELECT count(*) FROM pg_namespace WHERE nspname='memory_center'").fetchone()[0]:
            raise ValueError('Scratch database must start empty')
        user_objects = db.execute(
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' "
            "AND c.relkind IN ('r','p','v','m','S','f')").fetchone()[0]
        if user_objects:
            raise ValueError('Scratch database must contain no user data objects')
        db.execute('CREATE SCHEMA memory_center')
        db.execute('SET search_path=memory_center')
        # Use literal migration SQL before the Store adapter can rewrite types.
        db.execute(migration.read_text()); db.execute(migration.read_text())
        types = dict(db.execute("SELECT column_name,data_type FROM information_schema.columns "
                                "WHERE table_schema='memory_center' AND table_name='candidate_intake_receipts'").fetchall())
        assert types['created'] == 'double precision'
        evidence_types = dict(db.execute("SELECT column_name,data_type FROM information_schema.columns "
                                         "WHERE table_schema='memory_center' AND table_name='candidate_intake_evidence'").fetchall())
        assert evidence_types['quote_start'] == evidence_types['quote_end'] == 'integer'

    scope = 'agent:synthetic-pg-inbox'
    agent = {'id': 'synthetic-pg-node', 'owner': 'synthetic-pg-owner', 'trusted_user': False,
             'scopes': [scope], 'actions': ['read', 'source_read', 'write', 'candidate_write'], 'archive_only': True}
    owner = dict(agent, id='synthetic-pg-person', trusted_user=True, actions=['read', 'write', 'source_read'])
    with tempfile.TemporaryDirectory(prefix='candidate-intake-pg-synthetic-') as directory:
        store = Store(directory, dsn=dsn)
        source_lifecycle.setup(store)
        source = store.ingest(agent, {'scope': scope, 'source_key': 'synthetic-pg-source',
            'processing_policy': 'archive', 'messages': [{'id': 'synthetic-message', 'role': 'user',
                                                         'text': '🌱合成提案。后续仍待人工核实。'}]})
        claim = {'message_id': 'synthetic-message', 'quote': '合成提案。', 'start': 1, 'end': 6,
                 'statement': '合成待核实提案。', 'subject': '合成主题', 'topic': 'topics', 'kind': 'claim',
                 'client_candidate_id': 'synthetic-pg-candidate'}
        body = {'request_key': 'synthetic-pg-request', 'source_id': source['id'], 'claims': [claim]}
        call = lambda: candidate_intake.submit(store, agent, scope, body)
        baseline = _counts(store)
        before_checkpoint = change_feed.changes(store, owner, scope)['checkpoint']
        exact_time = 1700000000.125
        with patch('pipeline.memory_center.candidate_intake.time.time', return_value=exact_time):
            first = call()
        with store.db() as db:
            stored_time = db.execute('SELECT created FROM candidate_intake_receipts WHERE id=?', (first['id'],)).fetchone()['created']
            assert stored_time == exact_time
        assert call() == first | {'duplicate': True}
        changed_body = dict(body, claims=[dict(claim, statement='合成不同提案。')])
        _raises(Conflict, lambda: candidate_intake.submit(store, agent, scope, changed_body))
        concurrent_body = dict(body, request_key='synthetic-pg-concurrent')
        with ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: candidate_intake.submit(store, agent, scope, concurrent_body), range(4)))
        assert sum(not receipt['duplicate'] for receipt in receipts) == 1
        assert len({receipt['id'] for receipt in receipts}) == 1
        assert len({tuple(receipt['record_ids']) for receipt in receipts}) == 1
        after = _counts(store)
        assert after['candidate_intake_receipts'] == after['records'] == after['candidate_intake_evidence'] == 2
        assert all(after[key] == baseline[key] for key in ('sources', 'jobs', 'model_attempts'))

        invalid = dict(body, request_key='synthetic-pg-bad-evidence', claims=[claim, dict(claim,
                       client_candidate_id='synthetic-second', quote='合成不匹配引文')])
        _raises(Invalid, lambda: candidate_intake.submit(store, agent, scope, invalid))
        assert _counts(store) == after
        failed = dict(body, request_key='synthetic-pg-midwrite-failure', claims=[claim, dict(claim,
                      client_candidate_id='synthetic-second')])
        with patch('pipeline.memory_center.candidate_intake.uid', side_effect=[
                'synthetic-rollback-r1', 'synthetic-rollback-r2', 'synthetic-rollback-e1', RuntimeError('synthetic rollback')]):
            _raises(RuntimeError, lambda: candidate_intake.submit(store, agent, scope, failed))
        assert _counts(store) == after

        _raises(PermissionError, lambda: candidate_intake.submit(store, dict(agent, actions=['read', 'write', 'source_read']), scope, body))
        _raises(Invalid, lambda: candidate_intake.submit(store, dict(agent, id='synthetic-other-node'), scope, body))
        _raises(Invalid, lambda: candidate_intake.submit(store, dict(agent, owner='synthetic-other-owner'), scope, body))
        _raises(PermissionError, lambda: candidate_intake.listing(store, agent, scope))
        page = candidate_intake.listing(store, dict(owner, actions=['read']), scope, limit=1)
        assert page['total'] == 2 and page['next_offset'] == 1
        assert claim['quote'] not in json.dumps(page, ensure_ascii=False)
        assert claim['statement'] not in json.dumps(page, ensure_ascii=False)
        assert governance.context(store, owner, scope, '')['records'] == []

        checkpoint = change_feed.changes(store, owner, scope, cursor=before_checkpoint)
        assert checkpoint['changed'] and checkpoint['requires_context_refresh'] and checkpoint['total'] == 2
        assert all(item['state'] == 'candidate' for item in checkpoint['items'])
        assert not change_feed.changes(store, owner, scope, cursor=checkpoint['checkpoint'])['changed']
        governance.review(store, owner, first['record_ids'][0], {'revision': 0, 'state': 'rejected'})
        reviewed = change_feed.changes(store, owner, scope, cursor=checkpoint['checkpoint'])
        assert reviewed['changed'] and any(item['state'] == 'rejected' for item in reviewed['items'])
        source_lifecycle.withdraw(store, owner, scope, source['id'], 'Synthetic withdrawal rehearsal')
        _raises(Conflict, call)
        withdrawn = change_feed.changes(store, owner, scope, cursor=reviewed['checkpoint'])
        assert withdrawn['changed'] and all(item['source_withdrawn'] for item in withdrawn['items'])
        assert candidate_intake.listing(store, owner, scope)['total'] == 2
        assert _counts(store)['model_attempts'] == 0

    return {'database_prefix': 'memory_intake_scratch_', 'literal_migration_replayed': True,
            'literal_double_precision_verified': True, 'epoch_fraction_preserved': True,
            'concurrent_retry': 'one receipt and one record', 'payload_conflict_rejected': True,
            'transaction_rollback': True, 'authorization_isolated': True,
            'governance_and_withdrawal_checkpoints_changed': True,
            'trusted_context_candidates_excluded': True, 'model_calls': 0, 'production_writes': 0,
            'cleanup': 'caller must drop the disposable scratch database'}


def main():
    dsn = os.environ.get('QIU_MEMORY_INTAKE_SCRATCH_DSN')
    if not dsn:
        print('QIU_MEMORY_INTAKE_SCRATCH_DSN must name an empty local memory_intake_scratch_ database', file=sys.stderr)
        return 2
    try:
        result = check(dsn)
    except Exception as error:
        # Driver errors can include DSNs, hosts, users, SQL or source values.
        print('Candidate intake PostgreSQL rehearsal failed: ' + type(error).__name__, file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

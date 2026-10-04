#!/usr/bin/env python3
"""Synthetic PostgreSQL configuration rehearsal; never accepts the live database.

Run on a separately created disposable database with prefix memory_config_scratch_.
DSN comes from QIU_MEMORY_SCRATCH_DSN, never printed. No model calls; database connection only.
The caller owns creation/cleanup; this script cannot migrate production.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def check(dsn):
    import psycopg
    from pipeline.memory_center.core import Store, Conflict, Invalid
    from pipeline.memory_center.configuration import draft, activate, listing, runtime, extra_reservation
    from pipeline.memory_center import budget
    with psycopg.connect(dsn) as db:
        name = db.execute('SELECT current_database()').fetchone()[0]
        if not name.startswith('memory_config_scratch_'):
            raise ValueError('A disposable scratch database is required')
        if db.execute("SELECT count(*) FROM pg_namespace WHERE nspname='memory_center'").fetchone()[0]:
            raise ValueError('Scratch database must start empty')
        db.execute('CREATE SCHEMA memory_center')
        db.execute('SET search_path=memory_center')
        # Exercise the literal SQL used by psql, before Store can mask type drift.
        literal_migration=Path(__file__).resolve().parents[1]/'pipeline/memory_center/migrations/008_system_configuration.sql'
        db.execute(literal_migration.read_text());db.execute(literal_migration.read_text())
        types=db.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='memory_center' AND table_name IN ('system_config_versions','system_config_events') AND column_name='created'").fetchall()
        assert len(types)==2 and all(row[0]=='double precision' for row in types)

    principal = dict(id='synthetic-owner', owner='synthetic-config-rehearsal', trusted_user=True,
                     scopes=['personal','project:synthetic'], actions=['read','write','source_read'])
    with tempfile.TemporaryDirectory(prefix='config-pg-synthetic-') as directory:
        store=Store(directory,dsn=dsn)
        migration=Path(__file__).resolve().parents[1]/'pipeline/memory_center/migrations/008_system_configuration.sql'
        with store.db() as db:
            db.executescript(migration.read_text()); db.executescript(migration.read_text())
            initial = {table:db.execute('SELECT count(*) n FROM '+table).fetchone()['n']
                       for table in ('records','sources','jobs','bulk_batches','model_attempts')}
        def make(text):
            return draft(store,principal,'personal',dict(kind='prompt',label='Synthetic PostgreSQL version',payload={'instructions':text}))['id']
        first=make('合成版本一');second=make('合成版本二')
        def enable(vid,revision):
            try:
                return activate(store,principal,'personal',vid,{'revision':revision,'note':'Synthetic concurrency and rollback rehearsal only'})
            except Conflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda vid:enable(vid,0),(first,second)))
        assert sum(isinstance(r,dict) for r in results)==1 and results.count('conflict')==1
        winner=runtime(store,{'owner':principal['owner'],'scope':'personal'})['prompt_version']
        other=second if winner==first else first
        assert enable(other,1)['revision']==2
        assert enable(winner,2)['revision']==3
        listing_result=listing(store,principal,'personal')
        assert len(listing_result['events'])==3 and len(listing_result['versions'])==2
        for actor,scope in ((dict(principal,trusted_user=False),'personal'),(principal,'outside')):
            try:draft(store,actor,scope,dict(kind='prompt',label='Denied',payload={'instructions':'Denied'}))
            except PermissionError:pass
            else:raise AssertionError('Unauthorized configuration accepted')
        try:activate(store,principal,'project:synthetic',first,{'revision':0,'note':'Synthetic cross-scope denial test'})
        except Invalid:pass
        else:raise AssertionError('Cross-scope activation accepted')
        before=listing(store,principal,'personal')['active']['prompt']['revision']
        try:
            with store.db() as db:
                db.execute("UPDATE system_config_active SET revision=99 WHERE owner=?",(principal['owner'],))
                raise RuntimeError('synthetic transaction rollback')
        except RuntimeError:pass
        assert listing(store,principal,'personal')['active']['prompt']['revision']==before
        with store.db() as db:
            assert extra_reservation(db,principal['owner'],'personal')>300
            assert {table:db.execute('SELECT count(*) n FROM '+table).fetchone()['n'] for table in initial}==initial
        budget.configure(store,principal,'personal',{'token_limit':100000})
        source=dict(owner=principal['owner'],scope='personal',payload='synthetic input')
        with store.db() as db:
            aid=budget.reserve(db,source,'synthetic','known')
            reserved=db.execute('SELECT reservation FROM model_attempts WHERE id=?',(aid,)).fetchone()['reservation']
            assert reserved==len(source['payload'].encode())+12000+extra_reservation(db,principal['owner'],'personal')
            budget.settle(db,aid,{'total_tokens':123})
        assert budget.status(store,principal,'personal')['tokens_spent']==123
        with store.db() as db:
            unknown=budget.reserve(db,source,'synthetic','unknown')
            unknown_reserve=db.execute('SELECT reservation FROM model_attempts WHERE id=?',(unknown,)).fetchone()['reservation']
            budget.settle(db,unknown,{})
        state=budget.status(store,principal,'personal')
        assert state['tokens_spent']==123+unknown_reserve and state['unresolved_attempts']==1
        # Two synthetic attempts: a lost crash usage retains its first reserve;
        # the latest measured attempt settles only its own reserve.
        from pipeline.memory_center.bulk import Bulk, RESERVE_TOKENS
        from pipeline.memory_center.claude import PARSER_VERSION
        source_id=store.ingest(principal,dict(source_key='synthetic-bulk-budget',
            processing_policy='archive',messages=[dict(id='1',role='user',text='合成预算演练资料')]))['id']
        with store.db() as db:
            job_id=db.execute('SELECT id FROM jobs WHERE source_id=?',(source_id,)).fetchone()['id']
            reserve=RESERVE_TOKENS+extra_reservation(db,principal['owner'],'personal')
            db.execute('INSERT INTO bulk_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('synthetic-batch',principal['owner'],'synthetic-archive','personal','paused',100000,2*reserve,1,0,1,0,0,0))
            db.execute('INSERT INTO bulk_batch_parsers VALUES(?,?)',('synthetic-batch',PARSER_VERSION))
            db.execute('INSERT INTO bulk_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('synthetic-segment','synthetic-batch','synthetic-conversation',0,'synthetic-source','[]',
                 'conversation','sample','queued',job_id,0,2,2*reserve,0,None,0))
            db.execute("UPDATE jobs SET state='failed',attempts=2,usage=? WHERE id=?",(json.dumps({'total_tokens':200}),job_id))
        Bulk(store).tick()
        with store.db() as db:
            assert db.execute("SELECT tokens_spent FROM bulk_batches WHERE id='synthetic-batch'").fetchone()['tokens_spent']==reserve+200
            row=db.execute("SELECT reserved_tokens,spent_tokens FROM bulk_segments WHERE id='synthetic-segment'").fetchone()
            assert row['reserved_tokens']==0 and row['spent_tokens']==reserve+200
            # Delete only explicitly synthetic rehearsal rows before base invariant check.
            db.execute("DELETE FROM bulk_segments WHERE id='synthetic-segment'")
            db.execute("DELETE FROM bulk_batch_parsers WHERE batch_id='synthetic-batch'")
            db.execute("DELETE FROM bulk_batches WHERE id='synthetic-batch'")
            db.execute('DELETE FROM jobs WHERE id=?',(job_id,));db.execute('DELETE FROM sources WHERE id=?',(source_id,))
        # Migration rollback removes only its own tables; retained synthetic base data remains.
        with store.db() as db:
            for table in ('system_config_events','system_config_active','system_config_versions'):
                db.execute('DROP TABLE '+table)
            assert {table:db.execute('SELECT count(*) n FROM '+table).fetchone()['n'] for table in ('records','sources','jobs','bulk_batches')}=={k:initial[k] for k in ('records','sources','jobs','bulk_batches')}
            db.executescript(migration.read_text())
        assert listing(store,principal,'personal')['versions']==[]
    return dict(database_prefix='memory_config_scratch_', migration_idempotent=True,
                literal_sql_double_precision_verified=True,
                concurrent_activation='one winner, one conflict', transaction_rollback=True,
                config_rollback_audited=True, authorization_isolated=True,
                known_usage_settled=123, unknown_usage_kept_reserved=True,
                bulk_crash_reservation_preserved=True,
                ddl_rollback_and_reapply=True, model_calls=0, production_writes=0)

if __name__=='__main__':
    dsn=os.environ.get('QIU_MEMORY_SCRATCH_DSN')
    if not dsn:raise SystemExit('QIU_MEMORY_SCRATCH_DSN must name an empty disposable scratch database')
    print(json.dumps(check(dsn),ensure_ascii=False,sort_keys=True))

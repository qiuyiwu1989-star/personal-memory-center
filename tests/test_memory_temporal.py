"""Synthetic explicit change audit and deterministic projection recovery."""
import sqlite3
import unittest
from pathlib import Path
import test_memory_center as baseline
from pipeline.memory_center import temporal,owner_memory
from pipeline.memory_center.core import Invalid,Conflict
from pipeline.memory_center.governance import review,context
from pipeline.memory_center.documents import define_topic,build_documents

class TemporalTest(unittest.TestCase):
    setUp=baseline.MemoryTest.setUp
    tearDown=baseline.MemoryTest.tearDown

    def body(self,key='synthetic-create',**changes):
        return {'request_key':key,'statement':'Synthetic original statement.',
                'governance':{'holder':'owner:q','subject_id':'owner:q','as_of':'2000-01-01'},**changes}

    def setup_projection(self):
        temporal.setup(self.store)
        define_topic(self.store,self.owner,'personal','synthetic-topic','合成主题',['owner-memory:'])

    def revise(self,first,**changes):
        return owner_memory.revise(self.store,self.owner,'personal',first['id'],
            self.body('synthetic-revise',revision=1,governance_revision=1,**changes))

    def test_absent_migration_legacy_works_explicit_changes_rollback(self):
        first=owner_memory.create(self.store,self.owner,'personal',self.body())
        self.assertEqual(temporal.status(self.store,self.owner,'personal')['state'],'unavailable')
        with self.assertRaises(Invalid):self.revise(first,change_kind='interpretation_correction')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],1)
            self.assertEqual(db.execute('SELECT lifecycle FROM records WHERE id=?',(first['id'],)).fetchone()['lifecycle'],'active')
        self.assertTrue(owner_memory.create(self.store,self.owner,'personal',self.body())['duplicate'])

    def test_viewpoint_change_explicit_period_and_immutable_system_audit(self):
        self.setup_projection()
        first=owner_memory.create(self.store,self.owner,'personal',self.body())
        second=self.revise(first,statement='Synthetic revised statement.',change_kind='viewpoint_change',
                           previous_valid_until='2001-01-01',governance={'as_of':'2001-01-01'})
        with self.store.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM memory_change_events ORDER BY recorded_at')]
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[-1]['previous_valid_until'],'2001-01-01')
            self.assertEqual(rows[-1]['valid_from'],'2001-01-01')
            self.assertEqual(rows[-1]['previous_retired_at'],rows[-1]['recorded_at'])
            self.assertEqual(rows[-1]['previous_record_id'],first['id'])
            # No fact period is silently copied to the old governance row.
            self.assertIsNone(db.execute('SELECT valid_until FROM record_governance WHERE record_id=?',(first['id'],)).fetchone()['valid_until'])
        self.assertTrue(self.revise(first,statement='Synthetic revised statement.',change_kind='viewpoint_change',
                           previous_valid_until='2001-01-01',governance={'as_of':'2001-01-01'})['duplicate'])
        self.assertEqual(temporal.status(self.store,self.owner,'personal')['generation'],2)
        with self.assertRaises(Conflict):self.revise(first,request_key='different',change_kind='metadata_update')

    def test_projection_refresh_is_idempotent_no_new_judgment(self):
        self.setup_projection()
        first=owner_memory.create(self.store,self.owner,'personal',self.body())
        self.assertTrue(temporal.status(self.store,self.owner,'personal')['stale'])
        before=build_documents(self.store,self.owner,'personal')
        self.assertFalse(temporal.status(self.store,self.owner,'personal')['stale'])
        second=self.revise(first,statement='Synthetic changed assertion.',change_kind='interpretation_correction')
        self.assertTrue(temporal.status(self.store,self.owner,'personal')['stale'])
        after=build_documents(self.store,self.owner,'personal')
        self.assertGreater(after[0]['revision'],before[0]['revision'])
        self.assertIn('Synthetic changed assertion',after[0]['markdown'])
        self.assertEqual(after[0]['revision'],build_documents(self.store,self.owner,'personal')[0]['revision'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],2)
            self.assertEqual(db.execute('SELECT count(*) n FROM memory_change_events').fetchone()['n'],2)
        self.assertEqual(temporal.status(self.store,self.owner,'personal')['generation'],2)

    def test_failed_projection_refresh_stays_dirty_then_retries(self):
        from unittest.mock import patch
        self.setup_projection()
        owner_memory.create(self.store,self.owner,'personal',self.body())
        with patch('pipeline.memory_center.documents.render',side_effect=OSError('synthetic projection failure')):
            with self.assertRaises(OSError):build_documents(self.store,self.owner,'personal')
        self.assertTrue(temporal.status(self.store,self.owner,'personal')['stale'])
        build_documents(self.store,self.owner,'personal')
        self.assertFalse(temporal.status(self.store,self.owner,'personal')['stale'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM memory_change_events').fetchone()['n'],1)

    def test_unknown_period_not_inferred_review_stale_lock_and_agent_denial(self):
        self.setup_projection()
        first=owner_memory.create(self.store,self.owner,'personal',self.body(governance={}))
        review(self.store,self.owner,first['id'],{'revision':1,'state':'rejected','change_kind':'withdrawal'})
        with self.store.db() as db:
            rows=list(db.execute('SELECT valid_from,valid_until,previous_valid_until FROM memory_change_events'))
            self.assertTrue(all(all(r[k] is None for k in r.keys()) for r in rows))
        with self.assertRaises(Conflict):review(self.store,self.owner,first['id'],{'revision':1,'state':'candidate','change_kind':'metadata_update'})
        with self.assertRaises(PermissionError):review(self.store,dict(self.owner,trusted_user=False),first['id'],{'revision':2,'state':'candidate'})
        with self.assertRaises(PermissionError):temporal.status(self.store,dict(self.owner,scopes=['project:demo']),'personal')
        self.assertEqual(context(self.store,self.owner,'personal','')['records'],[])

    def test_same_record_review_uses_old_fact_period_not_new_start(self):
        self.setup_projection()
        first=owner_memory.create(self.store,self.owner,'personal',self.body())
        review(self.store,self.owner,first['id'],{'revision':1,'state':'candidate','as_of':'2002-01-01',
               'change_kind':'viewpoint_change','previous_valid_until':'2001-01-01'})
        with self.store.db() as db:
            row=db.execute("SELECT valid_from,previous_valid_until FROM memory_change_events WHERE change_kind='viewpoint_change'").fetchone()
            self.assertEqual(row['valid_from'],'2002-01-01')
            self.assertEqual(row['previous_valid_until'],'2001-01-01')

    def test_period_constraints_and_migration_restore_rehearsal(self):
        # Clone an old synthetic store, apply SQL twice, leave original untouched.
        legacy=owner_memory.create(self.store,self.owner,'personal',self.body('synthetic-legacy',governance={}))
        clone=Path(self.tmp.name)/'synthetic-restored.sqlite3'
        with sqlite3.connect(self.store.path) as source,sqlite3.connect(clone) as target:source.backup(target)
        sql=(Path(__file__).parents[1]/'pipeline/memory_center/migrations/007_temporal_projection_audit.sql').read_text()
        with sqlite3.connect(clone) as db:
            db.executescript(sql);db.executescript(sql)
            self.assertEqual(db.execute('SELECT count(*) FROM memory_change_events').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0],1)
            self.assertIsNone(db.execute('SELECT as_of FROM record_governance WHERE record_id=?',(legacy['id'],)).fetchone()[0])
        with self.store.db() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='memory_change_events'").fetchone())
        self.setup_projection();first=owner_memory.create(self.store,self.owner,'personal',self.body())
        for changes in ({'change_kind':'metadata_update','previous_valid_until':'2001-01-01'},
                        {'change_kind':'viewpoint_change','previous_valid_until':'1999-01-01'},
                        {'change_kind':'viewpoint_change','previous_valid_until':'20010101'}):
            with self.assertRaises(Invalid):self.revise(first,**changes)
        self.assertEqual(temporal.status(self.store,self.owner,'personal')['generation'],1)

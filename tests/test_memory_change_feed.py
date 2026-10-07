"""Synthetic downstream checkpoint contracts; no network or model API calls."""
import base64
from contextlib import contextmanager
import datetime
import json
import unittest
from unittest.mock import patch
import test_memory_center as baseline
from pipeline.memory_center import change_feed, source_lifecycle, temporal
from pipeline.memory_center.core import Conflict, Invalid, encoded
from pipeline.memory_center.governance import review


class ChangeFeedTest(unittest.TestCase):
    setUp = baseline.MemoryTest.setUp
    tearDown = baseline.MemoryTest.tearDown
    body = baseline.MemoryTest.body
    ingest = baseline.MemoryTest.ingest
    rows = baseline.MemoryTest.rows

    def read(self, **kwargs):
        return change_feed.changes(self.store, self.owner, 'personal', **kwargs)

    def drain(self, first=None, **kwargs):
        result = first or self.read(**kwargs)
        all_items = list(result['items'])
        while result['next_cursor']:
            result = self.read(cursor=result['next_cursor'], **kwargs)
            all_items.extend(result['items'])
        return result, all_items

    def test_empty_checkpoint_is_stable_and_has_no_runtime_writes(self):
        with self.store.db() as db:
            before = list(db.execute("SELECT name FROM sqlite_master ORDER BY name"))
        first = self.read()
        self.assertEqual(first['items'], [])
        self.assertEqual(first['total'], 0)
        self.assertTrue(first['requires_context_refresh'])
        second = self.read(cursor=first['checkpoint'])
        self.assertFalse(second['changed'])
        self.assertFalse(second['requires_context_refresh'])
        self.assertEqual(second['scope_revision'], first['scope_revision'])
        with self.store.db() as db:
            self.assertEqual(list(db.execute("SELECT name FROM sqlite_master ORDER BY name")), before)
        self.assertEqual(self.model.calls, 0)

    def test_new_candidate_appears_without_temporal_event_table(self):
        first = self.read()
        source = self.ingest(messages=[{'id': '1', 'role': 'user', 'text': 'Synthetic private candidate.'}])
        result = self.read(cursor=first['checkpoint'])
        self.assertTrue(result['requires_context_refresh'])
        self.assertEqual(result['items'][0]['state'], 'candidate')
        self.assertEqual(result['items'][0]['source_id'], source['id'])
        self.assertEqual(result['coverage'], 'current_record_metadata_only')
        self.assertNotIn('Synthetic private', encoded(result))
        self.assertNotIn('statement', encoded(result))
        self.assertNotIn('quote', encoded(result))
        with self.store.db() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='memory_change_events'").fetchone())

    def test_correction_and_rejection_change_checkpoint(self):
        self.ingest()
        old = self.rows()[0]
        first = self.read()
        newer = self.store.correct(self.owner, old['id'], {'revision': 1, 'statement': 'Synthetic correction.'})
        result = self.read(cursor=first['checkpoint'])
        self.assertTrue(result['requires_context_refresh'])
        states = {row['id']: row for row in result['items']}
        self.assertEqual(states[old['id']]['lifecycle'], 'superseded')
        self.assertEqual(states[newer['id']]['supersedes'], old['id'])
        self.assertEqual(states[newer['id']]['state'], 'candidate')
        review(self.store, self.owner, newer['id'], {'revision': 1, 'state': 'rejected'})
        rejected = self.read(cursor=result['checkpoint'])
        self.assertTrue(rejected['changed'])
        self.assertEqual(next(row for row in rejected['items'] if row['id'] == newer['id'])['state'], 'rejected')

    def test_source_withdrawal_changes_record_metadata_and_empty_source_is_outside_coverage(self):
        source = self.ingest()
        first = self.read()
        source_lifecycle.withdraw(self.store, self.owner, 'personal', source['id'])
        result = self.read(cursor=first['checkpoint'])
        self.assertTrue(result['items'][0]['source_withdrawn'])
        self.assertTrue(result['requires_context_refresh'])
        empty = self.store.ingest(self.owner, self.body(source_key='synthetic-empty-archive', processing_policy='archive'))
        source_lifecycle.withdraw(self.store, self.owner, 'personal', empty['id'])
        self.assertFalse(self.read(cursor=result['checkpoint'])['changed'])

    def test_source_withdrawal_supported_without_temporal_migration(self):
        source = self.ingest()
        initial = self.read()
        source_lifecycle.withdraw(self.store, self.owner, 'personal', source['id'])
        self.assertNotEqual(self.read()['scope_revision'], initial['scope_revision'])
        self.assertEqual(temporal.status(self.store, self.owner, 'personal')['state'], 'unavailable')

    def test_pagination_visits_every_record_once_at_same_revision(self):
        self.ingest(messages=[{'id': str(i), 'role': 'user', 'text': f'Synthetic candidate {i}.'} for i in range(11)])
        first = self.read(limit=2)
        self.assertIsNone(first['checkpoint'])
        final, items = self.drain(first, limit=2)
        self.assertEqual(len(items), 11)
        self.assertEqual(len({row['id'] for row in items}), 11)
        self.assertEqual([row['id'] for row in items], sorted(row['id'] for row in items))
        self.assertEqual(first['scope_revision'], final['scope_revision'])
        self.assertIsNotNone(final['checkpoint'])
        self.assertFalse(self.read(cursor=final['checkpoint'])['changed'])

    def test_response_budget_includes_tokens_and_never_silently_skips(self):
        self.ingest(messages=[{'id': str(i), 'role': 'user', 'text': f'Synthetic budget candidate {i}.'} for i in range(7)])
        for budget in (1000, 1200, 1600, 4000, 16000):
            result = self.read(max_chars=budget)
            seen = []
            while True:
                self.assertLessEqual(len(encoded(result)), budget)
                seen.extend(row['id'] for row in result['items'])
                if not result['next_cursor']:
                    break
                result = self.read(cursor=result['next_cursor'], max_chars=budget)
            self.assertEqual(len(seen), 7)
            self.assertEqual(len(set(seen)), 7)
        for budget in (999, 16001, True, '4000'):
            with self.assertRaises(Invalid): self.read(max_chars=budget)
        for limit in (0, 101, True, '50'):
            with self.assertRaises(Invalid): self.read(limit=limit)

    def test_concurrent_new_record_invalidates_page_instead_of_skipping(self):
        self.ingest(messages=[{'id': str(i), 'role': 'user', 'text': f'Synthetic page candidate {i}.'} for i in range(3)])
        first = self.read(limit=1)
        self.ingest(source_key='synthetic-addition')
        with self.assertRaises(Conflict): self.read(cursor=first['next_cursor'])
        final, items = self.drain(limit=1)
        self.assertEqual(len(items), 4)
        self.assertIsNotNone(final['checkpoint'])

    def test_concurrent_review_invalidates_continuation(self):
        self.ingest(messages=[{'id': str(i), 'role': 'user', 'text': f'Synthetic reviewed candidate {i}.'} for i in range(3)])
        first = self.read(limit=1)
        review(self.store, self.owner, self.rows()[0]['id'], {'revision': 0, 'state': 'rejected'})
        with self.assertRaises(Conflict): self.read(cursor=first['next_cursor'])

    def test_tied_and_backdated_events_do_not_skip_new_records(self):
        with patch('pipeline.memory_center.core.time.time', return_value=1000):
            self.ingest()
        first = self.read()
        with patch('pipeline.memory_center.core.time.time', return_value=1000):
            self.ingest(source_key='synthetic-tied')
        second = self.read(cursor=first['checkpoint'])
        self.assertEqual(second['total'], 2)
        with patch('pipeline.memory_center.core.time.time', return_value=999):
            self.ingest(source_key='synthetic-backdated')
        third = self.read(cursor=second['checkpoint'])
        self.assertEqual(third['total'], 3)
        self.assertTrue(third['requires_context_refresh'])

    def test_scope_owner_and_principal_binding_and_revocation(self):
        self.ingest()
        first = self.read()
        token = first['checkpoint']
        for principal, scope in ((self.owner, 'project:demo'),
                                 (dict(self.owner, owner='synthetic-other'), 'personal'),
                                 (dict(self.owner, id='synthetic-other-agent'), 'personal')):
            with self.assertRaises(Invalid):
                change_feed.changes(self.store, principal, scope, cursor=token)
        for principal in (dict(self.owner, actions=[]), dict(self.owner, scopes=['project:demo'])):
            with self.assertRaises(PermissionError):
                change_feed.changes(self.store, principal, 'personal', cursor=token)
        other = change_feed.changes(self.store, dict(self.owner, owner='synthetic-other'), 'personal')
        self.assertEqual(other['total'], 0)
        self.assertNotEqual(first['scope_revision'], other['scope_revision'])

    def test_foreign_writes_do_not_invalidate_scope(self):
        first = self.read()
        self.ingest(scope='project:demo')
        self.assertFalse(self.read(cursor=first['checkpoint'])['changed'])

    def test_malformed_and_out_of_range_cursors_fail_explicitly(self):
        first = self.read()
        for token in ('', 'not:base64', 'x' * 1001, 'e30', 4, True):
            with self.assertRaises(Invalid): self.read(cursor=token)
        decoded = json.loads(base64.urlsafe_b64decode(first['checkpoint'] + '=='))
        forged = change_feed._cursor(decoded['b'], decoded['r'], 1000)
        with self.assertRaises(Conflict): self.read(cursor=forged)
        for offset in (-1, 0, True, '1'):
            malformed = change_feed._cursor(decoded['b'], decoded['r'], offset)
            with self.assertRaises(Invalid): self.read(cursor=malformed)

    def test_date_transition_invalidates_even_without_an_event(self):
        self.ingest()
        rid = self.rows()[0]['id']
        class DayOne(datetime.date):
            @classmethod
            def today(cls): return cls(2000, 1, 1)
        class DayTwo(datetime.date):
            @classmethod
            def today(cls): return cls(2000, 1, 2)
        with patch('pipeline.memory_center.change_feed.datetime.date', DayOne):
            review(self.store, self.owner, rid, {'revision': 0, 'state': 'verified', 'holder': 'owner:q',
                  'subject_id': 'owner:q', 'as_of': '2000-01-01', 'valid_until': '2000-01-02'})
            first = self.read()
        with patch('pipeline.memory_center.change_feed.datetime.date', DayTwo):
            second = self.read(cursor=first['checkpoint'])
        self.assertTrue(second['requires_context_refresh'])
        self.assertEqual(second['refresh_after_seconds'], 300)
        self.assertEqual(first['items'], second['items'])
        self.assertNotEqual(first['scope_revision'], second['scope_revision'])

    def test_translation_metadata_and_legacy_migration_availability_change_revision(self):
        self.ingest()
        first = self.read()
        rid = self.rows()[0]['id']
        with self.store.db() as db:
            db.execute('INSERT INTO record_translations VALUES(?,?,?,?,?)',
                       (rid, 'zh', 'Synthetic private translation.', 'synthetic-run', 123))
        translated = self.read(cursor=first['checkpoint'])
        self.assertTrue(translated['changed'])
        self.assertNotIn('Synthetic private translation', encoded(translated))
        with self.store.db() as db: db.execute('DROP TABLE source_withdrawals')
        legacy = self.read(cursor=translated['checkpoint'])
        self.assertTrue(legacy['changed'])
        with self.store.db() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='source_withdrawals'").fetchone())

    def test_read_only_sql_and_postgres_repeatable_read_contract(self):
        # This is an adapter-contract test, not a live PostgreSQL integration.
        self.ingest()
        statements = []
        with self.store.db() as sqlite:
            class ReadProxy:
                def execute(self, sql, params=()):
                    statements.append(sql)
                    if sql.startswith('SET TRANSACTION'):
                        return sqlite.execute('BEGIN')
                    if not sql.startswith('SELECT '):
                        raise AssertionError('read must not write: ' + sql)
                    if 'payload' in sql or '.statement' in sql or '.quote' in sql or 't.text' in sql:
                        raise AssertionError('read must not fetch evidence text')
                    return sqlite.execute(sql, params)
            @contextmanager
            def fake_db():
                yield ReadProxy()
            with patch.object(self.store, 'dsn', 'synthetic-postgres-contract'), \
                 patch.object(self.store, 'db', fake_db), \
                 patch('pipeline.memory_center.change_feed._exists', return_value=True):
                self.read()
        self.assertEqual(statements[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        self.assertTrue(statements[1].startswith('SELECT '))

    def test_read_does_not_use_text_snapshot_or_model(self):
        self.ingest()
        calls = self.model.calls
        with patch.object(self.store, 'snapshot', side_effect=AssertionError('text snapshot forbidden')):
            self.read()
        self.assertEqual(self.model.calls, calls)


if __name__ == '__main__': unittest.main()

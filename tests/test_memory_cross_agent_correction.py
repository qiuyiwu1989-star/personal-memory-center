"""Synthetic end-to-end owner correction visible to two independent MCP readers."""
import datetime
import hashlib
import json
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
import test_memory_center as fixture
from pipeline.memory_center.service import create_app
from pipeline.memory_center import temporal


class CrossAgentCorrectionTest(unittest.TestCase):
    setUp = fixture.MemoryTest.setUp
    tearDown = fixture.MemoryTest.tearDown

    def protocol(self):
        grants = [dict(self.owner, token_sha256=hashlib.sha256(b'synthetic-owner-protocol').hexdigest())]
        for name in ('alpha', 'beta'):
            grants.append(dict(self.owner, id='synthetic-'+name, actions=['read'], trusted_user=False,
                               token_sha256=hashlib.sha256(('synthetic-'+name).encode()).hexdigest()))
        return grants, TestClient(create_app(self.store, lambda: list(grants), self.model, run_worker=False),
                                 base_url='http://127.0.0.1:5078')

    def post(self, client, path, body):
        response = client.post(self.prefix+path, json=body,
                               headers={'Authorization': 'Bearer synthetic-owner-protocol'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def read(self, client, name):
        return client.post('/mcp/', headers={'Authorization': 'Bearer synthetic-'+name,
                           'Accept': 'application/json, text/event-stream'}, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': 'memory_context', 'arguments': {'scope': 'personal', 'query': '', 'max_chars': 6000}}})

    def contexts(self, client):
        values = []
        for name in ('alpha', 'beta'):
            response = self.read(client, name)
            self.assertEqual(response.status_code, 200)
            result = response.json()['result']
            self.assertFalse(result.get('isError', False), result)
            values.append(result.get('structuredContent') or json.loads(result['content'][0]['text']))
        self.assertEqual(values[0], values[1])
        return values[0]

    def create(self, client, **governance):
        return self.post(client, '/owner-records', {'scope': 'personal', 'request_key': 'synthetic-create',
            'statement': 'Synthetic preference A.', 'explicit_confirmation': True,
            'governance': self.verified(**governance)})

    def verified(self, **fields):
        return dict(state='verified', holder='owner:q', subject_id='owner:q', as_of='2000-01-01', **fields)

    def revise(self, client, initial):
        return self.post(client, '/records/'+initial['id']+'/revise', {'scope': 'personal',
            'request_key': 'synthetic-revise', 'revision': 1, 'governance_revision': 1,
            'statement': 'Synthetic preference B.'})

    def review(self, client, revised, revision=1, **fields):
        return self.post(client, '/records/'+revised['id']+'/governance', {'revision': revision, **fields})

    def test_revision_review_withdrawal_preserves_history_without_old_fact_fallback(self):
        grants, client = self.protocol()
        with client as c:
            initial = self.create(c)
            first = self.contexts(c)
            self.assertEqual([r['id'] for r in first['records']], [initial['id']])
            self.assertEqual(first['records'][0]['source_id'], initial['source_id'])
            revised = self.revise(c, initial)
            pending = self.contexts(c)
            self.assertEqual(pending['records'], [])
            self.assertNotEqual(first['context_revision'], pending['context_revision'])
            self.review(c, revised, **self.verified())
            approved = self.contexts(c)
            row = approved['records'][0]
            self.assertEqual((row['id'], row['statement'], row['revision']),
                             (revised['id'], 'Synthetic preference B.', 2))
            self.assertEqual(row['source_id'], revised['source_id'])
            self.assertNotEqual(row['source_id'], initial['source_id'])
            self.assertEqual(row['message_id'], 'owner-statement')
            self.assertNotEqual(first['context_revision'], approved['context_revision'])
            self.review(c, revised, revision=2, state='rejected')
            withdrawn = self.contexts(c)
            self.assertEqual(withdrawn['records'], [])
            self.assertNotEqual(approved['context_revision'], withdrawn['context_revision'])
            history = c.get(self.prefix+'/records?scope=personal&history=1', headers={
                'Authorization': 'Bearer synthetic-owner-protocol'}).json()['records']
            by_id = {r['id']: r for r in history}
            self.assertEqual(by_id[initial['id']]['lifecycle'], 'superseded')
            self.assertEqual(by_id[initial['id']]['governance']['state'], 'verified')
            self.assertEqual(by_id[revised['id']]['governance']['state'], 'rejected')
            with self.store.db() as db:
                sources = db.execute('SELECT id,payload FROM sources').fetchall()
                self.assertEqual(len(sources), 2)
                self.assertEqual({json.loads(r['payload'])[0]['text'] for r in sources},
                                 {'Synthetic preference A.', 'Synthetic preference B.'})
        self.assertEqual(self.model.calls, 0)

    def test_exclusive_valid_until_hides_revision_for_both_readers_without_resurrecting_old(self):
        today = datetime.date.today()
        expiry = today+datetime.timedelta(days=1)
        class ExpiredDate(datetime.date):
            @classmethod
            def today(cls): return expiry
        grants, client = self.protocol()
        with client as c:
            initial = self.create(c)
            revised = self.revise(c, initial)
            self.review(c, revised, **self.verified(valid_until=expiry.isoformat()))
            valid = self.contexts(c)
            self.assertEqual([r['id'] for r in valid['records']], [revised['id']])
            with patch('pipeline.memory_center.governance.datetime.date', ExpiredDate):
                expired = self.contexts(c)
            self.assertEqual(expired['records'], [])
            self.assertNotEqual(valid['context_revision'], expired['context_revision'])
        self.assertEqual(self.model.calls, 0)

    def test_permission_revocation_is_per_reader_and_never_returns_previous_context(self):
        grants, client = self.protocol()
        with client as c:
            initial = self.create(c)
            prior = self.contexts(c)
            self.assertEqual(len(prior['records']), 1)
            grants[1] = dict(grants[1], scopes=['project:demo'])
            reduced = self.read(c, 'alpha')
            self.assertTrue(reduced.json()['result']['isError'])
            self.assertNotIn(initial['id'], reduced.text)
            grants[:] = [g for g in grants if g['id'] != 'synthetic-alpha']
            denied = self.read(c, 'alpha')
            self.assertEqual(denied.status_code, 401)
            self.assertNotIn(initial['id'], denied.text)
            allowed = self.read(c, 'beta').json()['result']
            data = allowed.get('structuredContent') or json.loads(allowed['content'][0]['text'])
            self.assertEqual(data, prior)
        self.assertEqual(self.model.calls, 0)

    def test_007_explicit_withdrawal_updates_two_readers_and_audits_no_inferred_period(self):
        temporal.setup(self.store)
        grants, client = self.protocol()
        with client as c:
            initial = self.create(c)
            before = self.contexts(c)
            self.review(c, initial, revision=1, state='rejected', change_kind='withdrawal')
            after = self.contexts(c)
            self.assertEqual(after['records'], [])
            self.assertNotEqual(before['context_revision'], after['context_revision'])
            with self.store.db() as db:
                event = db.execute("SELECT * FROM memory_change_events WHERE change_kind='withdrawal'").fetchone()
                self.assertEqual(event['record_id'], initial['id'])
                self.assertEqual(event['previous_record_id'], initial['id'])
                self.assertEqual(event['governance_revision'], 2)
                self.assertEqual(event['actor'], self.owner['id'])
                for field in ('valid_from', 'valid_until', 'previous_valid_until'):
                    self.assertIsNone(event[field])
                self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'], 1)
            self.assertTrue(temporal.status(self.store, self.owner, 'personal')['stale'])
        self.assertEqual(self.model.calls, 0)

    def test_007_inconsistent_withdrawal_and_stale_edit_rollback_without_audit(self):
        temporal.setup(self.store)
        grants, client = self.protocol()
        with client as c:
            initial = self.create(c)
            before = self.contexts(c)
            headers = {'Authorization': 'Bearer synthetic-owner-protocol'}
            review_path = self.prefix+'/records/'+initial['id']+'/governance'
            bad = c.post(review_path, headers=headers, json={
                'revision': 1, 'change_kind': 'withdrawal', **self.verified()})
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(self.contexts(c), before)
            # A second browser edited governance while the first held revision 1.
            self.review(c, initial, revision=1, **self.verified())
            current = self.contexts(c)
            stale = c.post(self.prefix+'/records/'+initial['id']+'/revise', headers=headers, json={
                'scope': 'personal', 'request_key': 'synthetic-stale', 'revision': 1,
                'governance_revision': 1, 'statement': 'Synthetic stale edit.',
                'change_kind': 'interpretation_correction'})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(self.contexts(c), current)
            bad_revision = c.post(self.prefix+'/records/'+initial['id']+'/revise', headers=headers, json={
                'scope': 'personal', 'request_key': 'synthetic-bad-withdrawal', 'revision': 1,
                'governance_revision': 2, 'change_kind': 'withdrawal',
                'explicit_confirmation': True, 'governance': self.verified()})
            self.assertEqual(bad_revision.status_code, 400)
            self.assertEqual(self.contexts(c), current)
            with self.store.db() as db:
                self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'], 1)
                self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'], 1)
                self.assertEqual(db.execute('SELECT count(*) n FROM memory_change_events').fetchone()['n'], 2)
                self.assertEqual(db.execute("SELECT count(*) n FROM memory_change_events WHERE change_kind='withdrawal'").fetchone()['n'], 0)
            self.assertEqual(temporal.status(self.store, self.owner, 'personal')['generation'], 2)
        self.assertEqual(self.model.calls, 0)

    def test_007_interpretation_correction_requires_review_and_preserves_audit_lineage(self):
        temporal.setup(self.store)
        grants, client = self.protocol()
        with client as c:
            initial = self.create(c)
            original = self.contexts(c)
            revised = self.post(c, '/records/'+initial['id']+'/revise', {
                'scope': 'personal', 'request_key': 'synthetic-explicit-correction',
                'revision': 1, 'governance_revision': 1,
                'statement': 'Synthetic corrected interpretation.',
                'change_kind': 'interpretation_correction'})
            self.assertEqual(self.contexts(c)['records'], [])
            self.review(c, revised, **self.verified())
            current = self.contexts(c)
            self.assertEqual([r['id'] for r in current['records']], [revised['id']])
            self.assertNotEqual(original['context_revision'], current['context_revision'])
            with self.store.db() as db:
                event = db.execute("SELECT * FROM memory_change_events WHERE change_kind='interpretation_correction'").fetchone()
                self.assertEqual(event['previous_record_id'], initial['id'])
                self.assertEqual(event['record_id'], revised['id'])
                self.assertIsNone(event['previous_valid_until'])
                self.assertEqual(db.execute('SELECT lifecycle FROM records WHERE id=?', (initial['id'],)).fetchone()['lifecycle'], 'superseded')
        self.assertEqual(self.model.calls, 0)


if __name__ == '__main__': unittest.main()

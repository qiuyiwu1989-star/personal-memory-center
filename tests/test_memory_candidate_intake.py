"""Explicitly synthetic upstream candidates; no provider/network/private data."""
import concurrent.futures
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pipeline.memory_center import candidate_intake, governance, source_lifecycle
from pipeline.memory_center.core import Store, Invalid, Conflict, encoded


class CandidateIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        candidate_intake.setup(self.store)
        self.scope = 'agent:synthetic-inbox'
        self.agent = {'id': 'synthetic-node', 'owner': 'synthetic-owner', 'trusted_user': False,
                      'scopes': [self.scope], 'actions': ['read', 'source_read', 'write', 'candidate_write'],
                      'archive_only': True}
        self.owner = dict(self.agent, id='synthetic-person', trusted_user=True,
                          actions=['read', 'source_read', 'write'])
        self.text = '合成前言🌱。合成决定仅针对演示项目。合成后文。'
        self.quote = '合成决定仅针对演示项目。'
        self.source = self.ingest()
        start = self.text.index(self.quote)
        self.claim = {'message_id': 'synthetic-message', 'quote': self.quote,
                      'start': start, 'end': start + len(self.quote),
                      'statement': '合成演示项目的待核实决定。', 'subject': '合成演示项目',
                      'topic': 'projects', 'kind': 'decision', 'client_candidate_id': 'synthetic-claim-1'}
        self.body = {'request_key': 'synthetic-request-1', 'source_id': self.source['id'], 'claims': [self.claim]}

    def ingest(self, principal=None, role='user', source_type='conversation', scope=None):
        return self.store.ingest(principal or self.agent, {
            'scope': scope or self.scope, 'source_key': 'synthetic-source-' + role,
            'processing_policy': 'archive', 'source_type': source_type,
            'messages': [{'id': 'synthetic-message', 'role': role, 'text': self.text}]})

    def submit(self, body=None, principal=None, scope=None):
        return candidate_intake.submit(self.store, principal or self.agent, scope or self.scope, body or self.body)

    def counts(self):
        with self.store.db() as db:
            return {table: db.execute('SELECT count(*) n FROM ' + table).fetchone()['n'] for table in
                    ('candidate_intake_receipts', 'candidate_intake_evidence', 'records', 'record_governance',
                     'events', 'sources', 'jobs', 'model_attempts')}

    def test_candidate_only_no_model_no_job_no_implicit_identity_or_dates(self):
        before = self.counts()
        receipt = self.submit()
        self.assertTrue(receipt['candidate_only']); self.assertFalse(receipt['facts_confirmed'])
        self.assertEqual(receipt['model_calls'], 0)
        row = self.store.snapshot(self.owner, self.scope)['records'][0]
        self.assertEqual(row['status'], 'source_reported'); self.assertEqual(row['lifecycle'], 'active')
        self.assertEqual(row['governance']['state'], 'candidate')
        for key in ('holder', 'subject_id', 'as_of', 'valid_until'):
            self.assertIsNone(row['governance'][key])
        self.assertFalse(governance.usable(row))
        self.assertEqual(governance.context(self.store, self.owner, self.scope, '')['records'], [])
        after = self.counts()
        for table in ('sources', 'jobs', 'model_attempts'):
            self.assertEqual(before[table], after[table])
        with self.store.db() as db:
            evidence = dict(db.execute('SELECT * FROM candidate_intake_evidence').fetchone())
        self.assertEqual(evidence['message_role'], 'user')
        self.assertEqual(evidence['quote_start'], self.claim['start'])

    def test_same_key_same_payload_replays_and_different_payload_conflicts(self):
        first = self.submit(); before = self.counts()
        repeated = self.submit()
        self.assertEqual(repeated, first | {'duplicate': True}); self.assertEqual(before, self.counts())
        different = copy.deepcopy(self.body); different['claims'][0]['statement'] = '另一合成候选'
        with self.assertRaises(Conflict): self.submit(different)
        self.assertEqual(before, self.counts())

    def test_concurrent_same_key_is_one_receipt_and_one_record(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            receipts = list(pool.map(lambda _: self.submit(), range(4)))
        self.assertEqual(sum(not row['duplicate'] for row in receipts), 1)
        self.assertEqual(len({row['id'] for row in receipts}), 1)
        self.assertEqual(self.counts()['records'], 1)

    def test_all_permissions_rechecked_on_duplicate_and_expiry(self):
        self.submit(); before = self.counts()
        for action in self.agent['actions']:
            denied = dict(self.agent, actions=[a for a in self.agent['actions'] if a != action])
            with self.subTest(action=action), self.assertRaises(PermissionError): self.submit(principal=denied)
        for fields in ({'enabled': False}, {'expires_at': 0}, {'expires_at': True}):
            with self.assertRaises(PermissionError): self.submit(principal=dict(self.agent, **fields))
        self.assertEqual(before, self.counts())

    def test_cross_owner_scope_principal_and_multiscope_denied(self):
        for principal in (dict(self.agent, owner='synthetic-other-owner'), dict(self.agent, id='synthetic-other-node')):
            with self.assertRaises(Invalid): self.submit(principal=principal)
        extra_scope = 'agent:synthetic-second-inbox'
        with self.assertRaises(Invalid): self.submit(principal=dict(self.agent, scopes=[extra_scope]), scope=extra_scope)
        with self.assertRaises(PermissionError): self.submit(principal=dict(self.agent, scopes=[self.scope, extra_scope]))
        with self.assertRaises(PermissionError): self.submit(principal=dict(self.agent, scopes=['personal']), scope='personal')
        self.assertEqual(self.counts()['records'], 0)

    def test_owner_may_submit_existing_source_without_candidate_write_but_never_confirms(self):
        receipt = self.submit(principal=self.owner)
        row = self.store.snapshot(self.owner, self.scope)['records'][0]
        self.assertEqual(row['id'], receipt['record_ids'][0]); self.assertEqual(row['status'], 'source_reported')
        self.assertEqual(row['governance']['state'], 'candidate')
        direct = self.ingest(principal=self.owner, role='external')
        receipt2 = self.submit(dict(self.body, source_id=direct['id'], request_key='synthetic-owner-source'), self.owner)
        self.assertEqual(receipt2['count'], 1)

    def test_source_roles_and_summary_classification_preserved(self):
        for role, source_type, expected in (('assistant', 'conversation', 'agent_suggested'),
                                            ('external', 'document', 'source_reported'),
                                            ('user', 'imported_summary', 'imported_summary')):
            with self.subTest(role=role, source_type=source_type):
                source = self.ingest(role=role, source_type=source_type)
                receipt = self.submit(dict(self.body, source_id=source['id'], request_key='synthetic-' + source_type + role))
                with self.store.db() as db:
                    row = dict(db.execute('SELECT status FROM records WHERE id=?', (receipt['record_ids'][0],)).fetchone())
                    ev = dict(db.execute('SELECT message_role FROM candidate_intake_evidence WHERE record_id=?', (receipt['record_ids'][0],)).fetchone())
                self.assertEqual(row['status'], expected); self.assertEqual(ev['message_role'], role)

    def test_spoofed_governance_roles_dates_and_unknown_fields_rejected(self):
        for key in ('verified', 'governance', 'holder', 'trusted_user', 'scope', 'status', 'source_role'):
            with self.subTest(top=key), self.assertRaises(Invalid): self.submit(dict(self.body, **{key: True}))
        for key in ('holder', 'subject_id', 'as_of', 'valid_until', 'state', 'status', 'role', 'priority', 'governance'):
            body = copy.deepcopy(self.body); body['claims'][0][key] = 'synthetic-spoof'
            with self.subTest(claim=key), self.assertRaises(Invalid): self.submit(body)
        self.assertEqual(self.counts()['records'], 0)

    def test_offsets_are_exact_unicode_code_points_not_utf16_and_bad_batch_is_atomic(self):
        # The seed emoji uses one Python/Unicode offset, two JavaScript UTF-16 units.
        for changes in ({'start': self.claim['start'] + 1}, {'end': len(self.text) + 1},
                        {'start': True}, {'start': -1}, {'end': self.claim['start']},
                        {'quote': '合成伪造引文'}, {'message_id': 'unknown'}):
            body = copy.deepcopy(self.body); body['claims'].append(dict(self.claim, client_candidate_id='synthetic-2', **changes))
            with self.subTest(changes=changes), self.assertRaises(Invalid): self.submit(body)
            self.assertEqual(self.counts()['records'], 0)
        self.assertEqual(self.submit()['count'], 1)

    def test_all_archived_text_used_even_above_ingest_or_read_limits(self):
        text = '合成较长正文。' * 6000 + self.quote
        with self.store.db() as db:
            payload = encoded([{'id': 'synthetic-message', 'role': 'user', 'text': text}])
            db.execute('UPDATE sources SET payload=?,digest=? WHERE id=?',
                       (payload, hashlib.sha256(payload.encode()).hexdigest(), self.source['id']))
        body = copy.deepcopy(self.body); body['claims'][0].update(start=text.index(self.quote), end=len(text))
        self.assertEqual(self.submit(body)['count'], 1)

    def test_multiple_claims_same_evidence_are_not_silently_deduplicated(self):
        body = copy.deepcopy(self.body)
        body['claims'].append(dict(self.claim, client_candidate_id='synthetic-claim-2'))
        receipt = self.submit(body)
        self.assertEqual(receipt['count'], 2); self.assertEqual(len(set(receipt['record_ids'])), 2)
        self.assertEqual(self.counts()['records'], 2)
        body['request_key'] = 'synthetic-repeated-client-id'
        body['claims'][1]['client_candidate_id'] = body['claims'][0]['client_candidate_id']
        with self.assertRaises(Invalid): self.submit(body)

    def test_receipt_and_records_roll_back_after_mid_transaction_failure(self):
        body = copy.deepcopy(self.body); body['claims'].append(dict(self.claim, client_candidate_id='synthetic-2'))
        before = self.counts()
        with patch('pipeline.memory_center.candidate_intake.uid', side_effect=['synthetic-r1', 'synthetic-r2', 'synthetic-e1', RuntimeError('synthetic failure')]):
            with self.assertRaises(RuntimeError): self.submit(body)
        self.assertEqual(before, self.counts())
        self.assertEqual(self.submit(body)['count'], 2)

    def test_withdrawn_source_cannot_submit_or_replay_receipt(self):
        receipt = self.submit()
        source_lifecycle.withdraw(self.store, self.owner, self.scope, self.source['id'], '合成撤回')
        before = self.counts()
        with self.assertRaises(Conflict): self.submit()
        with self.assertRaises(Conflict): self.submit(dict(self.body, request_key='synthetic-after-withdraw'))
        self.assertEqual(before, self.counts())
        listed = candidate_intake.listing(self.store, self.owner, self.scope)['receipts'][0]
        self.assertEqual(listed['source_state'], 'withdrawn'); self.assertEqual(listed['id'], receipt['id'])

    def test_owner_listing_bounded_private_and_current_governance_visible(self):
        receipts = [self.submit(dict(self.body, request_key='synthetic-page-' + str(i))) for i in range(3)]
        rid = receipts[-1]['record_ids'][0]
        governance.review(self.store, self.owner, rid, {'revision': 0, 'state': 'rejected', 'note': '合成拒绝原因'})
        limited_owner = dict(self.owner, actions=['read'])
        page = candidate_intake.listing(self.store, limited_owner, self.scope, limit=2)
        self.assertEqual(page['total'], 3); self.assertEqual(page['next_offset'], 2)
        self.assertEqual(len(page['receipts']), 2)
        serialized = encoded(page)
        for hidden in (self.quote, self.text, self.claim['statement'], self.claim['subject'], '合成拒绝原因', 'synthetic-page-'):
            self.assertNotIn(hidden, serialized)
        self.assertEqual(page['receipts'][0]['records'][0]['state'], 'rejected')
        tail = candidate_intake.listing(self.store, limited_owner, self.scope, offset=2, limit=2)
        self.assertEqual(len(tail['receipts']), 1); self.assertIsNone(tail['next_offset'])
        with self.assertRaises(PermissionError): candidate_intake.listing(self.store, self.agent, self.scope)
        other = candidate_intake.listing(self.store, dict(self.owner, owner='synthetic-other-owner'), self.scope)
        self.assertEqual(other['total'], 0)

    def test_unavailable_schema_read_does_not_create_tables(self):
        with self.store.db() as db:
            db.execute('DROP TABLE candidate_intake_evidence'); db.execute('DROP TABLE candidate_intake_receipts')
        status = candidate_intake.listing(self.store, self.owner, self.scope)
        self.assertFalse(status['supported']); self.assertIsNone(status['total'])
        with self.assertRaises(Invalid): self.submit()
        with self.store.db() as db: self.assertFalse(candidate_intake.available(self.store, db))

    def test_literal_migration_preserves_epoch_precision_and_replays(self):
        # SQLite keeps declared type names, so this catches the psql REAL versus
        # PostgreSQL adapter DOUBLE PRECISION mismatch before a PG rehearsal.
        migration = Path(__file__).resolve().parents[1] / 'pipeline/memory_center/migrations/010_candidate_intake.sql'
        with self.store.db() as db:
            db.executescript(migration.read_text()); db.executescript(migration.read_text())
            columns = {row['name']: row['type'] for row in db.execute('PRAGMA table_info(candidate_intake_receipts)')}
            self.assertEqual(columns['created'], 'DOUBLE PRECISION')
            precision_time = 1700000000.125
            with patch('pipeline.memory_center.candidate_intake.time.time', return_value=precision_time):
                receipt = self.submit()
            self.assertEqual(receipt['created'], precision_time)
            stored = db.execute('SELECT created FROM candidate_intake_receipts WHERE id=?', (receipt['id'],)).fetchone()
            self.assertEqual(stored['created'], precision_time)

    def test_cardinality_and_paging_bounds(self):
        for claims in ([], [dict(self.claim, client_candidate_id=str(i)) for i in range(21)]):
            with self.assertRaises(Invalid): self.submit(dict(self.body, claims=claims))
        for offset, limit in ((-1, 20), (True, 20), (0, 0), (0, 101), (0, True)):
            with self.assertRaises(Invalid): candidate_intake.listing(self.store, self.owner, self.scope, offset, limit)


if __name__ == '__main__': unittest.main()

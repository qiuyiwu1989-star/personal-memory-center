"""Only synthetic inputs: lossless framing, roles, retries and real Store limits."""
import json
import tempfile
import unittest

from pipeline.memory_center.core import Invalid, Store, encoded
from pipeline.memory_center.import_adapter import prepare_imports


class ImportAdapterTest(unittest.TestCase):
    def prepare(self, messages, **kwargs):
        return prepare_imports('synthetic://conversation/1', messages,
                               scope='agent:synthetic-inbox', **kwargs)

    def test_whole_messages_roles_dates_and_100_limit(self):
        messages = [{'id': str(i), 'role': ('user', 'assistant', 'external')[i % 3],
                     'text': '合成观点\n"引用"\\🙂', 'created_at': '2026-01-01T00:00:00Z'}
                    for i in range(205)]
        payloads = self.prepare(messages, source_type='conversation')
        self.assertEqual([len(p['messages']) for p in payloads], [100, 100, 5])
        self.assertEqual([m for p in payloads for m in p['messages']], messages)
        self.assertEqual(self.prepare(messages, source_type='conversation'), payloads)
        self.assertTrue(all(p['processing_policy'] == 'archive' for p in payloads))

    def test_single_long_message_exact_reassembly_and_original_locator(self):
        original = {'id': 'synthetic-long', 'role': 'assistant', 'text': ('🙂\\\n"合成"' * 12000),
                    'created_at': '2026-01-01', 'source_title': '合成会议'}
        parts = self.prepare([original], source_metadata={'original_ref': 'synthetic://raw/1',
                             'locator': 'line-10', 'parser_version': 'synthetic-parser'})
        self.assertGreater(len(parts), 1)
        cursor = 0
        for part in parts:
            message = part['messages'][0]
            self.assertLessEqual(len(encoded(part['messages'])), 24000)
            self.assertEqual(message['role'], original['role'])
            self.assertEqual(message['created_at'], original['created_at'])
            locator = json.loads(part['source_metadata']['locator'])
            self.assertEqual(locator['original_message_id'], original['id'])
            self.assertEqual(locator['char_start'], cursor)
            cursor = locator['char_end']
            self.assertEqual(locator['original_locator'], 'line-10')
            self.assertEqual(locator['original_parser_version'], 'synthetic-parser')
            self.assertEqual(part['source_metadata']['parent_source_key'], 'synthetic://conversation/1')
        self.assertEqual(cursor, len(original['text']))
        self.assertEqual(''.join(p['messages'][0]['text'] for p in parts), original['text'])

    def test_real_store_archive_retry_no_records_or_model(self):
        messages = [{'id': 'synthetic-user', 'role': 'user', 'text': '合成陈述' * 18000},
                    {'id': 'synthetic-agent', 'role': 'assistant', 'text': '合成建议，未经本人同意。'}]
        principal = {'id': 'synthetic-agent', 'owner': 'synthetic-owner',
                     'scopes': ['agent:synthetic-inbox'], 'actions': ['read', 'write'], 'trusted_user': False}
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            parts = self.prepare(messages)
            for payload in parts:
                self.assertFalse(store.ingest(principal, payload)['duplicate'])
                self.assertTrue(store.ingest(principal, payload)['duplicate'])
            with store.db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0], len(parts))
                self.assertEqual(db.execute('SELECT count(*) FROM records').fetchone()[0], 0)
                self.assertEqual({row[0] for row in db.execute('SELECT state FROM jobs')}, {'archived'})
                self.assertEqual({row[0] for row in db.execute('SELECT trusted_user FROM sources')}, {0})
            def must_not_run(*args):
                raise AssertionError('archive must not call model')
            self.assertFalse(store.process_one(must_not_run))

    def test_reject_not_infer_or_discard(self):
        valid = {'id': 'synthetic', 'role': 'external', 'text': '合成外部材料'}
        cases = [[dict(valid, role='system')], [dict(valid, text='   ')], [valid, valid],
                 [dict(valid, approval=True)], [dict(valid, created_at=None)]]
        for messages in cases:
            with self.subTest(messages=messages), self.assertRaises(Invalid):
                self.prepare(messages)
        with self.assertRaises(Invalid):
            self.prepare([valid], source_metadata={'trusted_user': 'true'})
        with self.assertRaises(Invalid):
            self.prepare([valid], source_metadata=[])
        with self.assertRaises(Invalid):
            self.prepare([valid], source_metadata={'locator': 'x' * 1000})
        with self.assertRaises(Invalid):
            self.prepare([dict(valid, text='合成' + ' ' * 50000)])

    def test_content_revision_changes_key_and_scope_is_explicit(self):
        before = {'id': 'synthetic', 'role': 'user', 'text': '合成旧说法'}
        after = dict(before, text='合成新说法')
        self.assertNotEqual(self.prepare([before])[0]['source_key'], self.prepare([after])[0]['source_key'])
        with self.assertRaises(Invalid):
            prepare_imports('synthetic://1', [before], scope='')


if __name__ == '__main__':
    unittest.main()

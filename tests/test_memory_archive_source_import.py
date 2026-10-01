"""Explicitly synthetic marked visible batch; no real archives or model calls."""
import tempfile
import unittest
from pipeline.memory_center.core import Store,Invalid,encoded
from pipeline.memory_center.claude import PARSER_VERSION,messages
from pipeline.memory_center.archive_source_import import import_batch


class ArchiveSourceImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.p={'id':'synthetic-person','owner':'synthetic-owner','scopes':['synthetic-scope'],
                'actions':['read','source_read','write'],'trusted_user':True}
        self.scope='synthetic-scope';self.batch='synthetic-batch'
        with self.store.db() as db:
            db.execute('INSERT INTO bulk_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (self.batch,self.p['owner'],'synthetic-archive',self.scope,'paused_budget',100000,42,1,0,1,0,0,1.0))
            db.execute('INSERT INTO bulk_batch_parsers VALUES(?,?)',(self.batch,PARSER_VERSION))
        visible=list(messages({'name':'合成归档','chat_messages':[{'uuid':'synthetic-msg','sender':'assistant',
            'content':[{'type':'thinking','thinking':'隐藏推理密文'},{'type':'tool_result','content':'工具密文'},
                       {'type':'text','text':'合成预算建议'}]}]}))
        self.add_segment('synthetic-segment',visible)

    def add_segment(self,sid,payload,source_type='conversation'):
        with self.store.db() as db:
            db.execute('INSERT INTO bulk_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (sid,self.batch,'synthetic-conversation',0 if sid=='synthetic-segment' else 1,'synthetic-source:'+sid,
                 encoded(payload),source_type,'remaining','planned',None,0,0,0,0,None,1.0))

    def test_default_dry_run_no_writes_and_cost_zero(self):
        with self.store.db() as db:before='\n'.join(db.iterdump())
        result=import_batch(self.store,self.p,self.scope,self.batch)
        with self.store.db() as db:after='\n'.join(db.iterdump())
        self.assertEqual(before,after);self.assertTrue(result['dry_run'])
        self.assertEqual(result['new_sources'],1);self.assertEqual(result['imported_sources'],0)
        self.assertEqual(result['model_calls'],0);self.assertEqual(result['extraction_tokens'],0)

    def test_import_only_archives_idempotent_preserves_roles_and_bulk(self):
        with self.store.db() as db:
            before_batch=dict(db.execute('SELECT * FROM bulk_batches').fetchone())
            before_segment=dict(db.execute('SELECT * FROM bulk_segments').fetchone())
        first=import_batch(self.store,self.p,self.scope,self.batch,dry_run=False)
        second=import_batch(self.store,dict(self.p,id='synthetic-other-agent'),self.scope,self.batch,dry_run=False)
        self.assertEqual(first['imported_sources'],1);self.assertEqual(second['duplicates'],1)
        with self.store.db() as db:
            source=dict(db.execute('SELECT * FROM sources').fetchone())
            job=dict(db.execute('SELECT * FROM jobs').fetchone())
            self.assertEqual(dict(db.execute('SELECT * FROM bulk_batches').fetchone()),before_batch)
            self.assertEqual(dict(db.execute('SELECT * FROM bulk_segments').fetchone()),before_segment)
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],0)
            self.assertEqual(source['trusted_user'],0);self.assertEqual(job['state'],'archived')
            self.assertTrue(source['source_key'].startswith('claude:readable:'))
            self.assertIn('assistant',source['payload']);self.assertNotIn('密文',source['payload'])
            metadata=db.execute('SELECT metadata,policy FROM source_envelopes').fetchone()
            self.assertIn('synthetic-segment',metadata['metadata']);self.assertEqual(metadata['policy'],'archive')

    def test_current_parser_marker_required(self):
        with self.store.db() as db:db.execute('UPDATE bulk_batch_parsers SET parser_version=?',('legacy-flat-text',))
        with self.assertRaises(Invalid):import_batch(self.store,self.p,self.scope,self.batch)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'],0)

    def test_preflight_rejects_excluded_content_before_any_import(self):
        self.add_segment('synthetic-other',[{'id':'bad','role':'assistant','text':'可见<thinking>隐藏密文</thinking>'}])
        with self.assertRaises(Invalid):import_batch(self.store,self.p,self.scope,self.batch,dry_run=False)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'],0)

    def test_structured_tool_or_extra_field_rejected(self):
        with self.store.db() as db:db.execute('UPDATE bulk_segments SET payload=?',(encoded([{'id':'bad','role':'assistant','text':'合成内容','content':[{'type':'tool_use'}]}]),))
        with self.assertRaises(Invalid):import_batch(self.store,self.p,self.scope,self.batch)

    def test_owner_scope_and_actions_guarded(self):
        with self.assertRaises(Invalid):import_batch(self.store,dict(self.p,owner='other-owner'),self.scope,self.batch)
        with self.assertRaises(PermissionError):import_batch(self.store,self.p,'other-scope',self.batch)
        for action in ('read','source_read','write'):
            with self.assertRaises(PermissionError):import_batch(self.store,dict(self.p,actions=[a for a in self.p['actions'] if a!=action]),self.scope,self.batch)

    def test_summary_retains_external_attribution(self):
        self.add_segment('synthetic-summary',[{'id':'synthetic-summary-message','role':'external','text':'合成旧摘要'}],'imported_summary')
        result=import_batch(self.store,self.p,self.scope,self.batch,dry_run=False)
        self.assertEqual(result['summary_materials'],1)
        with self.store.db() as db:
            summary=dict(db.execute("SELECT * FROM sources WHERE source_type='imported_summary'").fetchone())
            self.assertIn('external',summary['payload']);self.assertEqual(summary['trusted_user'],0)


if __name__=='__main__':unittest.main()

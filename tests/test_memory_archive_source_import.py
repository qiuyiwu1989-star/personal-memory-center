"""Explicitly synthetic marked visible batch; no real archives or model calls."""
import tempfile
import hashlib
import json
import unittest
from unittest.mock import patch
from pipeline.memory_center.core import Store,Invalid,encoded
from pipeline.memory_center.claude import PARSER_VERSION,messages
from pipeline.memory_center.archive_source_import import import_batch,import_archive


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


    def archive_fixture(self, conversations=None):
        aid='a'*64
        if conversations is None:
            conversations=[{'uuid':'synthetic-original','name':'合成来源','chat_messages':[
                {'uuid':'synthetic-user','sender':'human','content':[{'type':'text','text':'合成预算判断'}]},
                {'uuid':'synthetic-ai','sender':'assistant','content':[{'type':'thinking','thinking':'隐藏思考密文'},
                    {'type':'tool_result','content':'工具密文'},{'type':'text','text':'合成预算建议'}]}]},
                {'uuid':'synthetic-empty','chat_messages':[{'sender':'assistant','content':[{'type':'thinking','thinking':'隐藏密文'}]}]}]
        raw=json.dumps(conversations,ensure_ascii=False).encode();digest=hashlib.sha256(raw).hexdigest()
        directory=self.store.directory/'archives'/aid;directory.mkdir(parents=True,exist_ok=True)
        path=directory/'conversations.json';path.write_bytes(raw)
        with self.store.db() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS archive_batches(id TEXT PRIMARY KEY,owner_id TEXT,status TEXT); CREATE TABLE IF NOT EXISTS archive_files(batch_id TEXT,path TEXT,bytes INTEGER,sha256 TEXT);')
            db.execute('INSERT INTO archive_batches VALUES(?,?,?)',(aid,self.p['owner'],'archived_verified'))
            db.execute('INSERT INTO archive_files VALUES(?,?,?,?)',(aid,'conversations.json',len(raw),digest))
        p=dict(self.p,scopes=[self.scope,'claude:archive'])
        return aid,path,p,digest

    def test_archive_independent_dry_run_and_import_do_not_change_old_bulk(self):
        aid,path,p,digest=self.archive_fixture()
        with self.store.db() as db:
            db.execute('DELETE FROM bulk_batch_parsers')
            before='\n'.join(db.iterdump())
            before_batch=dict(db.execute('SELECT * FROM bulk_batches').fetchone())
            before_segments=[dict(r) for r in db.execute('SELECT * FROM bulk_segments')]
        report=import_archive(self.store,p,self.scope,aid)
        self.assertEqual(report['coverage'],'conversations.json-only')
        self.assertEqual(report['total_archive_conversations'],2)
        self.assertEqual(report['no_visible_text_conversations'],1)
        self.assertEqual(report['archive_sha256'],digest)
        with self.store.db() as db:self.assertEqual(before,'\n'.join(db.iterdump()))
        self.assertEqual(import_archive(self.store,p,self.scope,aid,dry_run=False)['imported_sources'],1)
        self.assertEqual(import_archive(self.store,p,self.scope,aid,dry_run=False)['duplicates'],1)
        with self.store.db() as db:
            self.assertEqual(before_batch,dict(db.execute('SELECT * FROM bulk_batches').fetchone()))
            self.assertEqual(before_segments,[dict(r) for r in db.execute('SELECT * FROM bulk_segments')])
            source=dict(db.execute('SELECT * FROM sources').fetchone())
            self.assertNotIn('密文',source['payload']);self.assertEqual(source['trusted_user'],0)
            self.assertIn(digest,db.execute('SELECT metadata FROM source_envelopes').fetchone()['metadata'])
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],0)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)

    def test_archive_corrupt_bytes_and_flattened_only_rejected(self):
        aid,path,p,_=self.archive_fixture([{'uuid':'synthetic-flat','chat_messages':[{'sender':'human','text':'无法证明可见正文'}]}])
        with self.assertRaisesRegex(Invalid,'flattened'):import_archive(self.store,p,self.scope,aid)
        path.write_bytes(b'[]')
        with self.assertRaises(Invalid):import_archive(self.store,p,self.scope,aid)

    def test_archive_scope_read_and_source_read_required(self):
        aid,path,p,_=self.archive_fixture()
        with self.assertRaises(PermissionError):import_archive(self.store,self.p,self.scope,aid)
        with self.assertRaises(PermissionError):import_archive(self.store,dict(p,actions=['read','write']),self.scope,aid)
        with self.assertRaises(Invalid):import_archive(self.store,dict(p,owner='other-owner'),self.scope,aid)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'],0)


    def test_archive_changes_during_parse_fail_before_first_write(self):
        from pipeline.memory_center.replan import preview as real_preview
        aid,path,p,_=self.archive_fixture()
        def changed_preview(conversations):
            result=real_preview(conversations)
            path.write_bytes(b'[]')
            with self.store.db() as db:
                db.execute('UPDATE archive_files SET bytes=?,sha256=? WHERE batch_id=?',(2,hashlib.sha256(b'[]').hexdigest(),aid))
            return result
        with patch('pipeline.memory_center.replan.preview',changed_preview):
            with self.assertRaisesRegex(Invalid,'哈希在处理中变化'):
                import_archive(self.store,p,self.scope,aid,dry_run=False)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'],0)


if __name__=='__main__':unittest.main()

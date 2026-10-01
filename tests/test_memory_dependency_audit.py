"""Explicitly synthetic dependency preview; all writes are fixture setup."""
import tempfile
import unittest
from pipeline.memory_center.core import Store,Invalid,encoded
from pipeline.memory_center import dependency_audit,documents,source_discovery


class DependencyAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.p={'id':'synthetic-agent','owner':'synthetic-owner','scopes':['synthetic-scope'],
                'actions':['read','source_read','write'],'trusted_user':True}
        self.scope='synthetic-scope'
        self.sid=self.store.ingest(self.p,{'scope':self.scope,'source_key':'synthetic:one','processing_policy':'archive',
            'messages':[{'id':'synthetic-message','role':'user','text':'合成预算说明'}]})['id']

    def record(self,rid='synthetic-record',owner=None):
        with self.store.db() as db:
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid,owner or self.p['owner'],self.scope,'preferences','preference','合成对象','合成预算说明','user_stated',
                 self.sid,'synthetic-message','合成预算说明','active',1,None,1.0))

    def test_exact_links_projection_reference_and_potential_rule(self):
        self.record();documents.setup(self.store);source_discovery.setup(self.store)
        source_discovery.rebuild(self.store,self.p,self.scope)
        with self.store.db() as db:
            db.execute('INSERT INTO document_topics VALUES(?,?,?,?,?)',(self.p['owner'],self.scope,'synthetic-topic','合成主题',encoded(['synthetic:'])))
            db.execute('INSERT INTO document_versions VALUES(?,?,?,?,?,?,?,?)',
                (self.p['owner'],self.scope,'synthetic-topic',1,'synthetic-digest','- 记录：synthetic-record / v1 / active','',1.0))
            db.execute('INSERT INTO extraction_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('synthetic-run',self.p['owner'],self.scope,self.sid,'synthetic-digest','synthetic-method','synthetic-request','ready',0,None,None,None,None,None,1.0))
        result=dependency_audit.preview(self.store,self.p,self.scope,self.sid)
        self.assertEqual(result['counts'],dict(records=1,jobs=1,extraction_runs=1,topic_rules=1,document_versions=1,index_chunks=1))
        self.assertIn('unfinished_processing',result['risks'])
        self.assertEqual({r['relationship'] for r in result['objects']},{'direct_source','potential_prefix_match','stored_record_reference'})
        self.assertTrue(result['preview_only']);self.assertFalse(result['deletion_supported'])

    def test_no_writes_even_optional_schema_missing(self):
        with self.store.db() as db:
            db.execute('DROP TABLE IF EXISTS source_discovery_chunks')
            before='\n'.join(db.iterdump())
        result=dependency_audit.preview(self.store,self.p,self.scope,self.sid)
        with self.store.db() as db:
            after='\n'.join(db.iterdump())
        self.assertEqual(before,after)
        self.assertEqual(result['coverage_missing'],['document_topics','document_versions','source_discovery_chunks'])
        self.assertIn('incomplete_optional_table_coverage',result['risks'])

    def test_unknown_and_unauthorized_indistinguishable(self):
        cases=[(self.p,self.scope,'missing'),(dict(self.p,owner='other-owner'),self.scope,self.sid),
               (self.p,'other-scope',self.sid),(dict(self.p,actions=['read']),self.scope,self.sid)]
        for p,scope,sid in cases:
            with self.assertRaisesRegex(Invalid,'^来源不存在或不可访问$'):
                dependency_audit.preview(self.store,p,scope,sid)
        self.assertEqual(dependency_audit.preview(self.store,dict(self.p,actions=['read','source_read']),self.scope,self.sid)['counts']['jobs'],1)

    def test_owner_scope_filters_dependent_rows(self):
        self.record(owner='other-owner')
        documents.setup(self.store)
        with self.store.db() as db:
            db.execute('INSERT INTO document_versions VALUES(?,?,?,?,?,?,?,?)',
                ('other-owner',self.scope,'synthetic-topic',1,'synthetic-digest','- 记录：synthetic-record / v1 / active','',1.0))
        result=dependency_audit.preview(self.store,self.p,self.scope,self.sid)
        self.assertEqual(result['counts']['records'],0)
        self.assertEqual(result['counts']['document_versions'],0)

    def test_bounded_full_json_and_exact_counts_despite_truncation(self):
        for i in range(30):self.record('synthetic-record-'+str(i))
        result=dependency_audit.preview(self.store,self.p,self.scope,self.sid,max_chars=900)
        self.assertLessEqual(len(encoded(result)),900)
        self.assertEqual(result['counts']['records'],30)
        self.assertTrue(result['truncated'])
        self.assertLess(len(result['objects']),31)
        for bad in (499,16001,True):
            with self.assertRaises(Invalid):dependency_audit.preview(self.store,self.p,self.scope,self.sid,max_chars=bad)


if __name__=='__main__':unittest.main()

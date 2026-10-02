"""Synthetic human-only statements and immutable metadata editing."""
import datetime
import json
import tempfile
import unittest
from unittest.mock import patch
from pipeline.memory_center.core import Store,Invalid,Conflict
from pipeline.memory_center import owner_memory,entities


class OwnerMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.p={'id':'synthetic-human','owner':'synthetic-owner','trusted_user':True,
                'scopes':['synthetic-scope'],'actions':['read','write','source_read']}
        self.scope='synthetic-scope'

    def create(self,**extras):
        body=dict(request_key='synthetic-request',statement='合成本人陈述')
        body.update(extras)
        return owner_memory.create(self.store,self.p,self.scope,body)

    def record(self,rid):
        with self.store.db() as db:
            return dict(db.execute('SELECT * FROM records WHERE id=?',(rid,)).fetchone())

    def governance(self,rid):
        with self.store.db() as db:
            return dict(db.execute('SELECT * FROM record_governance WHERE record_id=?',(rid,)).fetchone())

    def test_default_candidate_author_not_inferred_holder_and_no_extraction(self):
        result=self.create()
        row=self.record(result['id']);gov=self.governance(row['id'])
        self.assertEqual(gov['state'],'candidate');self.assertIsNone(gov['holder']);self.assertIsNone(gov['as_of'])
        self.assertEqual(row['status'],'user_stated');self.assertEqual(row['quote'],row['statement'])
        self.assertNotEqual(row['message_id'],'correction')
        with self.store.db() as db:
            job=dict(db.execute('SELECT state,usage FROM jobs').fetchone())
            self.assertEqual(job['state'],'archived')
            usage=json.loads(job['usage']);self.assertEqual(usage['method'],'owner_manual')
            self.assertTrue(usage['model_skipped']);self.assertEqual(usage['total_tokens'],0)
            self.assertEqual(db.execute('SELECT count(*) n FROM model_attempts').fetchone()['n'],0)
            self.assertEqual(db.execute('SELECT generation FROM scope_index_queue').fetchone()['generation'],1)
            self.assertIn('owner_manual_entry',db.execute('SELECT metadata FROM source_envelopes').fetchone()['metadata'])
        self.assertFalse(result['explicit_confirmation'])

    def test_request_key_idempotent_conflict_and_scope_principal_separation(self):
        first=self.create();second=self.create()
        self.assertEqual(first['id'],second['id']);self.assertTrue(second['duplicate'])
        with self.assertRaises(Conflict):self.create(statement='不同陈述')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],1)
        other=owner_memory.create(self.store,dict(self.p,id='synthetic-other-human'),self.scope,
                                  {'request_key':'synthetic-request','statement':'合成本人陈述'})
        self.assertNotEqual(first['id'],other['id'])

    def test_explicit_verified_requires_fresh_dates_registered_entities(self):
        today=datetime.date.today().isoformat()
        gov={'holder':'owner:'+self.p['owner'],'subject_id':'synthetic:topic','as_of':today,'state':'verified'}
        with self.assertRaises(Invalid):self.create(governance=gov)
        with self.assertRaises(Invalid):self.create(governance=gov,explicit_confirmation=True)
        entities.register(self.store,self.p,self.scope,{'id':'synthetic:topic','name':'合成主题','kind':'topic'})
        result=self.create(governance=gov,explicit_confirmation=True)
        self.assertEqual(self.governance(result['id'])['state'],'verified')
        future=(datetime.date.today()+datetime.timedelta(days=1)).isoformat()
        with self.assertRaises(Invalid):self.create(request_key='synthetic-future',governance=dict(gov,as_of=future),explicit_confirmation=True)
        with self.assertRaises(Invalid):self.create(request_key='synthetic-expired',governance=dict(gov,valid_until=today),explicit_confirmation=True)

    def test_revise_text_preserves_history_resets_trust_and_dates(self):
        today=datetime.date.today().isoformat()
        first=self.create(governance={'state':'verified','holder':'owner:'+self.p['owner'],
            'subject_id':'owner:'+self.p['owner'],'as_of':today},explicit_confirmation=True)
        oldgov=self.governance(first['id'])
        body={'request_key':'synthetic-edit','statement':'合成新的陈述','revision':1,'governance_revision':oldgov['revision']}
        edited=owner_memory.revise(self.store,self.p,self.scope,first['id'],body)
        self.assertEqual(self.record(first['id'])['lifecycle'],'superseded')
        self.assertEqual(self.record(edited['id'])['supersedes'],first['id'])
        self.assertEqual(self.record(edited['id'])['revision'],2)
        gov=self.governance(edited['id'])
        self.assertEqual(gov['state'],'candidate');self.assertIsNone(gov['as_of']);self.assertIsNone(gov['holder'])
        self.assertEqual(self.governance(first['id']),oldgov)
        self.assertEqual(owner_memory.revise(self.store,self.p,self.scope,first['id'],body)['id'],edited['id'])

    def test_metadata_only_keeps_agent_or_summary_evidence_attribution(self):
        imported=self.store.ingest(self.p,{'scope':self.scope,'source_key':'synthetic-summary','source_type':'imported_summary',
            'processing_policy':'archive','messages':[{'id':'synthetic-msg','role':'external','text':'合成摘要陈述'}]})
        with self.store.db() as db:
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('synthetic-summary-record',self.p['owner'],self.scope,'topics','claim','合成对象','合成摘要陈述','imported_summary',
                 imported['id'],'synthetic-msg','合成摘要陈述','active',1,None,1.0))
            db.execute('INSERT INTO record_translations VALUES(?,?,?,?,?)',('synthetic-summary-record','zh','合成展示译文','synthetic-translation-run',1.0))
        edited=owner_memory.revise(self.store,self.p,self.scope,'synthetic-summary-record',
            {'request_key':'synthetic-metadata','revision':1,'governance_revision':0,'governance':{'priority':'P1','note':'合成审核备注'}})
        row=self.record(edited['id'])
        self.assertEqual(row['source_id'],imported['id']);self.assertEqual(row['status'],'imported_summary')
        self.assertEqual(row['message_id'],'synthetic-msg');self.assertTrue(edited['original_evidence_preserved'])
        self.assertEqual(self.governance(edited['id'])['state'],'candidate')
        self.assertNotEqual(row['source_id'],edited['source_id'])
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT text FROM record_translations WHERE record_id=?',(edited['id'],)).fetchone()['text'],'合成展示译文')

    def test_stale_record_or_governance_revisions_rejected_before_write(self):
        first=self.create()
        for field in ('revision','governance_revision'):
            body={'request_key':'synthetic-stale','revision':1,'governance_revision':1,field:0}
            with self.assertRaises(Conflict):owner_memory.revise(self.store,self.p,self.scope,first['id'],body)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'],1)

    def test_owner_scope_trusted_and_actions_guards(self):
        first=self.create()
        for p in (dict(self.p,trusted_user=False),dict(self.p,actions=['read']),dict(self.p,actions=['write'])):
            with self.assertRaises(PermissionError):owner_memory.create(self.store,p,self.scope,{'request_key':'bad','statement':'合成'})
        with self.assertRaises(PermissionError):owner_memory.create(self.store,self.p,'other-scope',{'request_key':'bad','statement':'合成'})
        with self.assertRaises(Invalid):owner_memory.revise(self.store,dict(self.p,owner='other-owner'),self.scope,first['id'],
            {'request_key':'synthetic-cross-owner','revision':1,'governance_revision':1})

    def test_atomic_rollback_after_source_or_supersession(self):
        with patch('pipeline.memory_center.owner_memory._governance',side_effect=RuntimeError('synthetic rollback')):
            with self.assertRaises(RuntimeError):self.create()
        with self.store.db() as db:
            for table in ('sources','records','jobs','source_envelopes','scope_index_queue'):
                self.assertEqual(db.execute('SELECT count(*) n FROM '+table).fetchone()['n'],0)
        first=self.create()
        with patch('pipeline.memory_center.owner_memory._governance',side_effect=RuntimeError('synthetic rollback')):
            with self.assertRaises(RuntimeError):owner_memory.revise(self.store,self.p,self.scope,first['id'],
                {'request_key':'synthetic-edit','statement':'新的陈述','revision':1,'governance_revision':1})
        self.assertEqual(self.record(first['id'])['lifecycle'],'active')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM sources').fetchone()['n'],1)

    def test_no_import_role_source_override_or_inferred_verification(self):
        for field in ('role','source_type','source_id','trusted_user'):
            with self.assertRaises(Invalid):self.create(**{field:'synthetic'})
        with self.assertRaises(Invalid):self.create(explicit_confirmation='yes')
        with self.assertRaises(Invalid):self.create(explicit_confirmation=True)
        with self.assertRaises(Invalid):self.create(governance={'state':'verified'})


if __name__=='__main__':unittest.main()

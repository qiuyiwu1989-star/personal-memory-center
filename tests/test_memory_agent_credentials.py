"""Synthetic owner management; secrets cannot be listed or recovered."""
import hashlib,json,tempfile,time,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from pipeline.memory_center.agent_credentials import AgentCredentials
from pipeline.memory_center.web import load_grants
from pipeline.memory_center.core import Invalid,Conflict

class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'grants.json';self.path.write_text('[]');self.manager=AgentCredentials(self.path)
        self.p={'id':'synthetic-human','owner':'synthetic-owner','trusted_user':True,'scopes':['personal','project:test','agent:synthetic-inbox'],'actions':['read','source_read','write']}
        self.body={'request_key':'synthetic-create','description':'合成只读试用','scopes':['personal'],'actions':['read','source_read'],'days':1}
    def test_secret_only_first_response_retries_and_conflicting_key(self):
        first=self.manager.create(self.p,self.body);token=first['token'];row=load_grants(self.path)[0]
        self.assertFalse(row['trusted_user']);self.assertEqual(row['token_sha256'],hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token,self.path.read_text());self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        listing=self.manager.list(self.p);self.assertNotIn('token_sha256',json.dumps(listing));self.assertNotIn(token,json.dumps(listing))
        retry=self.manager.create(self.p,self.body);self.assertTrue(retry['duplicate']);self.assertIsNone(retry['token'])
        with self.assertRaises(Conflict):self.manager.create(self.p,dict(self.body,days=2))
    def test_revoke_expiry_and_cross_owner(self):
        row=self.manager.create(self.p,self.body)['credential'];self.manager.revoke(self.p,row['id']);self.assertEqual(load_grants(self.path),[])
        self.assertEqual(self.manager.list(self.p)['credentials'][0]['state'],'revoked')
        other=dict(self.p,owner='synthetic-other');self.assertEqual(self.manager.list(other)['total'],0)
        with self.assertRaises(Invalid):self.manager.revoke(other,row['id'])
        rows=json.loads(self.path.read_text());rows[0].update(enabled=True,expires_at=time.time()-1);self.path.write_text(json.dumps(rows))
        self.assertEqual(self.manager.list(self.p)['credentials'][0]['state'],'expired');self.assertEqual(load_grants(self.path),[])
    def test_agent_and_scope_permissions(self):
        for field in ({'trusted_user':False},{'trusted_user':1},{'actions':['read']}):
            with self.assertRaises(PermissionError):self.manager.create(dict(self.p,**field),self.body)
        with self.assertRaises(PermissionError):self.manager.create(self.p,dict(self.body,scopes=['unauthorized']))
        narrow=dict(self.p,scopes=['personal'],actions=['read','write'])
        with self.assertRaises(PermissionError):self.manager.create(narrow,self.body)
    def test_writer_is_separate_inbox_only(self):
        for scopes in (['personal'],['project:test'],['personal','agent:synthetic-inbox']):
            with self.assertRaises(Invalid):self.manager.create(self.p,dict(self.body,scopes=scopes,actions=['read','write']))
        result=self.manager.create(self.p,dict(self.body,scopes=['agent:synthetic-inbox'],actions=['read','write']))
        self.assertEqual(result['credential']['scopes'],['agent:synthetic-inbox'])
    def test_untrusted_legacy_owner_grant_not_exposed_or_revocable(self):
        rows=[dict(self.p,token_sha256='synthetic-hash')];self.path.write_text(json.dumps(rows))
        self.assertEqual(self.manager.list(self.p)['total'],0)
        with self.assertRaises(Invalid):self.manager.revoke(self.p,self.p['id'])
    def test_strict_fields_and_expiry(self):
        for extra in ({'trusted_user':True},{'days':True},{'days':0},{'days':91},{'actions':['read','approve']}):
            with self.assertRaises(Invalid):self.manager.create(self.p,self.body|extra)

    def test_new_grants_are_archive_only_and_legacy_summary_explicit(self):
        self.assertTrue(self.manager.create(self.p,self.body)['credential']['archive_only'])
        self.assertTrue(load_grants(self.path)[0]['archive_only'])
        for value in (False,1,'true',None):
            with self.assertRaises(Invalid):self.manager.create(self.p,self.body|{'archive_only':value})
        rows=json.loads(self.path.read_text());rows[0].pop('archive_only')
        spec={k:rows[0][k] for k in ('description','scopes','actions','days')}
        rows[0]['request_digest']=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
        self.path.write_text(json.dumps(rows))
        self.assertFalse(self.manager.list(self.p)['credentials'][0]['archive_only'])
        self.assertTrue(self.manager.create(self.p,self.body)['duplicate'])
        self.assertFalse(self.manager.create(self.p,self.body)['credential']['archive_only'])
        self.assertNotIn('archive_only',load_grants(self.path)[0])

    def test_malformed_grant_cost_flag_is_rejected(self):
        self.manager.create(self.p,self.body)
        rows=json.loads(self.path.read_text())
        for value in ('false',None,0,1,[]):
            rows[0]['archive_only']=value;self.path.write_text(json.dumps(rows))
            with self.assertRaises(Invalid):load_grants(self.path)

    def test_concurrent_same_request_key_persists_once_and_returns_one_secret(self):
        # Independent manager instances simulate separate server handlers;
        # flock must coordinate their read/modify/atomic-save transaction.
        def create(_):return AgentCredentials(self.path).create(self.p,self.body)
        with ThreadPoolExecutor(max_workers=8) as executor:
            results=list(executor.map(create,range(16)))
        rows=json.loads(self.path.read_text())
        self.assertEqual(len(rows),1)
        self.assertEqual(len({r['credential']['id'] for r in results}),1)
        self.assertEqual(sum(r['token'] is not None for r in results),1)
        self.assertEqual(sum(r['duplicate'] for r in results),15)
        token=next(r['token'] for r in results if r['token'] is not None)
        self.assertEqual(rows[0]['token_sha256'],hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token,self.path.read_text())
        self.assertNotIn(token,json.dumps(self.manager.list(self.p)))

if __name__=='__main__':unittest.main()

"""Synthetic REST ownership and expired grant boundaries."""
import hashlib,json,tempfile,time,unittest
from pathlib import Path
from pipeline.memory_center.core import Store
from pipeline.memory_center.web import local_app,load_grants

class NoModel:
    configured=False
    def extract(self,*args):raise AssertionError('manual editing must not call a model')

class OwnerRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name);self.path=Path(self.tmp.name)/'grants.json'
        base={'owner':'synthetic-owner','scopes':['synthetic'],'actions':['read','write']}
        self.rows=[dict(base,id='human',trusted_user=True,token_sha256=hashlib.sha256(b'synthetic-human').hexdigest()),dict(base,id='agent',trusted_user=False,token_sha256=hashlib.sha256(b'synthetic-agent').hexdigest())]
        self.path.write_text(json.dumps(self.rows))
        self.client=local_app(self.store,lambda:load_grants(self.path),NoModel()).test_client()
        self.prefix='/api/inside/memory-center/v1'
    def post(self,path,body,token='synthetic-human'):
        return self.client.post(self.prefix+path,json=body,headers={'Authorization':'Bearer '+token})
    def test_manual_create_revise_and_stale_version(self):
        response=self.post('/owner-records',{'scope':'synthetic','request_key':'a','statement':'合成陈述'})
        self.assertEqual(response.status_code,200);record=response.json
        body={'scope':'synthetic','request_key':'b','statement':'合成修正','revision':1,'governance_revision':1}
        revised=self.post('/records/'+record['id']+'/revise',body)
        self.assertEqual(revised.status_code,200)
        stale=self.post('/records/'+record['id']+'/revise',dict(body,request_key='c'))
        self.assertEqual(stale.status_code,409)
        records=self.store.snapshot(self.rows[0],'synthetic')['records']
        self.assertEqual(len(records),1);self.assertEqual(records[0]['governance']['state'],'candidate')
        self.assertEqual(records[0]['processing_method'],'owner_manual')
    def test_agent_cannot_impersonate_owner_or_other_scope(self):
        body={'scope':'synthetic','request_key':'a','statement':'合成陈述'}
        self.assertEqual(self.post('/owner-records',body,'synthetic-agent').status_code,403)
        self.assertEqual(self.post('/records/missing/revise',body,'synthetic-agent').status_code,403)
        self.assertEqual(self.post('/owner-records',dict(body,scope='other')).status_code,403)
    def test_expiry_and_revocation_apply_without_restart(self):
        for change in ({'expires_at':time.time()-1},{'enabled':False}):
            self.path.write_text(json.dumps([dict(self.rows[0],**change)]))
            self.assertEqual(self.post('/owner-records',{'scope':'synthetic','request_key':'a','statement':'合成陈述'}).status_code,401)

if __name__=='__main__':unittest.main()

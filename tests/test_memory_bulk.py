import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from pipeline.memory_center.bulk import Bulk, SCOPE
from pipeline.memory_center.core import Store
from pipeline.memory_center.documents import build_documents
from pipeline.memory_center.web import local_app

BATCH='a'*64

class MeteredModel:
    configured=True
    def __init__(self, tokens=20000):self.calls=0;self.tokens=tokens
    def extract(self,messages):
        self.calls+=1
        m=messages[0]
        quote=m['text'][:min(20,len(m['text']))]
        return {'claims':[{'topic':'projects','kind':'claim','subject':'user',
                'statement':quote,'quote':quote,'message_id':m['id']}]}, {'prompt_tokens':self.tokens-100,'completion_tokens':100,'total_tokens':self.tokens}

class BulkTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.owner={'id':'owner','owner':'q','scopes':['claude:archive',SCOPE],
                    'actions':['read','write'],'trusted_user':True}
        self.bulk=Bulk(self.store)
        self.folder=Path(self.tmp.name)/'archives'/BATCH
        (self.folder/'memories').mkdir(parents=True)
        conversations=[]
        for i in range(12):
            conversations.append({'uuid':'chat-'+str(i),'name':'Conversation '+str(i),'created_at':f'2026-09-{i+1:02d}',
                'chat_messages':[{'uuid':'msg-'+str(i),'sender':'human','text':'这是一段需要保留来源的历史讨论。'*900,'created_at':f'2026-09-{i+1:02d}'}]})
        conversations.append({'uuid':'empty-chat','name':'Image only','created_at':'2026-09-30','chat_messages':[]})
        data=json.dumps(conversations,ensure_ascii=False).encode()
        memo=json.dumps({'conversations_memory':'过去偏好摘要','project_memories':{},
                         'memory_files':[{'path':'/people/test.md','content':'历史人物关系摘要'}]},ensure_ascii=False).encode()
        (self.folder/'conversations.json').write_bytes(data)
        (self.folder/'memories'/'account.json').write_bytes(memo)
        with self.store.db() as db:
            db.executescript('''CREATE TABLE archive_batches(id TEXT PRIMARY KEY,owner_id TEXT,status TEXT);
                CREATE TABLE archive_files(batch_id TEXT,path TEXT,bytes INTEGER,sha256 TEXT);
                CREATE TABLE archive_conversations(batch_id TEXT,conversation_id TEXT,title TEXT);''')
            db.execute('INSERT INTO archive_batches VALUES(?,?,?)',(BATCH,'q','archived_verified'))
            for path,raw in [('conversations.json',data),('memories/account.json',memo)]:
                db.execute('INSERT INTO archive_files VALUES(?,?,?,?)',(BATCH,path,len(raw),hashlib.sha256(raw).hexdigest()))
            for c in conversations:db.execute('INSERT INTO archive_conversations VALUES(?,?,?)',(BATCH,c['uuid'],c['name']))
    def tearDown(self):self.tmp.cleanup()
    def test_plan_replay_budget_and_provenance(self):
        batch=self.bulk.create(self.owner,BATCH,100000)
        self.assertEqual((batch['total_conversations'],batch['no_text_conversations'],batch['memory_documents']),(13,1,2))
        self.assertGreater(batch['total_segments'],12)
        self.assertEqual(batch['sampled_segments'],10)
        self.assertEqual(self.bulk.create(self.owner,BATCH,100000)['id'],batch['id'])
        model=MeteredModel()
        for _ in range(30):
            self.bulk.tick()
            self.store.process_one(model)
            if self.bulk.status(self.owner,batch['id'])['state']=='paused_budget':break
        status=self.bulk.status(self.owner,batch['id'])
        self.assertEqual(status['state'],'paused_budget')
        self.assertEqual(status['tokens_spent'],model.calls*20000)
        self.assertLessEqual(status['tokens_spent'],100000)
        self.assertEqual(model.calls,4)
        self.assertGreater(status['counts']['planned'],0)
        with self.assertRaisesRegex(ValueError,'上限'):self.bulk.control(self.owner,batch['id'],'resume')
        rows=self.store.snapshot(self.owner,SCOPE)['records']
        self.assertTrue(rows)
        self.assertTrue(all(r['status']=='source_reported' for r in rows))
        docs=build_documents(self.store,self.owner,SCOPE)
        self.assertEqual(len(docs),6)
        self.assertEqual(next(d for d in docs if d['slug']=='history-projects')['claims'],1)
        self.assertEqual(len(next(d for d in docs if d['slug']=='history-projects')['dependencies']),len(rows))
        self.assertEqual(next(d for d in docs if d['slug']=='history-people')['claims'],0)
    def test_http_batch_controls_require_owner(self):
        import hashlib
        owner=dict(self.owner,token_sha256=hashlib.sha256(b'owner-test').hexdigest())
        reader=dict(owner,id='reader',trusted_user=False,token_sha256=hashlib.sha256(b'reader-test').hexdigest())
        client=local_app(self.store,[owner,reader],MeteredModel()).test_client()
        endpoint='/api/inside/memory-center/v1/archives/'+BATCH+'/bulk'
        self.assertEqual(client.post(endpoint,json={'token_limit':100000}).status_code,401)
        self.assertEqual(client.post(endpoint,headers={'Authorization':'Bearer reader-test'},json={'token_limit':100000}).status_code,403)
        created=client.post(endpoint,headers={'Authorization':'Bearer owner-test'},json={'token_limit':100000})
        self.assertEqual(created.status_code,202)
        self.assertEqual(client.get('/api/inside/memory-center/v1/bulk',headers={'Authorization':'Bearer owner-test'}).get_json()['batches'][0]['id'],created.get_json()['id'])
        pause=client.post('/api/inside/memory-center/v1/bulk/'+created.get_json()['id']+'/control',headers={'Authorization':'Bearer owner-test'},json={'action':'pause'})
        self.assertEqual(pause.get_json()['state'],'paused')
        preview=client.get('/api/inside/memory-center/v1/archives/conversations/chat-0/preview',headers={'Authorization':'Bearer owner-test'})
        self.assertEqual(preview.status_code,200)
        self.assertIn('这是一段需要保留来源的历史讨论',preview.get_json()['text'])
        self.assertEqual(client.get('/api/inside/memory-center/v1/archives/conversations/chat-0/preview',headers={'Authorization':'Bearer reader-test'}).status_code,403)
        self.bulk.control(self.owner,created.get_json()['id'],'resume')
        self.bulk.tick()
        class Disconnected:
            def extract(self,messages):raise ConnectionError('offline')
        self.store.process_one(Disconnected())
        with self.store.db() as db:
            failed=db.execute("SELECT job_id FROM bulk_segments WHERE state='queued' LIMIT 1").fetchone()['job_id']
        self.assertEqual(client.post('/api/inside/memory-center/v1/jobs/'+failed+'/retry',headers={'Authorization':'Bearer owner-test'},json={}).status_code,400)
    def test_corrupt_source_and_unauthorized_create(self):
        other=dict(self.owner,owner='other')
        with self.assertRaisesRegex(ValueError,'未找到'):self.bulk.create(other,BATCH)
        with self.assertRaises(PermissionError):self.bulk.create(dict(self.owner,trusted_user=False),BATCH)
        (self.folder/'conversations.json').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'校验'):self.bulk.create(self.owner,BATCH)
    def test_misquoted_archive_claim_does_not_discard_valid_evidence(self):
        batch=self.bulk.create(self.owner,BATCH)
        self.bulk.tick()
        class PartlyWrong:
            def extract(self,messages):
                m=messages[0]
                valid={'topic':'projects','kind':'claim','subject':'user','statement':'历史讨论有依据',
                       'message_id':m['id'],'quote':m['text'][:20]}
                return ({'claims':[valid,dict(valid,statement='错误引文',quote='不存在于来源的引文')]},
                        {'prompt_tokens':100,'completion_tokens':50,'total_tokens':150})
        self.store.process_one(PartlyWrong())
        self.bulk.tick()
        status=self.bulk.status(self.owner,batch['id'])
        self.assertEqual(status['counts']['applied'],1)
        self.assertEqual(len(self.store.snapshot(self.owner,SCOPE)['records']),1)
        jobs=self.store.snapshot(self.owner,SCOPE)['jobs']
        self.assertEqual(next(j for j in jobs if j['state']=='applied')['usage']['discarded_unsupported_claims'],1)
    def test_expired_attempt_keeps_reserved_budget(self):
        batch=self.bulk.create(self.owner,BATCH,100000)
        self.bulk.tick()
        with self.store.db() as db:
            segment=db.execute("SELECT job_id FROM bulk_segments WHERE batch_id=? AND state='queued'",(batch['id'],)).fetchone()
            db.execute("UPDATE jobs SET state='processing',attempts=1,lease='expired',lease_until=0 WHERE id=?",(segment['job_id'],))
        self.bulk.tick()
        with self.store.db() as db:
            row=db.execute('SELECT reserved_tokens,reserved_attempts FROM bulk_segments WHERE job_id=?',(segment['job_id'],)).fetchone()
        self.assertEqual((row['reserved_tokens'],row['reserved_attempts']),(70000,2))
        self.store.process_one(MeteredModel())
        self.bulk.tick()
        with self.store.db() as db:
            settled=db.execute('SELECT spent_tokens FROM bulk_segments WHERE job_id=?',(segment['job_id'],)).fetchone()
        self.assertEqual(settled['spent_tokens'],55000)
        self.assertLessEqual(self.bulk.status(self.owner,batch['id'])['tokens_spent'],100000)
    def test_unmetered_network_failure_pauses_batch_instead_of_stalling(self):
        batch=self.bulk.create(self.owner,BATCH,100000)
        self.bulk.tick()
        class Disconnected:
            def extract(self,messages):raise ConnectionError('private endpoint details')
        self.store.process_one(Disconnected())
        self.bulk.tick()
        status=self.bulk.status(self.owner,batch['id'])
        self.assertEqual(status['state'],'paused_error')
        self.assertEqual(status['counts']['failed'],1)
        self.assertEqual(status['counts'].get('queued',0),0)
        self.assertEqual(status['tokens_spent'],35000)
        retried=self.bulk.control(self.owner,batch['id'],'retry_failed')
        self.assertEqual(retried['state'],'running')
        self.store.process_one(MeteredModel())
        self.bulk.tick()
        self.assertEqual(self.bulk.status(self.owner,batch['id'])['counts']['applied'],1)
    def test_owner_can_raise_paused_budget_from_workbench(self):
        batch=self.bulk.create(self.owner,BATCH,100000)
        self.bulk.control(self.owner,batch['id'],'pause')
        with self.assertRaisesRegex(ValueError,'新上限'):
            self.bulk.control(self.owner,batch['id'],'set_limit',100000)
        with self.assertRaises(PermissionError):
            self.bulk.control(dict(self.owner,trusted_user=False),batch['id'],'set_limit',200000)
        with self.assertRaisesRegex(ValueError,'质量验收'):
            self.bulk.control(self.owner,batch['id'],'set_limit',200000)
        from pipeline.memory_center.budget import configure
        configure(self.store,self.owner,SCOPE,{'token_limit':0,'quality_approved':True,'note':'Synthetic explicit owner quality acceptance'})
        changed=self.bulk.control(self.owner,batch['id'],'set_limit',200000)
        self.assertEqual((changed['token_limit'],changed['state']),(200000,'running'))
    def test_pause_stops_new_jobs(self):
        batch=self.bulk.create(self.owner,BATCH)
        self.bulk.control(self.owner,batch['id'],'pause')
        for _ in range(3):self.bulk.tick()
        self.assertEqual(self.bulk.status(self.owner,batch['id'])['counts'].get('queued',0),0)
        self.bulk.control(self.owner,batch['id'],'resume')
        self.bulk.tick()
        self.assertEqual(self.bulk.status(self.owner,batch['id'])['counts']['queued'],1)

if __name__=='__main__':unittest.main()

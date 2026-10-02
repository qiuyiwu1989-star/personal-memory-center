"""Synthetic call traces against real local readers, never skill text matching."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from pipeline.memory_center.core import Store,encoded
from pipeline.memory_center.governance import context
from pipeline.memory_center.reading import search_page
from pipeline.memory_center import source_discovery

spec=importlib.util.spec_from_file_location('portable_reader',Path(__file__).resolve().parents[1]/'skills/personal-memory-center/references/retrieval_contract.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class DownstreamContractTest(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=Store(tmp.name);source_discovery.setup(self.store)
        self.p={'id':'synthetic-agent','owner':'synthetic-owner','scopes':['synthetic'],
                'actions':['read','source_read','write'],'trusted_user':True}
        self.text='Atlas 合成来源：'+('正文\\\n合成资料。'*250)
        self.sid=self.store.ingest(self.p,{'scope':'synthetic','source_key':'synthetic-source',
            'source_type':'conversation','processing_policy':'archive','messages':[
                {'id':'u','role':'user','text':self.text}]})['id']
        with self.store.db() as db:
            for rid,state,end in [('trusted','verified',None),('candidate','candidate',None),('expired','verified','2001-01-01')]:
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (rid,self.p['owner'],'synthetic','projects','claim','Atlas','Atlas 合成陈述 '+rid,
                   'user_stated',self.sid,'u',self.text[:40],'active',1,None,1))
                db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
                  (rid,'synthetic-holder','synthetic-project','2000-01-01',end,state,'P1',1,'Synthetic fixture',0))
        source_discovery.rebuild(self.store,self.p,'synthetic')

    def reader(self,host):
        trace=[]
        def call(name,args):
            trace.append((name,args.copy()))
            scope=args['scope'];budget=args['max_chars']
            if name=='memory_context':result=context(self.store,self.p,scope,args['query'],budget)
            elif name=='memory_search':result=search_page(self.store.snapshot(self.p,scope,args['query']),budget)
            elif name=='memory_archive_search':result=source_discovery.search(self.store,self.p,scope,args['query'],budget,args['offset'],args['limit'])
            elif name=='memory_archive_source_get':result=source_discovery.read(self.store,self.p,scope,args['locator'],args['offset'],budget)
            else:raise AssertionError('unexpected write or unsupported tool')
            return result if host=='native' else {'structuredContent':result,'content':[{'type':'text','text':encoded(result)}]}
        return module.Reader(call,'synthetic',access_epoch='synthetic-1',version='v1'),trace

    def test_two_hosts_l0_l1_use_only_current_trusted_context(self):
        for host in ('native','sdk'):
            reader,trace=self.reader(host)
            self.assertIsNone(reader.background(False,'Atlas'));self.assertEqual(trace,[])
            result=reader.background(True,'Atlas')
            self.assertEqual([r['id'] for r in result['records']],['trusted'])
            self.assertEqual(trace[0][0],'memory_context')
            self.assertEqual(trace[0][1]['max_chars'],1600)
            with self.store.db() as db:db.execute("UPDATE record_governance SET state='candidate' WHERE record_id='trusted'")
            self.assertEqual(reader.background(True,'Atlas')['records'],[])
            self.assertEqual([n for n,_ in trace],['memory_context','memory_context'])
            with self.store.db() as db:db.execute("UPDATE record_governance SET state='verified' WHERE record_id='trusted'")

    def test_l2_l3_follow_actual_offset_and_keep_original_evidence_separate(self):
        for host in ('native','sdk'):
            reader,trace=self.reader(host)
            candidates=reader.search('Atlas','candidate')
            self.assertIn('candidate',[r['id'] for r in candidates['records']])
            hits=reader.search('Atlas','archive')
            self.assertFalse(hits['facts_confirmed'])
            first=reader.page(hits['results'][0]['locator'],max_chars=700)
            second=reader.next_page(first,max_chars=700)
            self.assertEqual(second['offset'],first['next_offset'])
            self.assertNotEqual(second['offset'],700)
            self.assertEqual(first['text']+second['text'],self.text[:second['next_offset']])
            self.assertEqual([n for n,_ in trace],['memory_search','memory_archive_search','memory_archive_source_get','memory_archive_source_get'])
            self.assertEqual([a['max_chars'] for _,a in trace],[4000,6000,700,700])

    def test_scope_access_and_version_changes_invalidate_locators(self):
        reader,trace=self.reader('sdk')
        for identity in [('other','synthetic-1','v1'),('synthetic','synthetic-2','v1'),('synthetic','synthetic-2','v2')]:
            reader.reset('synthetic','synthetic-1','v1')
            hit=reader.search('Atlas','archive')['results'][0]
            reader.reset(*identity)
            before=len(trace)
            with self.assertRaises(ValueError):reader.page(hit['locator'])
            self.assertEqual(len(trace),before)

    def test_server_revocation_and_payload_drift_fail_without_retry(self):
        reader,trace=self.reader('native')
        hit=reader.search('Atlas','archive')['results'][0]
        self.p['actions']=['read']
        with self.assertRaises(PermissionError):reader.page(hit['locator'])
        before=len(trace)
        with self.assertRaises(ValueError):reader.page(hit['locator'])
        self.assertEqual(len(trace),before)
        self.p['actions']=['read','source_read','write']
        hit=reader.search('Atlas','archive')['results'][0]
        with self.store.db() as db:
            db.execute('UPDATE sources SET payload=? WHERE id=?',(encoded([{'id':'u','role':'user','text':'Atlas 新版本合成资料'}]),self.sid))
        # Core Invalid subclasses ValueError: the reference clears stale handles.
        with self.assertRaises(ValueError):reader.page(hit['locator'])
        before=len(trace)
        with self.assertRaises(ValueError):reader.page(hit['locator'])
        self.assertEqual(len(trace),before)

    def test_response_budget_and_text_envelope_behavior(self):
        reader=module.Reader(lambda name,args:{'content':[{'type':'text','text':json.dumps({'records':[]})}]},'synthetic')
        self.assertEqual(reader.background(True,'Atlas'),{'records':[]})
        reader=module.Reader(lambda name,args:{'records':[{'statement':'x'*2000}]},'synthetic')
        with self.assertRaises(ValueError):reader.background(True,'Atlas')


if __name__=='__main__':unittest.main()

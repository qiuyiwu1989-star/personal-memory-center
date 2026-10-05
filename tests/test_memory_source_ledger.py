"""Only synthetic provenance fixtures; no LLM or production data."""
import json
import unittest
import test_memory_center as baseline
from pipeline.memory_center.source_ledger import source_ledger, record_ledger
from pipeline.memory_center.core import Invalid, encoded
from pipeline.memory_center.documents import setup


class SourceLedgerTests(unittest.TestCase):
    setUp=baseline.MemoryTest.setUp
    tearDown=baseline.MemoryTest.tearDown
    body=baseline.MemoryTest.body
    ingest=baseline.MemoryTest.ingest
    rows=baseline.MemoryTest.rows

    def test_archive_unknown_cost_and_no_mutation_or_model(self):
        item=self.store.ingest(self.owner,self.body(processing_policy='archive',source_metadata={'original_ref':'private/path','visibility':'visible_only'}))
        calls=self.model.calls
        with self.store.db() as db: before=[dict(r) for r in db.execute('SELECT * FROM sources')]
        ledger=source_ledger(self.store,self.owner,'personal',item['id'])
        self.assertEqual(ledger['summary']['source_message_count'],1)
        self.assertEqual(ledger['summary']['records_total'],0)
        self.assertEqual(ledger['jobs'][0]['usage']['state'],'unknown')
        self.assertIsNone(ledger['jobs'][0]['usage']['monetary_cost'])
        self.assertNotIn('private/path',encoded(ledger));self.assertNotIn('payload',ledger['source'])
        self.assertEqual(ledger['source']['visibility'],'visible_only')
        self.assertEqual(self.model.calls,calls)
        with self.store.db() as db:self.assertEqual(before,[dict(r) for r in db.execute('SELECT * FROM sources')])

    def test_bidirectional_candidates_and_measured_not_guessed(self):
        item=self.ingest()
        rid=self.rows()[0]['id']
        result=record_ledger(self.store,self.owner,'personal',rid)
        self.assertEqual(result['focal_record']['id'],rid)
        self.assertEqual(result['source']['id'],item['id'])
        self.assertEqual(result['summary']['candidate'],1)
        self.assertEqual(result['summary']['current_usable'],0)
        self.assertEqual(result['records'][0]['evidence']['role'],'user')
        self.assertIn('not_verified',result['records'][0]['exclusion_reasons'])
        self.assertEqual(result['jobs'][0]['usage']['prompt_tokens'],17)
        self.assertIsNone(result['jobs'][0]['usage']['total_tokens'])
        self.assertIsNone(result['jobs'][0]['method_version'])

    def test_scope_owner_permissions_and_invalid_pages(self):
        item=self.ingest();rid=self.rows()[0]['id']
        for p,scope in ((self.agent,'personal'),(dict(self.owner,owner='other'),'personal'),(self.owner,'project:demo')):
            with self.assertRaises((Invalid,PermissionError)):source_ledger(self.store,p,scope,item['id'])
            with self.assertRaises((Invalid,PermissionError)):record_ledger(self.store,p,scope,rid)
        for limit in (True,0,101,'broken'):
            with self.assertRaises(Invalid):source_ledger(self.store,self.owner,'personal',item['id'],limit)
        for offset in (-1,10001,False):
            with self.assertRaises(Invalid):source_ledger(self.store,self.owner,'personal',item['id'],offset=offset)
        resp=self.client.get(self.prefix+'/sources/'+item['id']+'/ledger?limit=no',headers=self.headers)
        self.assertEqual(resp.status_code,400)
        resp=self.client.get(self.prefix+'/records/'+rid+'/ledger',headers=self.headers)
        self.assertEqual(resp.status_code,200)

    def test_document_exact_refs_bounded_scan_and_page(self):
        item=self.ingest();rid=self.rows()[0]['id'];setup(self.store)
        with self.store.db() as db:
            db.execute('INSERT INTO document_versions VALUES(?,?,?,?,?,?,?,?)',('q','personal','synthetic-one',1,'digest','- 记录：'+rid+' / v1 / active','',1))
            db.execute('INSERT INTO document_versions VALUES(?,?,?,?,?,?,?,?)',('q','personal','synthetic-two',1,'digest','- 记录：'+rid+'-similar / v1 / active','',2))
        first=source_ledger(self.store,self.owner,'personal',item['id'],limit=1)
        self.assertEqual(first['documents'],[])
        self.assertEqual(first['pagination']['documents']['coverage'],'partial')
        second=source_ledger(self.store,self.owner,'personal',item['id'],limit=1,offset=1)
        self.assertEqual(second['documents'][0]['slug'],'synthetic-one')
        self.assertEqual(second['records'],[])
        self.assertEqual(second['summary']['records_total'],1)
        self.assertTrue(first['pagination']['documents']['truncated'])

    def test_withdrawal_receipt_overrides_usable_and_rest_boundary(self):
        from pipeline.memory_center.source_lifecycle import setup as lifecycle_setup
        item=self.ingest();rid=self.rows()[0]['id'];lifecycle_setup(self.store)
        with self.store.db() as db:
            db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',(rid,'user','synthetic-subject','2020-01-01',None,'verified','P1',1,'',1))
        self.assertEqual(source_ledger(self.store,self.owner,'personal',item['id'])['summary']['current_usable'],1)
        url=self.prefix+'/sources/'+item['id']
        preview=self.client.get(url+'/withdrawal-preview',headers=self.headers)
        self.assertEqual(preview.status_code,200)
        receipt=self.client.post(url+'/withdraw',json={'scope':'personal','reason':'synthetic withdrawal'},headers=self.headers)
        self.assertEqual(receipt.status_code,200)
        ledger=source_ledger(self.store,self.owner,'personal',item['id'])
        self.assertEqual(ledger['source']['state'],'withdrawn')
        self.assertEqual(ledger['summary']['current_usable'],0)
        self.assertTrue(ledger['records'][0]['source_withdrawn'])
        self.assertIn('source_withdrawn',ledger['records'][0]['exclusion_reasons'])
        duplicate=self.client.post(url+'/withdraw',json={'scope':'personal'},headers=self.headers)
        self.assertTrue(duplicate.get_json()['duplicate'])
        wrong=self.client.post(url+'/withdraw',json={'scope':'personal','delete':True},headers=self.headers)
        self.assertEqual(wrong.status_code,400)

    def test_failed_job_does_not_leak_raw_error_or_notes(self):
        item=self.ingest()
        with self.store.db() as db:
            db.execute('UPDATE jobs SET error=?,usage=? WHERE source_id=?',('private/path provider response',encoded({'review_notes':{'secret':'value'},'total_tokens':0,'model_skipped':True,'method_version':'synthetic-v1'}),item['id']))
        result=source_ledger(self.store,self.owner,'personal',item['id'])
        self.assertTrue(result['jobs'][0]['error_present'])
        self.assertEqual(result['jobs'][0]['usage']['state'],'model_skipped')
        self.assertEqual(result['jobs'][0]['method_version'],'synthetic-v1')
        self.assertNotIn('private/path',encoded(result));self.assertNotIn('secret',encoded(result))


if __name__=='__main__':unittest.main()

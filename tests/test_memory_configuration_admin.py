"""Explicitly synthetic owner configuration pagination and export contracts."""
import hashlib
import tempfile
import unittest
from pipeline.memory_center.core import Store, Invalid
from pipeline.memory_center.configuration import draft, activate, listing, compare
from pipeline.memory_center.web import local_app
from test_memory_center import FakeModel


class ConfigurationAdminTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.owner={'id':'synthetic-admin','owner':'synthetic-config','trusted_user':True,
                    'scopes':['personal','project:synthetic'],'actions':['read','write']}
        self.grant=dict(self.owner,token_sha256=hashlib.sha256(b'synthetic-admin-token').hexdigest())
        self.client=local_app(self.store,[self.grant],FakeModel()).test_client()
        self.headers={'Authorization':'Bearer synthetic-admin-token'}
        self.prefix='/api/inside/memory-center/v1/configuration'
    def tearDown(self):self.tmp.cleanup()
    def make(self,i=0,kind='prompt',payload=None):
        return draft(self.store,self.owner,'personal',{'kind':kind,'label':'synthetic '+str(i),
                     'payload':payload or {'instructions':'合成提炼规则 '+str(i)}})['id']
    def test_all_versions_reachable_and_old_active_payload_independent_of_page(self):
        first=self.make(0);activate(self.store,self.owner,'personal',first,{'revision':0,'note':'合成验证依据，仅用于测试分页功能。'})
        for i in range(1,105):self.make(i)
        ids=[];offset=0
        while True:
            response=self.client.get(self.prefix,query_string={'offset':offset,'limit':20},headers=self.headers)
            self.assertEqual(response.status_code,200);page=response.get_json()
            self.assertEqual(page['total'],105)
            self.assertEqual(page['active']['prompt']['version']['id'],first)
            ids.extend(v['id'] for v in page['versions'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(len(set(ids)),105);self.assertEqual(len(ids),105)
    def test_audits_are_paginated_and_keep_previous_version(self):
        ids=[self.make(0),self.make(1)]
        for revision in range(33):activate(self.store,self.owner,'personal',ids[revision%2],{'revision':revision,'note':'合成重复切换验证，用来检验审计完整性。'})
        first=listing(self.store,self.owner,'personal');last=listing(self.store,self.owner,'personal',event_offset=30)
        self.assertEqual((first['event_total'],len(first['events']),len(last['events'])),(33,30,3))
        self.assertEqual(len({e['id'] for e in first['events']+last['events']}),33)
    def test_compare_is_exact_scoped_and_does_not_certify_semantics(self):
        a=self.make(0);b=self.make(1)
        result=compare(self.store,self.owner,'personal',a,b)
        self.assertTrue(result['changed']);self.assertIn('合成提炼规则 1',result['diff']);self.assertFalse(result['semantic_quality_verified'])
        self.assertFalse(compare(self.store,self.owner,'personal',a,a)['changed'])
        with self.assertRaises(Invalid):compare(self.store,self.owner,'project:synthetic',a,b)
        other=dict(self.owner,owner='different-synthetic-owner')
        with self.assertRaises(Invalid):compare(self.store,other,'personal',a,b)
        skill=self.make(kind='skill',payload={'name':'memory-capture','version':'v1','instructions':'合成 Skill 内容'})
        with self.assertRaises(Invalid):compare(self.store,self.owner,'personal',a,skill)
    def test_skill_http_download_has_utf8_bytes_hash_and_safe_attachment(self):
        text='---\nname: memory-capture\n---\n合成 Skill，只作下载验证。\n'
        vid=self.make(kind='skill',payload={'name':'memory-capture','version':'unsafe\r\nfilename','instructions':text})
        response=self.client.get(self.prefix+'/skill-download',query_string={'version_id':vid},headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.data,text.encode())
        self.assertEqual(response.headers['X-Skill-SHA256'],hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(response.headers['X-Skill-Publication'],'draft')
        self.assertEqual(response.headers['Content-Disposition'],'attachment; filename="memory-capture-'+vid+'-SKILL.md"')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(self.client.get(self.prefix+'/skill-download',query_string={'name':'memory-capture'},headers=self.headers).headers['X-Skill-Publication'],'bundled_code')
        self.assertEqual(self.client.get(self.prefix+'/skill-download',query_string={'scope':'project:synthetic','version_id':vid},headers=self.headers).status_code,400)
        self.assertEqual(self.client.get(self.prefix+'/skill-download',query_string={'version_id':vid}).status_code,401)
    def test_invalid_paging_and_non_owner_denied(self):
        for value in ('-1','1.2','nan','100000000000000000000000000000'):
            response=self.client.get(self.prefix,query_string={'limit':value},headers=self.headers)
            self.assertEqual(response.status_code,400)
        with self.assertRaises(PermissionError):listing(self.store,dict(self.owner,trusted_user=False),'personal')
        with self.assertRaises(PermissionError):compare(self.store,dict(self.owner,trusted_user=False),'personal','a','b')
        integration=listing(self.store,self.owner,'personal')['integration']
        self.assertEqual(integration['installed'],'unknown')
        self.assertTrue(all(s['installed']=='unknown' for s in integration['skills']))

if __name__=='__main__':unittest.main()

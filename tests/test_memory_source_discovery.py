"""Synthetic visible-source discovery fixtures only."""
import copy
import tempfile
import unittest
from pipeline.memory_center.core import Store, Invalid, encoded
from pipeline.memory_center import source_discovery as discovery


def principal(owner='synthetic-owner', scope='synthetic-scope', actions=None):
    return {'id':'synthetic-agent','owner':owner,'scopes':[scope],
            'actions':actions if actions is not None else ['read','source_read','write'],'trusted_user':True}


class SourceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        discovery.setup(self.store)
        self.p = principal()
        self.scope = 'synthetic-scope'

    def add(self, messages, source_key='synthetic-source', source_type='conversation', p=None):
        return self.store.ingest(p or self.p, {'scope':self.scope,'source_key':source_key,
            'source_type':source_type,'messages':messages,'processing_policy':'archive'})['id']

    def test_incremental_stable_hash_and_no_source_mutation(self):
        sid = self.add([{'id':'one','role':'user','text':'合成预算为十元'}])
        with self.store.db() as db:
            before = dict(db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone())
        first = discovery.rebuild(self.store,self.p,self.scope)
        hit = discovery.search(self.store,self.p,self.scope,'预算')['results'][0]
        second = discovery.rebuild(self.store,self.p,self.scope)
        discovery.rebuild(self.store,self.p,self.scope,force=True)
        self.assertEqual(first['indexed_sources'],1)
        self.assertEqual(second['unchanged_sources'],1)
        self.assertEqual(second['indexed_sources'],0)
        self.assertEqual(hit['locator'],discovery.search(self.store,self.p,self.scope,'预算')['results'][0]['locator'])
        self.assertEqual(first['confirmed_facts'],0)
        with self.store.db() as db:
            self.assertEqual(before,dict(db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()))
            self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],0)

    def test_roles_types_and_quotes_are_evidence(self):
        self.add([{'id':'u','role':'user','text':'合成预算讨论'},
                  {'id':'a','role':'assistant','text':'合成预算建议'},
                  {'id':'e','role':'external','text':'合成预算引文'}],source_type='imported_summary')
        discovery.rebuild(self.store,self.p,self.scope)
        result = discovery.search(self.store,self.p,self.scope,'预算')
        self.assertEqual({r['role'] for r in result['results']},{'user','assistant','external'})
        self.assertEqual({r['material_type'] for r in result['results']},{'imported_summary'})
        self.assertFalse(result['facts_confirmed'])
        self.assertTrue(all(r['evidence_only'] for r in result['results']))

    def test_thinking_excluded_and_offsets_preserved(self):
        text = '预算可见<thinking>隐藏推理密文<thinking>嵌套密文</thinking>末段密文</thinking>预算结尾'
        self.add([{'id':'one','role':'user','text':text}])
        # Legacy/raw source fixtures may retain typed or structured thinking.
        with self.store.db() as db:
            src = dict(db.execute('SELECT * FROM sources').fetchone())
            db.execute('UPDATE sources SET payload=? WHERE id=?',(encoded([
                {'id':'one','role':'user','text':text},
                {'id':'two','role':'assistant','type':'thinking','text':'隐藏推理密文'},
                {'id':'three','role':'assistant','text':'预算<thinking>未关闭密文'},
                {'id':'four','role':'thinking','text':'隐藏推理密文'},
                {'id':'five','role':'assistant','content':[{'type':'thinking','thinking':'隐藏推理密文'}]},
            ]),src['id']))
        rebuilt=discovery.rebuild(self.store,self.p,self.scope)
        self.assertEqual(rebuilt['messages'],2)
        self.assertEqual(discovery.search(self.store,self.p,self.scope,'隐藏推理密文')['total'],0)
        results=discovery.search(self.store,self.p,self.scope,'预算')['results']
        page=discovery.read(self.store,self.p,self.scope,results[0]['locator'])
        self.assertNotIn('密文',page['text'])
        if page['locator']['message_id']=='one':
            self.assertEqual(len(page['text']),len(text))
            self.assertEqual(page['text'].index('预算结尾'),text.index('预算结尾'))

    def test_permission_guard_before_database_and_no_cross_owner_scope(self):
        self.add([{'id':'one','role':'user','text':'合成预算'}])
        discovery.rebuild(self.store,self.p,self.scope)
        loc=discovery.search(self.store,self.p,self.scope,'预算')['results'][0]['locator']
        for actions in (['read'],['source_read'],['write']):
            denied=principal(actions=actions)
            with self.assertRaises(PermissionError):discovery.search(self.store,denied,self.scope,'预算')
            with self.assertRaises(PermissionError):discovery.read(self.store,denied,self.scope,loc)
        with self.assertRaises(PermissionError):discovery.rebuild(self.store,principal(actions=['read','source_read']),self.scope)
        self.assertEqual(discovery.search(self.store,principal(owner='other-owner'),self.scope,'预算')['total'],0)
        with self.assertRaises(Invalid):discovery.read(self.store,principal(owner='other-owner'),self.scope,loc)
        with self.assertRaises(PermissionError):discovery.search(self.store,self.p,'other-scope','预算')

    def test_stale_digest_and_payload_fail_closed_until_rebuild(self):
        sid=self.add([{'id':'one','role':'user','text':'合成预算'}])
        discovery.rebuild(self.store,self.p,self.scope)
        loc=discovery.search(self.store,self.p,self.scope,'预算')['results'][0]['locator']
        with self.store.db() as db:
            db.execute('UPDATE sources SET payload=? WHERE id=?',(encoded([{'id':'one','role':'user','text':'合成车辆'}]),sid))
        self.assertEqual(discovery.search(self.store,self.p,self.scope,'预算')['total'],0)
        with self.assertRaises(Invalid):discovery.read(self.store,self.p,self.scope,loc)
        self.assertEqual(discovery.rebuild(self.store,self.p,self.scope)['indexed_sources'],1)
        self.assertEqual(discovery.search(self.store,self.p,self.scope,'车辆')['total'],1)
        with self.store.db() as db:db.execute('UPDATE sources SET digest=? WHERE id=?',('synthetic-new-digest',sid))
        self.assertEqual(discovery.search(self.store,self.p,self.scope,'车辆')['total'],0)

    def test_deleted_source_removes_stale_index(self):
        sid=self.add([{'id':'one','role':'user','text':'合成预算'}])
        discovery.rebuild(self.store,self.p,self.scope)
        with self.store.db() as db:db.execute('DELETE FROM sources WHERE id=?',(sid,))
        self.assertEqual(discovery.search(self.store,self.p,self.scope,'预算')['total'],0)
        self.assertEqual(discovery.rebuild(self.store,self.p,self.scope)['removed_sources'],1)

    def test_read_pages_lossless_visible_text_and_entire_json_budget(self):
        text='合成预算资料。'*700
        self.add([{'id':'one','role':'user','text':text}])
        discovery.rebuild(self.store,self.p,self.scope)
        result=discovery.search(self.store,self.p,self.scope,'预算',max_chars=1600,limit=2)
        self.assertLessEqual(len(encoded(result)),1600)
        loc=result['results'][0]['locator'];position=0;pages=[]
        while True:
            page=discovery.read(self.store,self.p,self.scope,loc,position,max_chars=700)
            self.assertLessEqual(len(encoded(page)),700)
            pages.append(page['text'])
            if page['next_offset'] is None:break
            self.assertGreater(page['next_offset'],position)
            position=page['next_offset']
        self.assertEqual(''.join(pages),text)

    def test_search_pagination_stable_and_input_unchanged(self):
        messages=[{'id':str(i),'role':'user','text':'合成预算'+str(i)} for i in range(7)]
        self.add(messages)
        discovery.rebuild(self.store,self.p,self.scope)
        before=copy.deepcopy(self.p);ids=[];offset=0
        while True:
            page=discovery.search(self.store,self.p,self.scope,'预算',offset=offset,limit=2)
            ids.extend(r['locator']['chunk_id'] for r in page['results'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(len(ids),7);self.assertEqual(len(set(ids)),7);self.assertEqual(self.p,before)
        self.assertEqual(ids,[r['locator']['chunk_id'] for r in discovery.search(self.store,self.p,self.scope,'预算')['results']])

    def test_invalid_parameters(self):
        for budget in (499,16001,True):
            with self.assertRaises(Invalid):discovery.search(self.store,self.p,self.scope,'预算',max_chars=budget)
        for offset in (-1,True):
            with self.assertRaises(Invalid):discovery.search(self.store,self.p,self.scope,'预算',offset=offset)
        with self.assertRaises(Invalid):discovery.rebuild(self.store,self.p,self.scope,force='yes')
        with self.assertRaises(Invalid):discovery.read(self.store,self.p,self.scope,{'source_id':'fake'})


if __name__=='__main__':unittest.main()

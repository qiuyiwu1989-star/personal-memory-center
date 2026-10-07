"""Synthetic HTTP/MCP intake -> owner governance -> invalidation acceptance."""
import hashlib
import json
import tempfile
import unittest
from starlette.testclient import TestClient
from pipeline.memory_center.core import Store
from pipeline.memory_center.service import create_app
from pipeline.memory_center.web import PREFIX


class NoModel:
    configured = False
    def extract(self, *args):
        raise AssertionError('interface acceptance cannot call a model')


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.scope = 'agent:synthetic-inbox'
        base = dict(owner='synthetic-owner', scopes=[self.scope], archive_only=True)
        self.owner = dict(base, id='synthetic-human', trusted_user=True,
                          actions=['read', 'write', 'source_read'])
        self.agent = dict(base, id='synthetic-node', trusted_user=False,
                          actions=['read', 'write', 'source_read', 'candidate_write'])
        self.legacy = dict(self.agent, id='synthetic-legacy', actions=['read', 'write', 'source_read'])
        self.grants = []
        for name, row in [('human', self.owner), ('node', self.agent), ('legacy', self.legacy)]:
            row['token_sha256'] = hashlib.sha256(('synthetic-' + name).encode()).hexdigest()
            self.grants.append(row)
        app = create_app(self.store, lambda:self.grants, NoModel(), run_worker=False)
        self.client = self.enterContext(TestClient(app, base_url='http://127.0.0.1:5078'))
        self.quote = '合成项目使用方案甲。'
        self.text = '合成前言。' + self.quote + '合成后文。'

    def headers(self, actor='human'):
        return {'Authorization':'Bearer synthetic-' + actor, 'Accept':'application/json, text/event-stream'}

    def get(self, path, actor='human', **params):
        return self.client.get(PREFIX + path, params={'scope':self.scope, **params}, headers=self.headers(actor))

    def post(self, path, body, actor='human'):
        data = body if path.endswith('/governance') else {'scope':self.scope, **body}
        return self.client.post(PREFIX + path, json=data, headers=self.headers(actor))

    def rpc(self, name, args=None, actor='node'):
        response = self.client.post('/mcp/', headers=self.headers(actor), json={
            'jsonrpc':'2.0', 'id':1, 'method':'tools/call',
            'params':{'name':name, 'arguments':{'scope':self.scope, **(args or {})}}})
        self.assertEqual(response.status_code, 200)
        result = response.json()['result']
        if 'structuredContent' not in result and not result.get('isError'):
            result['structuredContent'] = json.loads(result['content'][0]['text'])
        return result

    def archive(self):
        body = {'source_key':'synthetic-source', 'processing_policy':'archive',
                'messages':[{'id':'synthetic-message', 'role':'user', 'text':self.text}]}
        response = self.post('/sources', body, 'node')
        self.assertEqual(response.status_code, 202)
        return response.json()['id']

    def submission(self, source_id):
        start = self.text.index(self.quote)
        return {'source_id':source_id, 'request_key':'synthetic-request', 'claims':[{
            'message_id':'synthetic-message', 'start':start, 'end':start + len(self.quote),
            'quote':self.quote, 'statement':'合成项目的候选决定。', 'topic':'projects',
            'kind':'decision', 'subject':'合成项目'}]}

    def test_http_complete_owner_review_correction_and_withdrawal(self):
        source_id = self.archive(); body = self.submission(source_id)
        before = self.get('/changes').json()['checkpoint']
        submitted = self.post('/candidate-intake', body, 'node')
        self.assertEqual(submitted.status_code, 201); rid = submitted.json()['record_ids'][0]
        self.assertEqual(self.post('/candidate-intake', body, 'node').status_code, 200)
        listed = self.get('/candidate-intake').json()
        self.assertEqual(listed['receipts'][0]['records'][0]['state'], 'candidate')
        self.assertNotIn(self.quote, str(listed)); self.assertNotIn(body['claims'][0]['statement'], str(listed))
        detail = self.get('/records/' + rid).json()['record']
        self.assertEqual(detail['quote'], self.quote); self.assertFalse(detail['usable'])
        self.assertEqual(detail['processing_method'], 'upstream_candidate')
        self.assertEqual(detail['candidate_intake']['quote_start'], body['claims'][0]['start'])
        self.assertEqual(self.rpc('memory_context', {'query':''})['structuredContent']['records'], [])
        self.assertTrue(self.get('/changes', cursor=before).json()['requires_context_refresh'])
        review = {'revision':0, 'state':'verified', 'holder':'owner:synthetic-owner',
                  'subject_id':'owner:synthetic-owner', 'as_of':'2000-01-01'}
        self.assertEqual(self.post('/records/' + rid + '/governance', review, 'node').status_code, 403)
        self.assertEqual(self.post('/records/' + rid + '/governance', review).status_code, 200)
        trusted = self.rpc('memory_context', {'query':''})['structuredContent']['records']
        self.assertEqual(len(trusted), 1)
        checkpoint = self.get('/changes').json()['checkpoint']
        revised = self.post('/records/' + rid + '/revise', {
            'request_key':'synthetic-correction', 'statement':'合成更正：方案乙尚待核实。',
            'revision':1, 'governance_revision':1})
        self.assertEqual(revised.status_code, 200)
        self.assertTrue(self.get('/changes', cursor=checkpoint).json()['requires_context_refresh'])
        self.assertEqual(self.get('/records/' + rid).json()['record']['lifecycle'], 'superseded')
        self.assertEqual(self.rpc('memory_context', {'query':''})['structuredContent']['records'], [])
        checkpoint = self.get('/changes').json()['checkpoint']
        self.assertEqual(self.post('/sources/' + source_id + '/withdraw', {'reason':'合成撤回'}).status_code, 200)
        self.assertTrue(self.get('/changes', cursor=checkpoint).json()['requires_context_refresh'])
        self.assertEqual(self.get('/source', source_id=source_id, message_id='synthetic-message').status_code, 400)
        self.assertEqual(self.get('/records', 'node', history='1').status_code, 403)
        self.assertNotIn(self.quote, str(self.get('/records', 'node').json()))
        self.assertIn(self.quote, str(self.get('/records', history='1').json()))
        self.assertTrue(self.get('/records/' + rid).json()['record']['source_withdrawn'])
        self.assertEqual(self.post('/candidate-intake', body, 'node').status_code, 409)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) n FROM model_attempts').fetchone()['n'], 0)

    def test_mcp_capabilities_submit_replay_and_new_permission(self):
        capabilities = self.rpc('memory_capabilities')['structuredContent']
        self.assertTrue(capabilities['candidate_intake']['available'])
        self.assertTrue(capabilities['candidate_intake']['authorized'])
        self.assertFalse(self.rpc('memory_capabilities', actor='legacy')['structuredContent']['candidate_intake']['authorized'])
        self.owner.pop('archive_only')
        owner_cap = self.get('/capabilities').json()
        self.assertEqual(owner_cap['archive']['rest_default_policy'], 'extract')
        self.assertEqual(owner_cap['archive']['mcp_default_policy'], 'archive')
        self.assertEqual(owner_cap['context']['rest_path'], '/task-context')
        self.assertFalse(owner_cap['legacy_context']['verified_only'])
        body = self.submission(self.archive())
        result = self.rpc('memory_candidate_submit', body)
        self.assertFalse(result.get('isError', False)); receipt = result['structuredContent']
        self.assertTrue(receipt['candidate_only']); self.assertFalse(receipt['facts_confirmed'])
        again = self.rpc('memory_candidate_submit', body)['structuredContent']
        self.assertEqual(receipt['id'], again['id']); self.assertTrue(again['duplicate'])
        self.assertTrue(self.rpc('memory_candidate_submit', body, 'legacy')['isError'])
        self.assertTrue(self.rpc('memory_import', {'source_key':'synthetic-paid-denied',
            'processing_policy':'extract', 'messages':[{'id':'1','role':'user','text':'合成正文'}]})['isError'])
        checkpoint = self.rpc('memory_changes')['structuredContent']['checkpoint']
        result = self.rpc('memory_changes', {'cursor':checkpoint})['structuredContent']
        self.assertFalse(result['changed']); self.assertEqual(result['items'], [])
        self.agent['actions'].remove('candidate_write')
        self.assertTrue(self.rpc('memory_candidate_submit', body)['isError'])
        self.grants.remove(self.agent)
        response = self.client.post('/mcp/', headers=self.headers('node'), json={})
        self.assertEqual(response.status_code, 401)

    def test_owner_detail_and_strict_route_boundaries(self):
        body = self.submission(self.archive()); rid = self.post('/candidate-intake', body, 'node').json()['record_ids'][0]
        for path in ['/candidate-intake', '/records/' + rid]:
            self.assertEqual(self.get(path, 'node').status_code, 403)
        for path in ['/capabilities', '/changes', '/records/' + rid, '/candidate-intake']:
            self.assertEqual(self.get(path, scope='outside').status_code, 403)
        self.owner['actions'].remove('source_read')
        self.assertEqual(self.get('/records/' + rid).status_code, 403)
        self.assertEqual(self.get('/candidate-intake').status_code, 200)
        for path in ['/candidate-intake', '/changes']:
            for value in ['-1', 'abc', '1.0', '']:
                self.assertEqual(self.get(path, limit=value).status_code, 400)
        self.assertTrue(self.rpc('memory_changes', {'limit':True})['isError'])

    def test_missing_migration_read_only_capabilities_and_no_false_empty_success(self):
        with self.store.db() as db:
            db.execute('DROP TABLE candidate_intake_evidence')
            db.execute('DROP TABLE candidate_intake_receipts')
        cap = self.get('/capabilities').json()
        self.assertFalse(cap['candidate_intake']['available'])
        self.assertEqual(cap['candidate_intake']['migration_required'], '010_candidate_intake')
        self.assertFalse(self.get('/candidate-intake').json()['supported'])
        self.assertEqual(self.post('/candidate-intake', self.submission(self.archive()), 'node').status_code, 400)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) n FROM sqlite_master WHERE name LIKE 'candidate_intake_%'").fetchone()['n'], 0)


if __name__ == '__main__':unittest.main()

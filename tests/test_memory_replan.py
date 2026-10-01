import unittest
from pipeline.memory_center.replan import preview

class ReplanTest(unittest.TestCase):
    def test_private_projection_preserves_old_plan_and_excludes_hidden_blocks(self):
        conversations=[{'uuid':'synthetic-1','chat_messages':[
            {'uuid':'m1','sender':'assistant','text':'ReasoningReply','content':[
                {'type':'thinking','thinking':'Reasoning'},{'type':'text','text':'Reply'}]}]},
            {'uuid':'synthetic-2','chat_messages':[{'uuid':'m2','sender':'human','content':[]}]}]
        previous=[{'conversation_id':'synthetic-1','segment_index':0,'state':'applied','digest':'old'}]
        result=preview(conversations,previous)
        self.assertEqual(previous[0]['digest'],'old')
        self.assertEqual(result['summary']['new_conversation_segments'],1)
        self.assertEqual(result['summary']['no_visible_text_conversations'],1)
        self.assertEqual(result['summary']['excluded_block_types'],{'thinking':1})
        self.assertEqual(result['planned_segments'][0]['messages'][0]['text'],'Reply')
        self.assertEqual(result['policy'],'preview-only-no-model-no-dispatch-no-writeback')

class MappingTest(unittest.TestCase):
    def test_locator_quote_and_ambiguity_are_required(self):
        from pipeline.memory_center.replan import map_evidence
        segments=[{'conversation_id':'c','messages':[{'id':'m#t1p0','text':'visible'},{'id':'other#t0p0','text':'secret'}]}]
        records=[{'id':'r','conversation_id':'c','message_id':'m','quote':'secret'},
                 {'id':'v','conversation_id':'c','message_id':'m','quote':'visible'}]
        self.assertEqual([r['state'] for r in map_evidence(records,segments)],['unresolved','mapped'])
        segments[0]['messages'].append({'id':'m#t2p0','text':'visible'})
        self.assertEqual(map_evidence(records,segments)[1]['state'],'ambiguous')

class PersistentReplanTest(unittest.TestCase):
    def test_adoption_is_idempotent_and_does_not_change_jobs_or_budget(self):
        import copy
        from test_memory_bulk import BulkTest,BATCH
        from pipeline.memory_center.replan import Replans
        fixture=BulkTest();fixture.setUp()
        try:
            batch=fixture.bulk.create(fixture.owner,BATCH,100000)
            with fixture.store.db() as db:
                before=[tuple(r) for r in db.execute('SELECT * FROM bulk_segments')]
            plans=Replans(fixture.store)
            plan=plans.create(fixture.owner,batch['id'])['plan']
            self.assertFalse(plan['dispatch_enabled'])
            self.assertEqual(len(plan['conversation_changes']),13)
            self.assertNotIn('planned_segments',plan)
            self.assertEqual(plans.create(fixture.owner,batch['id'])['plan']['id'],plan['id'])
            adopted=plans.adopt(fixture.owner,batch['id'],plan['id'])['plan']
            self.assertEqual(adopted['state'],'adopted_waiting_quality')
            self.assertEqual(plans.adopt(fixture.owner,batch['id'],plan['id'])['plan']['adopted'],adopted['adopted'])
            with fixture.store.db() as db:
                self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM bulk_segments')])
                self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT tokens_spent FROM bulk_batches').fetchone()[0],0)
            foreign=copy.deepcopy(fixture.owner);foreign['owner']='other'
            with self.assertRaises(ValueError):plans.get(foreign,batch['id'])
            readonly=copy.deepcopy(fixture.owner);readonly['actions']=['read']
            with self.assertRaises(PermissionError):plans.adopt(readonly,batch['id'],plan['id'])
            with fixture.store.db() as db:db.execute("UPDATE archive_replans SET parser_version='old' WHERE id=?",(plan['id'],))
            with self.assertRaisesRegex(ValueError,'过时'):plans.adopt(fixture.owner,batch['id'],plan['id'])
        finally:fixture.tearDown()

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

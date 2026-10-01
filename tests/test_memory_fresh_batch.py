"""Explicitly synthetic, no provider or live DB fixture."""
import tempfile
import unittest
from pathlib import Path
from scripts.prepare_fresh_memory_batch import select, candidate_gate, write_private


class FreshBatchTests(unittest.TestCase):
    def setUp(self):
        self.conversations = [{'uuid': 'synthetic-conversation', 'name': '合成项目', 'chat_messages': [
            {'uuid': 'synthetic-message', 'sender': 'human', 'created_at': '2025-01-01',
             'content': [{'type': 'text', 'text': '我希望合成项目保存来源。'},
                         {'type': 'thinking', 'text': '不可作为证据的合成思考'}]}]}]

    def test_unseen_visible_input(self):
        batch = select(self.conversations, [], [], ['synthetic-message'])
        self.assertNotIn('合成思考', str(batch['cases']))
        self.assertFalse(batch['preflight']['quality_approved'])
        self.assertEqual(batch['preflight']['model_calls'], 0)

    def test_seen_or_applied_rejected(self):
        with self.assertRaises(ValueError):
            select(self.conversations, [{'conversation_id': 'synthetic-conversation', 'state': 'applied'}], [], ['synthetic-message'])
        with self.assertRaises(ValueError):
            select(self.conversations, [], [{'messages': [{'id': 'synthetic-message#old', 'role': 'user'}]}], ['synthetic-message'])

    def test_static_never_semantic_confirmation(self):
        case = select(self.conversations, [], [], ['synthetic-message'])['cases'][0]
        claim = {'message_id': case['messages'][0]['id'], 'quote': '保存来源',
                 'statement': '2025-01-01 合成项目要求保存来源。', 'status': 'source_reported'}
        gate = candidate_gate(case, [claim])
        self.assertTrue(gate['static_gate_passed'])
        self.assertFalse(gate['quality_approved'])
        self.assertTrue(gate['semantic_review_required'])
        self.assertFalse(candidate_gate(case, [claim, claim])['static_gate_passed'])
        self.assertFalse(candidate_gate(case, [claim | {'quote': '合成思考'}])['static_gate_passed'])
        self.assertFalse(candidate_gate(case, [claim | {'status': 'verified'}])['static_gate_passed'])

    def test_private_exclusive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'synthetic.json'
            write_private(target, {})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private(target, {})


if __name__ == '__main__': unittest.main()

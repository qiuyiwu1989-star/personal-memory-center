"""Synthetic regression for wish versus decision; no semantic certification."""
import unittest
from pipeline.memory_center.core import validate_plan,Invalid,encoded

class ModalityTest(unittest.TestCase):
    def check(self,quote,statement):
        source={'source_type':'conversation','trusted_user':False,'processing_method_version':'2026-10-01.13','payload':encoded([{'id':'synthetic','role':'user','text':quote}])}
        return validate_plan({'claims':[{'topic':'projects','kind':'plan','subject':'synthetic','quote':quote,'statement':statement,'message_id':'synthetic'}]},source)
    def test_wish_cannot_be_declared_a_decision(self):
        for phrase in ('用户决定','用户已决定','用户已经决定'):
            with self.assertRaises(Invalid):self.check('我希望采用合成方案。',phrase+'采用合成方案。')
    def test_wish_and_explicit_decision_are_not_rewritten(self):
        self.assertEqual(self.check('我希望采用合成方案。','用户希望采用合成方案。')[0]['status'],'source_reported')
        self.assertEqual(self.check('我决定采用合成方案。','用户决定采用合成方案。')[0]['statement'],'用户决定采用合成方案。')

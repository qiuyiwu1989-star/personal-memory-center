"""Synthetic candidate association cases, no private fixtures."""
import unittest
from copy import deepcopy
from pipeline.memory_center.candidate_links import candidate_links

class CandidateLinksTest(unittest.TestCase):
    def sample(self):
        return {'owner':'synthetic-owner','scope':'synthetic-project','source_type':'conversation',
                'role':'user','status':'user_stated','topic':'projects','kind':'decision','subject':'user',
                'statement':'合成项目保留全部原始引用。','source_id':'source-1','message_id':'m1',
                'quote':'合成项目保留全部原始引用。',
                'evidence_context':{'source_date':'2026-01-01','conversation_title':'合成项目'}}

    def test_exact_repeated_text_links_without_mutating_sources(self):
        candidate=self.sample(); old=dict(candidate,id='r1',source_id='source-2',message_id='m2')
        before=deepcopy(old); result=candidate_links(candidate,[old])
        self.assertEqual(result[0]['relation'],'exact_statement')
        self.assertEqual(result[0]['evidence']['source_id'],'source-2')
        self.assertEqual(old,before); self.assertNotIn('id',candidate)

    def test_same_evidence_is_only_related_not_semantic_merge(self):
        candidate=self.sample(); old=dict(candidate,id='r1',statement='用户在合成项目讨论引用保存方案。')
        result=candidate_links(candidate,[old]);self.assertEqual(result[0]['relation'],'same_evidence')

    def test_cross_identity_attribution_date_or_scope_is_not_duplicate(self):
        candidate=self.sample()
        for key,value in [('owner','other'),('scope','other'),('role','assistant'),('source_type','imported_summary'),('status','agent_suggested')]:
            with self.subTest(key=key): self.assertEqual(candidate_links(candidate,[dict(candidate,id='r1',**{key:value})]),[])
        for key,value in [('source_date','2025-01-01'),('conversation_title','另一个合成项目')]:
            context=dict(candidate['evidence_context'],**{key:value})
            self.assertEqual(candidate_links(candidate,[dict(candidate,id='r1',evidence_context=context)]),[])

    def test_paraphrase_is_not_guessed_duplicate_and_results_bounded(self):
        candidate=self.sample()
        old=dict(candidate,id='r1',source_id='other',statement='相似但未经语义核实的合成表述。')
        self.assertEqual(candidate_links(candidate,[old]),[])
        self.assertEqual(len(candidate_links(candidate,[dict(candidate,id=str(i)) for i in range(50)],limit=3)),3)
        with self.assertRaises(ValueError):candidate_links(candidate,[],limit=0)

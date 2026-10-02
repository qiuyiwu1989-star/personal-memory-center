import unittest

from pipeline.memory_center.answer_contract import validate


class AnswerContractTests(unittest.TestCase):
    def test_evidence_boundary_answer_is_not_false_current_state(self):
        result = validate({'answer': '合成资料只提供一条助手建议，无法证明本人采纳。',
                           'citations': ['synthetic-1'], 'evidence_status': 'answered',
                           'abstained': False, 'limitations': ['当前采纳状态未知。']}, {'synthetic-1'})
        self.assertFalse(result['abstained'])

    def test_current_fact_without_evidence_abstains(self):
        result = validate({'answer': '没有材料说明当前项目状态。', 'citations': [],
                           'evidence_status': 'insufficient_evidence', 'abstained': True,
                           'limitations': ['未提供当前来源。']}, set())
        self.assertTrue(result['abstained'])

    def test_inconsistent_or_invented_citations_rejected(self):
        valid = {'answer': '合成事实。', 'citations': ['synthetic-1'],
                 'evidence_status': 'answered', 'abstained': False, 'limitations': []}
        for delta in ({'abstained': True}, {'abstained': 0}, {'citations': ['unknown']},
                      {'citations': []}, {'citations': ['synthetic-1', 'synthetic-1']},
                      {'evidence_status': 'verified'}, {'trusted': True}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                validate(valid | delta, {'synthetic-1'})

    def test_matching_citation_is_not_semantic_quality_approval(self):
        # Contract validation cannot detect this synthetic misattribution.
        output = {'answer': '用户决定了X。', 'citations': ['third-party-1'],
                  'evidence_status': 'answered', 'abstained': False, 'limitations': []}
        self.assertEqual(validate(output, {'third-party-1'}), output)


if __name__ == '__main__':
    unittest.main()

"""Synthetic audit hints do not approve, delete or rewrite candidates."""
import copy
import json
import unittest
from pipeline.memory_center.extraction_quality import review, review_notes


def claim(statement,quote=None,**fields):
    return {'statement':statement,'quote':quote or statement,'topic':'projects','kind':'claim',
            'subject':'synthetic-project','status':'user_stated'} | fields


class ExtractionQualityTest(unittest.TestCase):
    def test_condition_review_is_explicit_uncertainty_not_false_entailment(self):
        claims=[claim('用户的项目名叫 Atlas。','我的项目名叫 Atlas；如果评测通过，我计划发布。'),
                claim('如果评测通过，用户计划发布 Atlas。')]
        result=review(claims)
        self.assertEqual(result['items'][0]['disposition'],'review_required')
        self.assertIn('不能仅凭词法认定遗漏',review_notes(result,claims)[claims[0]['statement']])
        self.assertEqual(result['items'][1]['findings'],[])
        self.assertFalse(result['quality_approved'])

    def test_named_fact_and_wish_separate_without_mixed_source_global_kill(self):
        quote='我的项目名叫 Atlas，我希望以后支持离线查询。'
        result=review([claim('用户的项目名叫 Atlas。',quote),
                       claim('用户希望以后支持离线查询。',quote,kind='plan'),
                       claim('用户的项目名叫 Atlas，用户希望以后支持离线查询。',quote,kind='plan')])
        self.assertEqual(result['items'][0]['findings'],[])
        self.assertEqual(result['items'][1]['findings'],[])
        self.assertIn('mixed_statement_review',[f['code'] for f in result['items'][2]['findings']])

    def test_exact_duplicate_and_partial_overlap_link_never_merge(self):
        claims=[claim('合成项目必须保留原始出处。'),
                claim('合成项目必须保留原始出处。'),
                claim('合成项目必须保留原始出处。用户希望今后支持查询。'),
                claim('合成项目应保留来源。'),
                claim('合成项目必须保留原始出处。',status='agent_suggested')]
        before=copy.deepcopy(claims);result=review(claims)
        self.assertEqual(claims,before)
        items=result['items']
        self.assertEqual(items[1]['findings'][0]['duplicate_of'],0)
        self.assertIn('exact_clause_overlap',[f['code'] for f in items[2]['findings']])
        self.assertEqual(items[3]['findings'],[])
        self.assertEqual(items[4]['findings'],[])

    def test_short_task_hint_does_not_erase_durable_constraints(self):
        claims=[claim('用户请求调研合成产品。'),
                claim('用户要求每次调研必须保留出处。'),
                claim('合成项目必须保留原始出处。','请生成草图，长期约束是保留出处。')]
        result=review(claims)
        self.assertEqual([i['disposition'] for i in result['items']],
                         ['archive_only','candidate','candidate'])
        self.assertEqual(len(claims),3)

    def test_server_labels_do_not_create_fact_or_condition_signals(self):
        prefix='来源消息日期：2026-01-01（非事件成立时间，当前有效性待核实）。来源对话：如果项目计划已完成。'
        c=claim(prefix+'用户希望采用 Atlas。', '我希望采用 Atlas。',
                evidence_context={'source_date':'2026-01-01','conversation_title':'如果项目计划已完成'},kind='plan')
        self.assertEqual(review([c])['items'][0]['findings'],[])

    def test_empty_and_invalid_payload(self):
        self.assertEqual(review([])['total'],0)
        with self.assertRaises(ValueError):review([{'statement':'synthetic'}])

    def test_resolved_metadata_can_be_supplied_without_copying_source_into_report(self):
        title='如果项目计划已完成'
        quote='我希望采用 Atlas。'
        prefix='来源消息日期：2026-01-01（非事件成立时间，当前有效性待核实）。来源对话：'+title+'。'
        c=claim(prefix+'用户希望采用 Atlas。',quote,kind='plan',message_id='synthetic-u')
        source={'source_type':'conversation','payload':json.dumps([{'id':'synthetic-u','role':'user','text':quote,
                    'source_title':title,'created_at':'2026-01-01'}])}
        result=review([c],source)
        self.assertEqual(result['items'][0]['findings'],[])
        serialized=json.dumps(result,ensure_ascii=False)
        self.assertNotIn(quote,serialized)
        self.assertNotIn(c['statement'],serialized)
        self.assertEqual(result['quality_policy_version'],'extraction-quality-review-v2')

    def test_display_notes_are_separate_bounded_and_no_adoption_is_implied(self):
        claims=[claim('用户请求调研合成产品。')]
        result=review(claims)
        notes=review_notes(result,claims)
        self.assertLessEqual(len(notes[claims[0]['statement']]),400)
        self.assertNotIn('review_notes',result)
        self.assertFalse(result['items'][0]['semantics_verified'])


if __name__=='__main__':unittest.main()

"""Independent synthetic modality fixtures; no real model or personal data."""
import unittest
from pipeline.memory_center.core import Invalid
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
from pipeline.memory_center.modality import evidence_ranges, modality_problem


class ModalityTest(unittest.TestCase):
    def prepare(self, text, version='2026-10-01.14'):
        return prepare_request('conversation', [{'id': 'synthetic-message', 'role': 'user',
            'text': text, 'source_title': 'Synthetic / 项目 A', 'created_at': '2026-02-03'}], version=version)

    def claim(self, sid, statement, kind='claim'):
        return {'topic': 'projects', 'kind': kind, 'subject': 'user',
                'statement': statement, 'evidence_id': sid}

    def test_named_fact_and_wish_separate_with_lossless_offsets(self):
        text='我的合成项目名叫 Atlas，我希望下一阶段增加离线查询。'
        request, spans, _ = self.prepare(text)
        self.assertEqual(len(spans), 2)
        self.assertEqual(''.join(s['quote'] for s in spans.values()), text)
        for span in spans.values():
            self.assertEqual(text[span['start']:span['end']], span['quote'])
        ids=list(spans)
        result=resolve_plan({'claims':[
            self.claim(ids[0], '用户的合成项目名叫 Atlas。'),
            self.claim(ids[1], '用户希望下一阶段增加离线查询。', 'plan'),
        ]}, spans, version='2026-10-01.14')
        self.assertEqual([c['modality'] for c in result['claims']], ['stated', 'wish'])
        for claim in result['claims']:
            self.assertIn('来源对话：Synthetic / 项目 A。', claim['statement'])
            self.assertIn('来源消息日期：2026-02-03（非事件成立时间，当前有效性待核实）。', claim['statement'])

    def test_wish_promotion_rejected_without_erasing_named_fact(self):
        text='我的合成项目名叫 Atlas，我希望下一阶段增加离线查询。'
        _, spans, _=self.prepare(text)
        fact, wish=list(spans)
        resolve_plan({'claims':[self.claim(fact,'用户的合成项目名叫 Atlas。')]}, spans, version='2026-10-01.14')
        for statement,kind in [('用户已经完成离线查询。','claim'),('用户决定支持离线查询。','decision'),('用户支持离线查询。','event')]:
            with self.subTest(statement=statement), self.assertRaises(Invalid):
                resolve_plan({'claims':[self.claim(wish,statement,kind)]},spans,version='2026-10-01.14')

    def test_list_condition_and_inherited_subject_keep_context(self):
        examples=[
            '我的合成系统包含：\n1. Atlas 查询器\n2. Orion 归档器。\n我希望以后增加导出。',
            '如果独立评测通过，我计划发布 Atlas；我希望它保留证据。',
            '我的合成系统叫 Atlas。它只允许离线查询。',
            '我的合成系统叫“Atlas；我希望”。我计划增加查询。',
        ]
        for text in examples[:3]:
            with self.subTest(text=text):
                self.assertEqual(evidence_ranges(text),[(0,len(text))])
        ranges=evidence_ranges(examples[3])
        self.assertEqual(len(ranges),2)
        self.assertEqual(examples[3][slice(*ranges[0])],'我的合成系统叫“Atlas；我希望”。')

    def test_mixed_fact_and_condition_do_not_globally_reject_naming(self):
        self.assertIsNone(modality_problem('我的项目叫 Atlas；希望未来离线。','用户的项目叫 Atlas。','claim'))
        conditional='如果评测通过，我计划发布 Atlas。'
        self.assertIsNone(modality_problem(conditional,'用户计划在评测通过的情况下发布 Atlas。','plan'))
        self.assertIsNotNone(modality_problem(conditional,'用户已经完成发布 Atlas。','event'))
        self.assertIsNone(modality_problem('用户已决定采用 Atlas。','用户已决定采用 Atlas。','decision'))

    def test_negated_intention_and_legacy_metadata_compatibility(self):
        self.assertIsNotNone(modality_problem('我不希望增加自动发布。','用户希望增加自动发布。','plan'))
        self.assertIsNone(modality_problem('我不希望增加自动发布。','用户不希望增加自动发布。','plan'))
        _,spans,_=self.prepare('我希望采用 Atlas。',version='2026-10-01.13')
        result=resolve_plan({'claims':[self.claim(next(iter(spans)),'用户希望采用 Atlas。','plan')]},spans,version='2026-10-01.13')
        self.assertIn('来源对话：Synthetic / 项目 A。',result['claims'][0]['statement'])
        self.assertIn('来源消息日期：2026-02-03',result['claims'][0]['statement'])
        self.assertNotIn('modality',result['claims'][0])

    def test_model_supplied_modality_is_overridden_by_evidence(self):
        _,spans,_=self.prepare('我希望采用 Atlas。')
        claim=self.claim(next(iter(spans)),'用户希望采用 Atlas。','plan') | {'modality':'verified'}
        result=resolve_plan({'claims':[claim]},spans,version='2026-10-01.14')
        self.assertEqual(result['claims'][0]['modality'],'wish')

    def test_artifact_capability_in_request_is_not_optional_grant(self):
        from pipeline.memory_center.modality import modality_problem
        for quote in ('请做成可以折叠的合成清单。', '帮我生成一个可以缩放的合成示意图。'):
            self.assertIsNone(modality_problem(quote, '用户要求制作该合成产物。', 'claim'))
        for quote in ('请做成可以折叠的合成清单，也可以选择普通列表。',
                      '请生成合成图，我允许采用可选布局。'):
            self.assertIsNotNone(modality_problem(quote, '用户要求必须采用折叠布局。', 'claim'))

    def test_permission_cannot_be_promoted_to_mandatory_or_prohibited(self):
        for quote in ('我可以为合成项目采用 Atlas。','合成项目支持可选离线查询。',
                      '我允许合成项目使用离线查询。','The synthetic project may use Atlas.',
                      'The synthetic project can use Atlas.'):
            for statement in ('用户要求合成项目采用 Atlas。','合成项目必须采用 Atlas。',
                              '合成项目应当采用 Atlas。','用户禁止采用 Atlas。',
                              'The synthetic project must use Atlas.'):
                with self.subTest(quote=quote,statement=statement):
                    self.assertIsNotNone(modality_problem(quote,statement,'claim'))

    def test_permission_guard_preserves_weaker_statements_and_mixed_constraints(self):
        for quote,statement in (
            ('我可以采用 Atlas。','用户可以采用 Atlas。'),
            ('我的项目叫 Atlas，可以离线查询。','用户的项目叫 Atlas。'),
            ('我的项目叫 Atlas，可以离线查询。','用户不要求离线查询。'),
            ('我的项目叫 Atlas，可以离线查询。','用户不要求项目必须支持离线查询。'),
            ('The synthetic project may use Atlas.','Atlas is not required.'),
            ('我的项目可以离线查询，但必须保留出处。','项目必须保留出处。'),
            ('我允许离线查询，不允许自动发布。','用户禁止自动发布。'),
            ('我的项目可以离线查询，我已决定默认离线。','用户已决定默认离线。'),
            ('如果独立评测通过，我可以采用 Atlas。','如果独立评测通过，用户可以采用 Atlas。'),
        ):
            with self.subTest(quote=quote,statement=statement):
                self.assertIsNone(modality_problem(quote,statement,'claim'))

    def test_permission_promotion_is_rejected_in_resolver_with_exact_evidence(self):
        text='合成项目可以采用离线查询。'
        _,spans,_=self.prepare(text)
        with self.assertRaises(Invalid):
            resolve_plan({'claims':[self.claim(next(iter(spans)),'合成项目必须采用离线查询。')]},
                         spans,version='2026-10-01.14')
        self.assertEqual(next(iter(spans.values()))['quote'],text)


if __name__=='__main__':unittest.main()

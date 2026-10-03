"""Independent v19 scope acceptance, entirely synthetic and provider-free.

These contrasts were selected before reading the new scope implementation or
provider prompt. A mechanical pass is not semantic or whole-batch approval.
"""
import unittest

from pipeline.memory_center.core import Invalid
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan


VERSION = '2026-10-03.19'
LEGACY = '2026-10-03.18'


class ScopeV19AdversarialTest(unittest.TestCase):
    def prepare(self, text, version=VERSION):
        request, spans, routes = prepare_request('conversation', [{
            'id': 'synthetic-v19', 'role': 'user', 'text': text,
            'source_title': 'Synthetic independent scope audit',
            'created_at': '2026-01-02',
        }], version=version, source_metadata={'visibility': 'visible_only'})
        self.assertEqual(''.join(item['quote'] for item in spans.values()), text)
        for item in spans.values():
            self.assertEqual(text[item['start']:item['end']], item['quote'])
        return request, spans, routes

    def resolve(self, spans, sid, statement, kind='plan', version=VERSION):
        return resolve_plan({'claims': [{
            'topic': 'projects', 'kind': kind, 'subject': 'user',
            'statement': statement, 'evidence_id': sid,
        }]}, spans, version=version)['claims'][0]

    @unittest.expectedFailure
    def test_independent_wish_before_other_project_condition_is_deliverable(self):
        # Frozen coverage target remains unimplemented. Expected failure is not
        # acceptance: do not replace this desired split with an abstention test.
        text = '我希望项目 Atlas 保留每条原始证据。如果独立评测通过，我计划发布项目 Orion。'
        request, spans, _ = self.prepare(text)
        self.assertEqual(len(spans), 2)
        first, second = list(spans)
        delivered = self.resolve(spans, first, '用户希望项目 Atlas 保留每条原始证据。')
        self.assertEqual(delivered['modality'], 'wish')
        self.assertEqual(delivered['quote'], text[:text.index('如果')])
        self.assertEqual(request['source_visibility']['status'], 'visible_only')
        with self.assertRaises(Invalid):
            self.resolve(spans, second, '用户计划发布项目 Orion。')
        conditional = self.resolve(spans, second, '如果独立评测通过，用户计划发布项目 Orion。')
        self.assertEqual(conditional['modality'], 'conditional')

    def test_explicit_independence_declaration_delivers_wish_not_approval(self):
        # Supplemental narrow capability, added after implementation review;
        # it cannot substitute for the frozen ordinary different-project case.
        text = ('我希望项目 Atlas 保留每条原始证据。'
                '这项期望独立成立，我尚未批准实施。'
                '如果独立评测通过，我计划发布项目 Orion。')
        _, spans, _ = self.prepare(text)
        self.assertEqual(len(spans), 2)
        first, second = list(spans)
        wish = self.resolve(spans, first, '用户希望项目 Atlas 保留每条原始证据。')
        self.assertEqual(wish['modality'], 'wish')
        self.assertIn('尚未批准实施', wish['quote'])
        with self.assertRaises(Invalid):
            self.resolve(spans, first, '用户已决定项目 Atlas 保留每条原始证据。', 'decision')
        with self.assertRaises(Invalid):
            self.resolve(spans, second, '用户计划发布项目 Orion。')
        self.assertEqual(self.resolve(spans, second,
                         '如果独立评测通过，用户计划发布项目 Orion。')['modality'], 'conditional')

    def test_postposed_condition_cannot_be_discarded(self):
        for text in (
            '我计划发布项目 Atlas。前提是独立评测通过。',
            '我希望项目 Atlas 自动发布。只有独立评测通过才执行。',
        ):
            with self.subTest(text=text):
                _, spans, _ = self.prepare(text)
                self.assertEqual(len(spans), 1)
                with self.assertRaises(Invalid):
                    self.resolve(spans, next(iter(spans)), '用户计划发布项目 Atlas。')

    def test_pronoun_dependency_preserves_antecedent_and_condition(self):
        for text in (
            '如果独立评测通过，我计划发布项目 Atlas。我希望它保留每条证据。',
            '我希望项目 Atlas 保留证据。如果独立评测通过，它会自动发布。',
        ):
            with self.subTest(text=text):
                _, spans, _ = self.prepare(text)
                self.assertEqual(len(spans), 1)
                with self.assertRaises(Invalid):
                    self.resolve(spans, next(iter(spans)), '用户计划自动发布项目 Atlas。')

    def test_same_project_condition_is_not_released_by_repeated_subject(self):
        text = '如果独立评测通过，我计划发布项目 Atlas。另外，我希望项目 Atlas 保留每条证据。'
        _, spans, _ = self.prepare(text)
        self.assertEqual(len(spans), 1)
        with self.assertRaises(Invalid):
            self.resolve(spans, next(iter(spans)), '用户希望项目 Atlas 保留每条证据。')

    def test_quotation_and_list_are_not_independence_declarations(self):
        for text in (
            '如果独立评测通过，要求如下：\n1. 我希望项目 Atlas 保留证据。\n2. 我计划发布项目 Orion。',
            '如果独立评测通过，同事说：“我希望项目 Atlas 保留证据。如果测试通过，我计划发布 Orion。”',
        ):
            with self.subTest(text=text):
                _, spans, _ = self.prepare(text)
                self.assertEqual(len(spans), 1)
                with self.assertRaises(Invalid):
                    self.resolve(spans, next(iter(spans)), '用户计划发布项目 Orion。')

    def test_v19_preserves_v18_modality_safety_and_legacy_scope_shape(self):
        for text, statement, kind in (
            ('我希望项目 Atlas 离线查询。', '用户已决定项目 Atlas 离线查询。', 'decision'),
            ('我允许项目 Atlas 离线查询。', '用户要求项目 Atlas 必须离线查询。', 'claim'),
            ('我不希望项目 Atlas 自动发布。', '用户希望项目 Atlas 自动发布。', 'plan'),
            ('如果独立评测通过，我计划发布项目 Atlas。', '用户已完成发布项目 Atlas。', 'event'),
        ):
            for version in (LEGACY, VERSION):
                with self.subTest(text=text, version=version):
                    _, spans, _ = self.prepare(text, version)
                    with self.assertRaises(Invalid):
                        self.resolve(spans, next(iter(spans)), statement, kind, version)
        legacy_text = '我希望项目 Atlas 保留每条原始证据。如果独立评测通过，我计划发布项目 Orion。'
        _, spans, _ = self.prepare(legacy_text, LEGACY)
        self.assertEqual(len(spans), 1)


if __name__ == '__main__':
    unittest.main()

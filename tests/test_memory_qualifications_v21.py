"""Synthetic omission regressions; no semantic approval or provider calls."""
import unittest
from unittest.mock import patch

from pipeline.memory_center.core import Invalid, encoded, validate_plan
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
from pipeline.memory_center.qualifications import qualification_problem
from pipeline.memory_center.model import Model, ModelOutputError, PROMPT_VERSION


class QualificationV21Test(unittest.TestCase):
    quote = ('我决定：从现在起，以下全部规则长期适用，直到我明确更改：'
             '合成项目 Atlas 所有发布都必须保留审核记录，任何人都不能直接覆盖已发布版本。')
    good = '用户决定从现在起合成项目 Atlas 必须保留审核记录，长期适用，直到用户明确更改。'

    def test_each_shared_limit_is_required_without_auto_repair(self):
        self.assertIsNone(qualification_problem(self.quote, self.good, 'decision'))
        for old, label in (('从现在起', '生效起点'), ('长期适用', '持续时间'),
                           ('直到用户明确更改', '结束条件')):
            with self.subTest(label=label):
                problem = qualification_problem(self.quote, self.good.replace(old, ''), 'decision')
                self.assertIn(label, problem)

    def test_both_entrypoints_reject_missing_start_and_legacy_is_unchanged(self):
        messages = [{'id': 'rule', 'role': 'user', 'text': self.quote}]
        for version in ('2026-10-03.20', '2026-10-03.21'):
            _, spans, _ = prepare_request('conversation', messages, version=version)
            sid = next(iter(spans))
            item = {'topic': 'projects', 'kind': 'decision', 'subject': 'Atlas',
                    'statement': self.good.replace('从现在起', ''), 'evidence_id': sid}
            source = {'source_type': 'conversation', 'trusted_user': False,
                      'payload': encoded(messages), 'processing_method_version': version}
            raw = {k: v for k, v in item.items() if k != 'evidence_id'}
            raw.update(message_id='rule', quote=self.quote)
            if version.endswith('.21'):
                with self.assertRaisesRegex(Invalid, '生效起点'):
                    resolve_plan({'claims': [item]}, spans, version=version)
                with self.assertRaisesRegex(Invalid, '生效起点'):
                    validate_plan({'claims': [raw]}, source)
            else:
                resolve_plan({'claims': [item]}, spans, version=version)
                validate_plan({'claims': [raw]}, source)

    def test_source_date_wrapper_cannot_replace_start(self):
        messages = [{'id': 'rule', 'role': 'user', 'text': self.quote,
                     'created_at': '2026-01-01'}]
        statement = ('来源消息日期：2026-01-01（非事件成立时间，当前有效性待核实）。'
                     + self.good.replace('从现在起', ''))
        raw = {'topic': 'projects', 'kind': 'decision', 'subject': 'Atlas',
               'statement': statement, 'message_id': 'rule', 'quote': self.quote}
        with self.assertRaisesRegex(Invalid, '生效起点'):
            validate_plan({'claims': [raw]}, {'source_type': 'conversation',
                'trusted_user': False, 'payload': encoded(messages),
                'processing_method_version': '2026-10-03.21'})

    def test_negated_markers_do_not_count_as_preservation(self):
        for old in ('从现在起', '长期适用', '直到用户明确更改'):
            with self.subTest(old=old):
                self.assertIn('否定', qualification_problem(self.quote, self.good.replace(old, '不是（' + old + '）'), 'decision'))

    def test_adapter_rejects_omission_with_measured_usage(self):
        messages = [{'id': 'rule', 'role': 'user', 'text': self.quote}]
        _, spans, _ = prepare_request('conversation', messages, version=PROMPT_VERSION)
        item = {'topic': 'projects', 'kind': 'decision', 'subject': 'Atlas',
                'statement': self.good.replace('从现在起', ''), 'evidence_id': next(iter(spans))}
        with patch.object(Model, '_call', return_value=({'claims': [item]}, {'total_tokens': 17})):
            with self.assertRaises(ModelOutputError) as caught:
                Model().extract(messages)
        self.assertEqual(caught.exception.usage['total_tokens'], 17)
        self.assertEqual(caught.exception.usage['qualification_guard_version'], 'shared-rule-time-v1')
        self.assertEqual(caught.exception.code, 'source_span_contract')

    def test_two_rules_preserve_same_time_without_changing_evidence(self):
        messages = [{'id': 'rule', 'role': 'user', 'text': self.quote}]
        _, spans, _ = prepare_request('conversation', messages, version=PROMPT_VERSION)
        claims = [{'topic': 'projects', 'kind': 'decision', 'subject': 'Atlas',
                   'statement': text, 'evidence_id': next(iter(spans))}
                  for text in (self.good,
                      '用户决定从现在起合成项目 Atlas 任何人不能直接覆盖已发布版本，长期适用，直到用户明确更改。')]
        with patch.object(Model, '_call', return_value=({'claims': claims}, {'total_tokens': 17})):
            plan, usage = Model().extract(messages)
        self.assertEqual(len(plan['claims']), 2)
        self.assertTrue(all(claim['quote'] == self.quote for claim in plan['claims']))
        self.assertFalse(usage['quality_assessment']['quality_approved'])
        self.assertIsNone(qualification_problem(self.quote,
            '用户确定 Atlas 保留记录。', 'suggestion'))
        self.assertIn('生效起点', qualification_problem(self.quote,
            '用户确定 Atlas 保留记录。', 'claim'))

    def test_mixed_scope_abstains_without_copying_qualifications(self):
        for quote in (
            'Atlas 从现在起保留历史；Orion 从明年开始禁止覆盖。',
            '第一条仅试行三个月；第二条长期有效。',
            '本周开始收集；只有审核通过后才开放。',
            self.quote + '张某建议从下月实施另一条规则。',
            '用户转述“从现在起我们保留历史”。',
            '这条规则从现在起不生效。',
            '合成规则：自下次发布起执行；发布日期未知。',
            '仅 Atlas 长期保存，Orion 不适用。',
            '我决定：从现在起，以下全部规则长期适用，直到我明确更改：Atlas 必须保留日志，Orion 半年后才生效且不得覆盖版本。',
            '我决定：从现在起，以下全部规则长期适用，直到我明确更改：Atlas 必须保留日志，但 Orion 规则有效期三个月。',
            '旧项目必须保留日志。从现在起，新项目必须记录版本。这个要求长期适用，直到我明确更改。',
            '从现在起，Atlas 必须保留日志，Orion 必须记录版本。这个要求长期适用，直到我明确更改。',
        ):
            with self.subTest(quote=quote):
                self.assertIsNone(qualification_problem(quote, '用户要求保留历史。', 'claim'))
        self.assertIsNone(qualification_problem(self.quote, '张某建议删除历史。', 'suggestion'))


if __name__ == '__main__':
    unittest.main()

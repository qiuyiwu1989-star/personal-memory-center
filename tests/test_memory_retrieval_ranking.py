"""Synthetic domain-independent lexical ranking; no private benchmark questions."""
import copy
import unittest
from pipeline.memory_center.retrieval_ranking import rank_records, score_record, query_terms


def row(statement='', **changes):
    return dict(statement=statement, subject='', topic='', **changes)


class LexicalRankingTest(unittest.TestCase):
    def test_shared_single_han_is_not_relevant(self):
        self.assertEqual(rank_records([row('蔬菜价格下降'), row('会议安排已更新')], '仓库预算'), [])
        self.assertEqual(rank_records([row('甲乙丙丁')], '甲戊己丁'), [])
        self.assertEqual(rank_records([row('甲乙在别的地方')], '甲乙丙丁戊'), [])

    def test_short_phrase_and_question_wrapper(self):
        expected = row('合成仓库预算为十元')
        self.assertEqual(rank_records([expected, row('合成仓库模型讨论')], '预算'), [expected])
        self.assertEqual(rank_records([expected], '请问我的预算是什么呢？'), [expected])
        self.assertIn('目的', query_terms('目的').phrases)

    def test_long_phrase_partial_requires_two_pairs(self):
        target = row('合成太阳能供电需要逆变器')
        self.assertEqual(rank_records([target], '太阳能配置'), [target])
        self.assertEqual(rank_records([row('合成太阳照片')], '太阳能配置'), [])

    def test_latin_boundaries_case_and_nfkc(self):
        target = row('Synthetic Postgres INDEX configuration')
        self.assertEqual(rank_records([target, row('Synthetic indexing subpostgres')], 'Ｐｏｓｔｇｒｅｓ index'), [target])
        self.assertEqual(rank_records([row('Synthetic configuration')], 'fig'), [])
        self.assertEqual(rank_records([target], 'what is my index'), [target])

    def test_entity_and_title_weights_and_no_quote_index(self):
        statement = row('合成北星计划')
        entity = row('合成一般说明', governance={'subject_id':'北星计划'})
        title = row('合成一般说明', source_title='北星计划')
        self.assertEqual(rank_records([title, statement, entity], '北星计划'), [entity, statement, title])
        self.assertEqual(rank_records([row('合成 unrelated', quote='北星计划')], '北星计划'), [])
        self.assertGreater(score_record(row('合成一般说明', scope='北星计划'), '北星计划'), 0)

    def test_duplicates_translation_and_occurrences_do_not_inflate(self):
        original = row('合成预算')
        self.assertEqual(score_record(original, '预算'), score_record(row('合成预算', display_statement='合成预算'), '预算'))
        self.assertEqual(score_record(original, '预算'), score_record(row('合成预算预算预算'), '预算'))

    def test_single_character_only_explicit_entity(self):
        target = dict(statement='合成一般说明', subject='甲', topic='')
        self.assertEqual(rank_records([row('甲在仓库'), target], '甲'), [target])

    def test_no_mutation_empty_query_and_stable_ties(self):
        records = [row('合成预算一', id='a'), row('合成预算二', id='b')]
        before = copy.deepcopy(records)
        self.assertEqual(rank_records(records, '预算'), records)
        self.assertEqual(rank_records(records, '  '), records)
        self.assertEqual(records, before)
        self.assertEqual(rank_records(records, 'what is the'), [])


if __name__ == '__main__': unittest.main()

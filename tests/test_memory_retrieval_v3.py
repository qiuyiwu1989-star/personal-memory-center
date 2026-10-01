"""Explicitly synthetic, domain-independent v3 examples; no private labels."""
import copy
import unittest
from pipeline.memory_center.retrieval_ranking import (
    query_terms_v3, rank_records, rank_records_v3, score_record_v3, search_records,
)


def row(statement='', **extras):
    return dict(statement=statement, subject='', topic='', **extras)


class LexicalV3Tests(unittest.TestCase):
    def test_two_han_keyword_inside_natural_question(self):
        target = row('合成预算为十元')
        query = '请问仓库的预算是什么呢？'
        self.assertEqual(rank_records([target], query), [])
        self.assertEqual(rank_records_v3([target], query), [target])

    def test_functional_connector_splits_but_retains_full_name(self):
        self.assertIn('预算', query_terms_v3('关于仓库的预算').phrases)
        target = row('合成和美计划已启动')
        self.assertEqual(rank_records_v3([target], '和美计划'), [target])

    def test_single_han_overlap_still_abstains(self):
        self.assertEqual(rank_records_v3([row('蔬菜价格下降')], '仓库的预算'), [])
        self.assertEqual(rank_records_v3([row('甲戊己丁')], '甲乙丙丁'), [])
        self.assertEqual(rank_records_v3([row('甲乙在仓库')], '甲和乙'), [])

    def test_single_bigram_of_unsplit_long_phrase_still_abstains(self):
        self.assertEqual(rank_records_v3([row('合成太阳照片')], '太阳能配置'), [])
        target = row('合成太阳能供电')
        self.assertEqual(rank_records_v3([target], '太阳能配置'), [target])

    def test_scope_and_topic_cannot_open_gate(self):
        self.assertEqual(rank_records_v3([row('合成 unrelated', scope='预算')], '预算'), [])
        self.assertEqual(rank_records_v3([dict(statement='合成 unrelated', subject='', topic='预算')], '预算'), [])
        target = row('合成预算说明', scope='仓库')
        self.assertGreater(score_record_v3(target, '仓库的预算'), 0)

    def test_latin_and_unicode_boundaries(self):
        target = row('Synthetic POSTGRES configuration')
        self.assertEqual(rank_records_v3([target, row('Synthetic subpostgres')], 'Ｐｏｓｔｇｒｅｓ'), [target])
        self.assertEqual(rank_records_v3([row('Synthetic indexer')], 'index'), [])

    def test_entities_and_titles_rank_by_weights(self):
        statement = row('合成预算说明')
        entity = row('合成一般说明', governance={'subject_id':'预算'})
        title = row('合成一般说明', source_title='预算')
        self.assertEqual(rank_records_v3([title, statement, entity], '预算'), [entity, statement, title])

    def test_quoted_evidence_not_searched(self):
        self.assertEqual(rank_records_v3([row('合成 unrelated', quote='预算')], '预算'), [])

    def test_single_han_explicit_entity_only(self):
        target = dict(statement='合成一般说明', subject='甲', topic='')
        self.assertEqual(rank_records_v3([row('甲在仓库'), target], '甲'), [target])

    def test_grammar_only_query_abstains(self):
        self.assertEqual(rank_records_v3([row('合成预算')], '请帮我查询一下是什么呢？'), [])
        self.assertEqual(rank_records_v3([row('Synthetic general')], 'what is the'), [])

    def test_translation_repetition_not_inflate(self):
        target = row('合成预算')
        expected = score_record_v3(target, '仓库的预算')
        self.assertEqual(expected, score_record_v3(row('合成预算', display_statement='合成预算'), '仓库的预算'))
        self.assertEqual(expected, score_record_v3(row('合成预算预算预算'), '仓库的预算'))

    def test_empty_query_stable_ties_and_no_mutation(self):
        records = [row('合成预算一', id='a'), row('合成预算二', id='b')]
        before = copy.deepcopy(records)
        self.assertEqual(rank_records_v3(records, '  '), records)
        self.assertEqual(rank_records_v3(records, '预算'), records)
        self.assertEqual(records, before)

    def test_v3_explicit_and_default_remains_v1(self):
        irrelevant = row('合成库房施工')
        self.assertEqual(search_records([irrelevant], '仓库的预算'), [irrelevant])
        self.assertEqual(search_records([irrelevant], '仓库的预算', 'lexical-v3'), [])


if __name__ == '__main__':
    unittest.main()

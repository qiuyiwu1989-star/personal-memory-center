"""Explicitly synthetic source routing inheritance and integrity tests."""
import copy
import unittest
from pipeline.memory_center.core import Invalid
from pipeline.memory_center.long_source_plan import plan_long_source
from pipeline.memory_center.source_context import inherit_source_context
from pipeline.memory_center.scope_review import prepare_long_source_review

METHOD='2026-10-04.22'

class SourceContextTests(unittest.TestCase):
    def envelope(self, text, role='user', source_type='conversation'):
        return {'source_key':'synthetic-context','scope':'synthetic:inbox','source_type':source_type,
            'source_metadata':{'visibility':'visible_only'},'messages':[{'id':'original',
            'role':role,'text':text,'source_title':'Synthetic fixture','created_at':'2026-01-01'}]}
    def inherit(self, envelope):
        return inherit_source_context(envelope,plan_long_source(**envelope),version=METHOD)
    def test_pasted_template_tail_never_becomes_personal_evidence(self):
        env=self.envelope('请参考。\n你是助手，核心使命：'+'合成模板：我决定部署。'*3000)
        packet=prepare_long_source_review(env,plan_long_source(**env),version=METHOD)
        self.assertGreater(packet['independent_segment_evidence_characters'],0)
        self.assertLessEqual(packet['extraction_evidence_characters'],len('请参考。'))
        self.assertTrue(all('合成模板' not in item['quote'] for segment in packet['segments']
            for item in segment['inherited_context']['evidence_spans']))
        for segment in packet['segments']:
            inherited=segment['inherited_context']
            self.assertEqual(inherited['complete_source_route'],'mixed_reference_document')
            self.assertEqual(inherited['reference_reason'],'role_template')
            self.assertFalse(inherited['automatic_extraction_authorized'])
    def test_outer_statement_retained_reference_tail_excluded(self):
        env=self.envelope('我的长期目标是改善合成系统。\n你是助手，核心使命：'+'合成模板正文。'*5000)
        result=self.inherit(env)
        quotes=[item['quote'] for segment in result['segments'] for item in segment['evidence_spans']]
        self.assertEqual(quotes,['我的长期目标是改善合成系统。'])
        self.assertLess(result['inherited_evidence_characters'],100)
        self.assertTrue(all(not segment['automatic_extraction_authorized'] for segment in result['segments']))
    def test_assistant_role_retained_and_not_made_user(self):
        result=self.inherit(self.envelope('我决定上线。'*5000,role='assistant'))
        self.assertEqual(result['inherited_evidence_characters'],0)
        self.assertTrue(all(segment['declared_author_context']['role']=='assistant' for segment in result['segments']))
        self.assertTrue(all(segment['complete_source_route']=='assistant_reference' for segment in result['segments']))
    def test_external_author_declaration_not_identity_proof(self):
        result=self.inherit(self.envelope('我的长期目标是合成研究。',role='external',source_type='document'))
        self.assertEqual(result['segments'][0]['declared_author_context']['role'],'external')
        self.assertFalse(result['segments'][0]['author_identity_verified'])
        self.assertEqual(result['source_visibility']['status'],'visible_only')
    def test_evidence_boundary_not_clipped_and_offsets_bind_original(self):
        env=self.envelope('合成\"背景。'*4101+'如果审批通过，我才启动项目。')
        result=self.inherit(env)
        self.assertGreater(result['boundary_blocked_evidence_characters'],0)
        self.assertEqual(result['inherited_evidence_characters']+result['boundary_blocked_evidence_characters'],result['complete_source_evidence_characters'])
        for segment in result['segments']:
            for evidence in segment['evidence_spans']:
                loc=evidence['original_locator']
                self.assertEqual(env['messages'][0]['text'][loc['start']:loc['end']],evidence['quote'])
                self.assertEqual(loc['global_start'],loc['start'])
                self.assertEqual(loc['message_id'],'original')
        self.assertTrue(any(segment['boundary_review_spans'] for segment in result['segments']))
    def test_global_offsets_include_previous_original_message(self):
        env=self.envelope('合成前言。')
        env['messages'].append({'id':'second','role':'user','text':'我的目标是合成研究。'})
        result=self.inherit(env)
        loc=result['segments'][1]['evidence_spans'][0]['original_locator']
        self.assertEqual(loc['global_start'],len(env['messages'][0]['text']))
        self.assertEqual(loc['message_id'],'second')
    def test_neighbor_condition_and_later_correction_remain_review_context(self):
        env=self.envelope('如果审批通过，才可以启动项目。')
        env['messages'].append({'id':'reply','role':'assistant','text':'建议上线。'})
        env['messages'].append({'id':'correction','role':'user','text':'更正：审批尚未通过。'})
        result=self.inherit(env)
        middle=result['segments'][1]
        self.assertIn('neighbor_condition_requires_semantic_review',middle['review_reasons'])
        self.assertEqual([item['message_id']for item in middle['context_message_locators']],['original','reply','correction'])
        self.assertEqual(middle['evidence_spans'],[])
        self.assertFalse(middle['automatic_extraction_authorized'])
    def test_original_and_archive_tampering_refused(self):
        env=self.envelope('我的长期目标是合成研究。');plan=plan_long_source(**env)
        altered=copy.deepcopy(env);altered['messages'][0]['role']='assistant'
        with self.assertRaises(Invalid):inherit_source_context(altered,plan,version=METHOD)
        for key in ('scope','source_key'):
            altered=copy.deepcopy(env);altered[key]='other'
            with self.assertRaises(Invalid):inherit_source_context(altered,plan,version=METHOD)
        altered=copy.deepcopy(plan);altered['segments'][0]['payload']['messages'][0]['text']='changed'
        with self.assertRaises(Invalid):inherit_source_context(env,altered,version=METHOD)
    def test_explicit_experiment_only_and_legacy_packet_unchanged(self):
        env=self.envelope('我的目标是合成研究。');plan=plan_long_source(**env)
        with self.assertRaises(Invalid):inherit_source_context(env,plan,version='2026-10-03.21')
        packet=prepare_long_source_review(env,plan,version='2026-10-03.21')
        self.assertIsNone(packet['source_context_inheritance'])
        self.assertIsNone(packet['segments'][0]['inherited_context'])
        self.assertEqual(packet['model_calls'],0)

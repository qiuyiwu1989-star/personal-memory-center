"""Synthetic adapter/diagnostic contracts, not actual LLM semantic performance."""
import copy
import json
import unittest
import test_memory_generation_v14 as generation_fixture
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
from pipeline.memory_center.extraction_quality import review


class GenerationV15Test(unittest.TestCase):
    environment=generation_fixture.GenerationV14Test.environment
    invoke=generation_fixture.GenerationV14Test.invoke

    def test_quoted_first_person_owner_assignment_requires_review_not_adoption(self):
        text='收到同事发来的邮件：我经营一家陶艺工坊，我担心活动会占用大家时间，请代我询问。'
        def respond(payload):
            span=payload['messages'][0]['evidence_spans'][0]
            return {'claims':[{'topic':'profile','kind':'claim','subject':'user',
                'statement':'用户经营一家陶艺工坊，并担心活动占用大家时间。',
                'evidence_id':span['evidence_id']}]}
        (plan,usage),calls=self.invoke([{'id':'letter','role':'user','text':text}],respond)
        self.assertEqual(len(calls),1)
        self.assertIn('nested_speaker_review',usage['quality_assessment']['items'][0]['codes'])
        self.assertEqual(plan['claims'][0]['quote'],text)
        self.assertFalse(usage['quality_assessment']['quality_approved'])

    def test_omitted_historical_resource_beside_question_is_source_signal(self):
        text='I have domain synthetic.invalid. How should I organize a one-day exhibition?'
        (plan,usage),calls=self.invoke([{'id':'asset','role':'user','text':text}],lambda payload:{'claims':[]})
        self.assertEqual(plan,{'claims':[]})
        self.assertEqual(len(calls),1)
        signals=usage['quality_assessment']['source_signals']
        self.assertEqual(signals[0]['code'],'historical_self_report_review')
        self.assertNotIn(text,json.dumps(signals))
        self.assertFalse(usage['quality_assessment']['semantics_verified'])

    def test_coverage_warning_does_not_fabricate_missing_quote_or_delete_claim(self):
        claims=[{'topic':'projects','kind':'claim','subject':'atelier','statement':'草案包括教学、展览、出版。',
                 'quote':'草案包括教学、展览。','message_id':'draft'}]
        before=copy.deepcopy(claims)
        assessment=review(claims)
        self.assertIn('enumerated_coverage_review',assessment['items'][0]['codes'])
        self.assertEqual(claims,before)
        self.assertFalse(assessment['quality_approved'])

    def test_single_named_fact_retained_without_global_third_party_or_task_kill(self):
        source={'messages':[{'id':'self','role':'user','text':'我拥有一座工坊；如何规划开放日？'}]}
        c={'topic':'profile','kind':'claim','subject':'user','statement':'用户自述拥有一座工坊。',
           'quote':'我拥有一座工坊；如何规划开放日？','message_id':'self'}
        result=review([c],source)
        self.assertEqual(result['source_signals'],[])
        self.assertEqual(result['items'][0]['disposition'],'candidate')
        source['messages'][0]['text']='以下是朋友来信：我拥有一座工坊；如何规划开放日？'
        self.assertEqual(review([],source)['source_signals'],[])

    def test_source_metadata_and_modality_remain_compatible_across_versions(self):
        messages=[{'id':'m','role':'user','text':'如果评测通过，我希望未来开放工作坊。',
                   'source_title':'Synthetic Atelier','created_at':'2026-02-03'}]
        for version in ('2026-10-01.13','2026-10-01.14','2026-10-02.15'):
            with self.subTest(version=version):
                request,spans,_=prepare_request('conversation',messages,version=version)
                sid=request['messages'][0]['evidence_spans'][0]['evidence_id']
                plan=resolve_plan({'claims':[{'topic':'projects','kind':'plan','subject':'user',
                    'statement':'如果评测通过，用户希望未来开放工作坊。','evidence_id':sid}]},spans,version=version)
                c=plan['claims'][0]
                self.assertTrue(c['statement'].startswith('来源消息日期：2026-02-03'))
                self.assertIn('来源对话：Synthetic Atelier。',c['statement'])
                self.assertEqual(messages[0]['text'][c['start']:c['end']],c['quote'])
                if version!='2026-10-01.13':self.assertEqual(c['modality'],'conditional')


if __name__=='__main__':unittest.main()

"""Synthetic, narrow explicit scope contrasts; no production or provider calls."""
import json
import unittest
from pipeline.memory_center.core import Invalid, validate_plan
from pipeline.memory_center.extraction_input import prepare_request, resolve_plan
from pipeline.memory_center.modality import scoped_evidence_ranges, scoped_evidence_ranges_v19

VERSION='2026-10-03.19'
POSITIVE='我希望 Atlas 保存完整证据。这项期望独立成立，尚未批准实施。如果预算获批，我计划发布 Orion。'


class ScopeV19Test(unittest.TestCase):
    def prepared(self,text=POSITIVE,version=VERSION):
        message={'id':'synthetic','role':'user','text':text,'source_title':'Synthetic scope',
                 'created_at':'2026-01-02'}
        return prepare_request('conversation',[message],version=version,
                               source_metadata={'visibility':'visible_only'})

    def test_explicit_independence_is_lossless_and_local(self):
        request,spans,_=self.prepared()
        self.assertEqual(len(spans),2)
        self.assertEqual(''.join(s['quote'] for s in spans.values()),POSITIVE)
        for span in spans.values():
            self.assertEqual(POSITIVE[span['start']:span['end']],span['quote'])
        self.assertEqual([p['modality_hint'] for p in request['messages'][0]['evidence_spans']],
                         ['wish','conditional'])
        self.assertEqual(request['source_visibility']['status'],'visible_only')

    def test_declaration_and_negated_approval_both_required(self):
        texts=(
            '我希望 Atlas 保存证据。另外，如果预算获批，我计划发布 Orion。',
            '我希望 Atlas 保存证据，尚未批准实施。如果预算获批，我计划发布 Orion。',
            '我希望 Atlas 保存证据。这项期望独立成立。如果预算获批，我计划发布 Orion。',
            '我希望 Atlas 保存证据。我没有批准实施。如果预算获批，我计划发布 Orion。',
            '我希望 Atlas 保存证据。这只是我的期望，目前没有批准开发，也没有上线日期。如果预算获批，我计划发布 Orion。',
            POSITIVE.replace('我计划','我们计划'),
        )
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(scoped_evidence_ranges_v19(text),[(0,len(text))])

    def test_shared_postposed_and_pronominal_conditions_remain_whole(self):
        texts=(
            '如果审核通过，'+POSITIVE,
            POSITIVE+'两项都以审核通过为前提。',
            POSITIVE.replace('发布 Orion','实施上述期望'),
            POSITIVE.replace('发布 Orion','将它上线'),
            POSITIVE.replace('发布 Orion','发布 Orion，如果测试通过'),
            POSITIVE.replace('保存完整证据','保存证据并计划发布 Atlas'),
        )
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(scoped_evidence_ranges_v19(text),[(0,len(text))])

    def test_third_party_quotes_and_lists_remain_whole(self):
        for text in ('团队说：'+POSITIVE,'同事认为'+POSITIVE,'“'+POSITIVE+'”','以下是会议记录：'+POSITIVE,
                     '1. '+POSITIVE,POSITIVE.replace('Atlas','“Atlas”')):
            with self.subTest(text=text):
                self.assertEqual(scoped_evidence_ranges_v19(text),[(0,len(text))])

    def test_legacy_v17_v18_and_old_independent_project_shape_preserved(self):
        for version in ('2026-10-03.17','2026-10-03.18'):
            self.assertEqual(len(self.prepared(version=version)[1]),1)
        self.assertEqual(scoped_evidence_ranges(POSITIVE),[(0,len(POSITIVE))])
        text='如果测试通过，我计划发布 Atlas。我对另一独立项目 Orion 的要求是：保留证据。'
        self.assertEqual(scoped_evidence_ranges_v19(text),scoped_evidence_ranges(text))

    def test_v19_modality_guards_dates_and_source_visibility_inherited(self):
        _,spans,_=self.prepared()
        def claim(sid,statement,kind='claim'):
            return {'topic':'projects','kind':kind,'subject':'user','statement':statement,'evidence_id':sid}
        first,last=list(spans)
        resolved=resolve_plan({'claims':[claim(first,'用户希望 Atlas 保存完整证据。')]},spans,version=VERSION)
        self.assertIn('非事件成立时间',resolved['claims'][0]['statement'])
        self.assertIn('来源对话：Synthetic scope',resolved['claims'][0]['statement'])
        with self.assertRaises(Invalid):
            resolve_plan({'claims':[claim(last,'用户计划发布 Orion。','plan')]},spans,version=VERSION)
        with self.assertRaises(Invalid):
            resolve_plan({'claims':[claim(first,'用户已决定 Atlas 保存证据。','decision')]},spans,version=VERSION)
        conditional=resolve_plan({'claims':[claim(last,'如果预算获批，用户计划发布 Orion。','plan')]},spans,version=VERSION)
        source={'source_type':'conversation','trusted_user':True,'processing_method_version':VERSION,
                'payload':json.dumps([{'id':'synthetic','role':'user','text':POSITIVE,
                                       'source_title':'Synthetic scope','created_at':'2026-01-02'}])}
        result=validate_plan(conditional,source)
        self.assertEqual(result[0]['status'],'user_stated')
        self.assertEqual(result[0]['modality'],'conditional')

if __name__=='__main__':unittest.main()

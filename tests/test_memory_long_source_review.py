"""Synthetic end-to-end private review packets; no provider calls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pipeline.memory_center.core import Invalid
from pipeline.memory_center.long_source_plan import plan_long_source
from pipeline.memory_center.scope_review import prepare_long_source_review

class LongSourceReviewTests(unittest.TestCase):
    def envelope(self):
        return {'source_key':'synthetic','scope':'synthetic:inbox','source_type':'conversation',
            'source_metadata':{'visibility':'complete_visible'},'messages':[
                {'id':'long','role':'user','text':'如果批准，'+'合成背景。'*4100+'才启动项目。'},
                {'id':'reply','role':'assistant','text':'建议直接上线。'},
                {'id':'later','role':'user','text':'更正：尚未批准。'}]}
    def test_literal_coverage_and_context_not_scope_release(self):
        env=self.envelope(); packet=prepare_long_source_review(env,plan_long_source(**env),version='2026-10-04.22')
        self.assertEqual(packet['original_envelope'],env)
        self.assertEqual(packet['archive_characters'],sum(len(m['text'])for m in env['messages']))
        self.assertTrue(packet['archive_verification']['literal_coverage_verified'])
        self.assertGreater(packet['unreviewed_segments'],3)
        for seg in packet['segments']:
            self.assertFalse(seg['automatic_extraction_authorized'])
            if seg['original_locator']['message_index']==0:
                self.assertIn('condition_scope_requires_semantic_review',seg['review_reasons'])
                self.assertIn('partial_message_requires_context_review',seg['review_reasons'])
            if seg['original_locator']['message_index']==1:
                self.assertEqual(seg['input_coverage']['evidence_characters'],0)
        self.assertFalse(packet['quality_approved']); self.assertEqual(packet['model_calls'],0)
    def test_template_routing_change_is_visible_not_approval(self):
        env=self.envelope()
        env['messages']=[{'id':'template','role':'user','text':'请参考。\n你是助手。核心使命：'+ '合成模板正文。'*5000}]
        packet=prepare_long_source_review(env,plan_long_source(**env),version='2026-10-04.22')
        self.assertLess(packet['complete_source_input_coverage']['evidence_characters'],packet['independent_segment_evidence_characters'])
        self.assertLessEqual(packet['extraction_evidence_characters'],packet['complete_source_input_coverage']['evidence_characters'])
        self.assertTrue(any('segment_routing_differs_from_complete_source' in s['review_reasons']for s in packet['segments']))
        self.assertTrue(all(not s['automatic_extraction_authorized']for s in packet['segments']))

    def test_tampered_original_scope_and_receipt_refused(self):
        env=self.envelope(); plan=plan_long_source(**env)
        for key,value in [('scope','other'),('source_type','document'),('source_key','other')]:
            changed=copy.deepcopy(env);changed[key]=value
            with self.assertRaises(Invalid):prepare_long_source_review(changed,plan,version='2026-10-04.22')
        changed=copy.deepcopy(plan);changed['segments'][0]['end']-=1
        with self.assertRaises(Invalid):prepare_long_source_review(env,changed,version='2026-10-04.22')
    def test_cli_private_exclusive_and_redacted(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory()as directory:
            source=Path(directory)/'input.json';output=Path(directory)/'packet.json'
            source.write_text(json.dumps(self.envelope()))
            cmd=[sys.executable,str(repo/'scripts/build_long_source_review.py'),'--input',str(source),'--output',str(output)]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn('合成背景',result.stdout)
            self.assertEqual(output.stat().st_mode&0o777,0o600)
            self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,1)
            cmd[-1]=str(repo/'forbidden-review.json')
            self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,1)
            self.assertFalse((repo/'forbidden-review.json').exists())

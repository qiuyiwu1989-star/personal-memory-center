"""Synthetic purpose-limited contexts: provenance survives manual selection."""
import copy
import unittest

from pipeline.memory_center.core import Invalid
from pipeline.memory_center.long_source_plan import plan_long_source
from pipeline.memory_center.bounded_source_request import (
    plan_bounded_source_requests, scoped_source_request, verified_bounded_source_request)

METHOD = '2026-10-04.22'


class ScopedRequestTest(unittest.TestCase):
    def setUp(self):
        self.env = dict(source_key='synthetic:scope', scope='synthetic:inbox',
            source_type='conversation', source_metadata={}, messages=[
                dict(id='request', role='user', text='请分析这次合成会议。'),
                dict(id='transcript', role='external', text='合成录音，人物甲发言。\n' * 120),
                dict(id='correction', role='user', text='更正：说话人一是合成人物甲，说话人二仍然未知。')])
        self.archive = plan_long_source(**self.env)
        bundles = plan_bounded_source_requests(self.env, self.archive, version=METHOD)['requests']
        self.base = next(x for x in bundles if x['request']['messages'][0]['id']=='correction')
        self.selection = dict(purpose='historical_speaker_correction',
            base_request_id=self.base['request_id'],
            source_canonical_sha256=self.archive['source_canonical_sha256'],
            context_ranges=[dict(message_id='correction', start=0,
                end=len(self.env['messages'][2]['text'])),
                dict(message_id='transcript', start=0, end=14)])

    def build(self, selection=None, **kwargs):
        return scoped_source_request(self.env, self.archive,
            selection if selection is not None else self.selection, version=METHOD, **kwargs)

    def test_exact_evidence_roles_offsets_and_omissions_survive(self):
        b = self.build()
        self.assertEqual(b['spans'], self.base['spans'])
        self.assertEqual(b['routes'], self.base['routes'])
        self.assertEqual(b['request']['messages'], self.base['request']['messages'])
        context=b['request']['source_context']
        self.assertEqual(context[0]['declared_role'],'external')
        self.assertEqual(context[0]['text'],self.env['messages'][1]['text'][:14])
        policy=b['request']['context_policy']
        self.assertFalse(b['context_complete'])
        self.assertEqual(policy['semantic_sufficiency'],'not_approved')
        self.assertIn('request',policy['omitted_message_ids'])
        self.assertTrue(any(x['message_id']=='transcript' and x['start']==14 for x in policy['omitted_ranges']))
        self.assertFalse(b['quality_approved'])
        self.assertFalse(b['automatic_extraction_authorized'])
        self.assertNotEqual(b['request_id'],self.base['request_id'])
        self.assertEqual(verified_bounded_source_request(self.env,self.archive,b['request_id'],
            version=METHOD,context_selection=self.selection),b)

    def test_selection_order_is_canonical_but_changed_context_breaks_binding(self):
        b=self.build(); changed=copy.deepcopy(self.selection)
        changed['context_ranges'].reverse()
        self.assertEqual(b,self.build(changed))
        changed['context_ranges'][0]['end']+=1
        self.assertNotEqual(b['request_id'],self.build(changed)['request_id'])
        with self.assertRaises(Invalid):
            verified_bounded_source_request(self.env,self.archive,b['request_id'],
                version=METHOD,context_selection=changed)

    def test_missing_quote_or_overlapping_context_rejected(self):
        changed=copy.deepcopy(self.selection);changed['context_ranges'][0]['start']=1
        with self.assertRaises(Invalid):self.build(changed)
        changed=copy.deepcopy(self.selection);changed['context_ranges'].append(changed['context_ranges'][1])
        with self.assertRaises(Invalid):self.build(changed)

    def test_invalid_ranges_and_purpose_fail_closed(self):
        for key,value in [('start',True),('start',-1),('end',999999),('message_id','invented')]:
            changed=copy.deepcopy(self.selection);changed['context_ranges'][0][key]=value
            with self.assertRaises(Invalid):self.build(changed)
        changed=copy.deepcopy(self.selection);changed['purpose']='confirm_all_people'
        with self.assertRaises(Invalid):self.build(changed)
        with self.assertRaises(Invalid):self.build(dict(self.selection,context_ranges=[]))

    def test_tampered_source_or_base_rejected(self):
        for key,value in [('source_canonical_sha256','0'*64),('base_request_id','req:invented')]:
            with self.assertRaises(Invalid):self.build(dict(self.selection,**{key:value}))
        self.env['messages'][1]['role']='user'
        with self.assertRaises(Invalid):self.build()

    def test_full_coverage_is_literal_only_and_size_limit_never_truncates(self):
        selected=dict(self.selection,context_ranges=[dict(message_id=m['id'],start=0,end=len(m['text']))
            for m in self.env['messages']])
        b=self.build(selected)
        self.assertTrue(b['context_complete'])
        self.assertFalse(b['quality_approved'])
        self.assertEqual(b['request']['context_policy']['semantic_sufficiency'],'not_approved')
        # Existing base request fits; the extra explicit range inventory need
        # not fit the same limit. Both stages reject rather than slice text.
        with self.assertRaises(Invalid):self.build(selected,max_request_bytes=1024)

    def test_cli_private_output_no_source_logs_and_no_overwrite(self):
        import json, stat, subprocess, sys, tempfile
        from pathlib import Path
        script=Path(__file__).resolve().parents[1]/'scripts/build_bounded_scope_request.py'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'source.json';selection=root/'selection.json';output=root/'out.json'
            source.write_text(json.dumps(self.env),encoding='utf-8')
            selection.write_text(json.dumps(self.selection),encoding='utf-8')
            command=[sys.executable,str(script),'--input',str(source),'--selection',str(selection),'--output',str(output)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o600)
            self.assertFalse(json.loads(output.read_text())['quality_approved'])
            self.assertNotIn('合成人物',result.stdout+result.stderr)
            old=output.read_bytes()
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(old,output.read_bytes())

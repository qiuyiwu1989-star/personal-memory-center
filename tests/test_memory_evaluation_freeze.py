"""Synthetic review binding tests, no real extraction or sources."""
import copy
import unittest
from pipeline.memory_center.evaluation_freeze import digest,review_binding,trial_readiness

class TrialBindingTest(unittest.TestCase):
    def setUp(self):
        c=dict(case_id='synthetic',source_sha256=digest('source'),method_version='synthetic-v',
               prompt_sha256=digest('prompt'),model_profile_sha256=digest('profile'))
        self.manifest=dict(cases=[c],token_limit=100,holdout_independence='verified')
        self.run=dict(c,claims=[{'statement':'Synthetic supported claim','quote':'Synthetic evidence'}],usage={'total_tokens':20})
        self.run['review']=dict.fromkeys(('semantic_support','speaker_attribution','time_handling','scope_handling','durable_value','coverage'),'pass')
        self.run['review']['binding_sha256']=review_binding(self.run,c)
    def result(self):return trial_readiness(self.manifest,[self.run])
    def test_exact_binding_makes_decision_ready_never_approves(self):
        result=self.result();self.assertTrue(result['ready_for_quality_decision'])
        self.assertFalse(result['quality_approved']);self.assertFalse(result['production_dispatch_enabled'])
    def test_output_changed_after_review_blocks(self):
        self.run['claims'][0]['statement']='Synthetic changed meaning'
        self.assertIn('synthetic:stale_or_missing_review',self.result()['blocking_reasons'])
    def test_source_or_configuration_changed_blocks(self):
        for field in ('source_sha256','method_version','prompt_sha256','model_profile_sha256'):
            run=copy.deepcopy(self.run);run[field]='changed'
            self.assertIn('synthetic:frozen_input_mismatch',trial_readiness(self.manifest,[run])['blocking_reasons'])
    def test_unknown_cost_retains_reservation_and_blocks(self):
        self.run['usage']={};self.run['reserved_tokens']=90
        result=self.result();self.assertEqual(result['charged_or_reserved_tokens'],90)
        self.assertIn('unknown_usage_requires_resolution',result['blocking_reasons'])
        self.run['reserved_tokens']=101;self.assertIn('trial_budget_exceeded',self.result()['blocking_reasons'])
    def test_empty_positive_cannot_pass_and_negative_explicit(self):
        self.run['claims']=[];self.run['review']['binding_sha256']=review_binding(self.run,self.manifest['cases'][0])
        self.assertIn('synthetic:empty_positive_output',self.result()['blocking_reasons'])
        self.manifest['cases'][0]['requires_nonempty_claims']=False
        self.run['review']['binding_sha256']=review_binding(self.run,self.manifest['cases'][0])
        self.assertTrue(self.result()['ready_for_quality_decision'])
    def test_pending_independence_duplicate_missing_and_unreviewed_coverage(self):
        self.manifest['holdout_independence']='unknown';self.run['review']['coverage']='pending'
        reasons=self.result()['blocking_reasons'];self.assertIn('independence_not_verified',reasons)
        self.assertIn('synthetic:review_incomplete_or_failed',reasons)
        for runs in ([],[self.run,self.run]):
            self.assertIn('synthetic:missing_or_duplicate_run',trial_readiness(self.manifest,runs)['blocking_reasons'])

    def test_cli_private_receipt_permissions_and_refuses_overwrite(self):
        import tempfile,json,subprocess,sys,stat
        from pathlib import Path
        script=Path(__file__).resolve().parents[1]/'scripts/evaluate_memory_trial_binding.py'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'manifest.json';runs=root/'runs.json';out=root/'receipt.json'
            manifest.write_text(json.dumps(self.manifest));runs.write_text(json.dumps([self.run]))
            command=[sys.executable,str(script),'--manifest',str(manifest),'--runs',str(runs),'--output',str(out)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(stat.S_IMODE(out.stat().st_mode),0o600)
            self.assertNotIn('Synthetic supported claim',result.stdout)
            original=out.read_bytes();self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(out.read_bytes(),original)
    def test_cli_blocked_review_has_nonzero_exit_and_no_approval(self):
        import tempfile,json,subprocess,sys
        from pathlib import Path
        script=Path(__file__).resolve().parents[1]/'scripts/evaluate_memory_trial_binding.py'
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'manifest.json';runs=root/'runs.json';out=root/'receipt.json'
            self.manifest['holdout_independence']='unknown'
            manifest.write_text(json.dumps(self.manifest));runs.write_text(json.dumps([self.run]))
            result=subprocess.run([sys.executable,str(script),'--manifest',str(manifest),'--runs',str(runs),'--output',str(out)],capture_output=True,text=True)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertFalse(json.loads(out.read_text())['quality_approved'])

    def test_bounded_context_change_invalidates_frozen_input_and_review(self):
        case=self.manifest['cases'][0]
        case.update(input_kind='bounded_source_request',request_fingerprint=digest('original-window'),
                    scope_contract_sha256=digest('original-purpose'))
        self.run.update(request_fingerprint=case['request_fingerprint'],scope_contract_sha256=case['scope_contract_sha256'])
        self.run['review']['binding_sha256']=review_binding(self.run,case)
        self.assertTrue(self.result()['ready_for_quality_decision'])
        self.run['request_fingerprint']=digest('different-window')
        self.assertIn('synthetic:frozen_request_mismatch',self.result()['blocking_reasons'])
        case['request_fingerprint']=self.run['request_fingerprint']
        self.assertIn('synthetic:stale_or_missing_review',self.result()['blocking_reasons'])
        self.run['review']['binding_sha256']=review_binding(self.run,case)
        self.run['scope_contract_sha256']=digest('different-purpose')
        self.assertIn('synthetic:frozen_request_mismatch',self.result()['blocking_reasons'])

    def test_v22_missing_request_binding_blocks_even_with_semantic_pass(self):
        self.run['method_version']=self.manifest['cases'][0]['method_version']='2026-10-04.22'
        self.run['review']['binding_sha256']=review_binding(self.run,self.manifest['cases'][0])
        self.assertIn('synthetic:unfrozen_bounded_input',self.result()['blocking_reasons'])

    def test_negative_contract_rejects_nonempty_output(self):
        case=self.manifest['cases'][0]
        case.update(expected_output='empty',requires_nonempty_claims=False)
        self.run['review']['binding_sha256']=review_binding(self.run,case)
        self.assertIn('synthetic:nonempty_negative_output',self.result()['blocking_reasons'])
        self.run['claims']=[];self.run['review']['binding_sha256']=review_binding(self.run,case)
        self.assertTrue(self.result()['ready_for_quality_decision'])

    def test_invalid_or_conflicting_bounded_contract_is_rejected(self):
        self.manifest['cases'][0]['request_fingerprint']=True
        with self.assertRaises(ValueError):self.result()
        self.manifest['cases'][0].pop('request_fingerprint')
        self.manifest['cases'][0]['expected_output']='empty'
        with self.assertRaises(ValueError):self.result()

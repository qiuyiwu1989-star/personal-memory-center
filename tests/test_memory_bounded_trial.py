"""Synthetic bounded model trials; no real API, sources or production budgets."""
import tempfile
import unittest
from unittest.mock import patch,PropertyMock
from pipeline.memory_center.core import Store,Invalid
from pipeline.memory_center.model import Model,ModelOutputError
from pipeline.memory_center.long_source_plan import plan_long_source
from pipeline.memory_center.bounded_source_request import plan_bounded_source_requests
from pipeline.memory_center import budget

class BoundedTrialTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.p=dict(id='synthetic-owner',owner='synthetic',trusted_user=True,scopes=['personal'],actions=['read','write','source_read'])
        self.env=dict(source_key='synthetic:trial',scope='personal',source_type='conversation',source_metadata={},
                      messages=[dict(id='original',role='user',text='我的长期偏好是先看合成证据。')])
        self.plan=plan_long_source(self.env['source_key'],self.env['messages'],scope='personal',source_type='conversation',source_metadata={})
        packet=plan_bounded_source_requests(self.env,self.plan,version='2026-10-04.22')
        self.rid=packet['requests'][0]['request_id'];self.model=Model(self.store,method_version='2026-10-04.22')
        self.configured=patch.object(Model,'configured',new_callable=PropertyMock,return_value=True);self.configured.start()
    def tearDown(self):self.configured.stop();self.tmp.cleanup()
    def run_trial(self,key='synthetic-key'):
        return self.model.extract_bounded_source(self.env,self.plan,self.rid,self.p,key)
    def enable(self):budget.configure(self.store,self.p,'personal',{'token_limit':100000})
    def test_no_budget_no_call(self):
        with patch.object(self.model,'_call') as call:
            with self.assertRaisesRegex(Invalid,'预算不足'):self.run_trial()
        call.assert_not_called()
    def test_settlement_and_stable_key_prevent_duplicate_calls(self):
        self.enable()
        with patch.object(self.model,'_call',return_value=({'claims':[]},{'total_tokens':12})) as call:
            plan,usage=self.run_trial()
            self.assertEqual(plan['claims'],[]);self.assertFalse(usage['quality_approved'])
            self.assertEqual(budget.status(self.store,self.p,'personal')['tokens_spent'],12)
            self.assertEqual(call.call_args.args[1]['messages'][0]['id'],'original')
            with self.assertRaisesRegex(Invalid,'已使用'):self.run_trial()
            self.assertEqual(call.call_count,1)
    def test_unknown_failure_retains_reservation_and_cannot_retry_same_key(self):
        self.enable()
        with patch.object(self.model,'_call',side_effect=RuntimeError('synthetic-private-provider-body')):
            with self.assertRaises(ModelOutputError) as caught:self.run_trial()
        self.assertNotIn('synthetic-private-provider-body',str(caught.exception))
        with self.store.db() as db:r=dict(db.execute('SELECT * FROM model_attempts').fetchone())
        self.assertEqual(r['state'],'usage_unknown');self.assertGreater(r['charged'],0)
        self.assertEqual(caught.exception.usage['attempt_id'],r['id'])
        with self.assertRaisesRegex(Invalid,'已使用'):self.run_trial()
    def test_bad_output_still_settles_measured_cost(self):
        self.enable()
        with patch.object(self.model,'_call',return_value=({'claims':[{'evidence_id':'invented'}]},{'total_tokens':20})):
            with self.assertRaises(ModelOutputError):self.run_trial()
        self.assertEqual(budget.status(self.store,self.p,'personal')['tokens_spent'],20)
    def test_original_tamper_rejected_before_reservation(self):
        self.enable();self.env['messages'][0]['text']='Synthetic changed source'
        with patch.object(self.model,'_call') as call:
            with self.assertRaises(Invalid):self.run_trial()
        call.assert_not_called()
        self.assertEqual(budget.status(self.store,self.p,'personal')['tokens_spent'],0)
    def test_third_party_or_default_method_not_allowed(self):
        self.enable();self.p['trusted_user']=False
        with self.assertRaises(PermissionError):self.run_trial()
        with self.assertRaises(Invalid):Model(self.store).extract_bounded_source(self.env,self.plan,self.rid,self.p,'key')

    def test_positive_output_preserves_original_evidence_and_stays_unconfirmed(self):
        self.enable()
        packet=plan_bounded_source_requests(self.env,self.plan,version='2026-10-04.22')['requests'][0]
        eid=next(iter(packet['spans']))
        output={'claims':[{'topic':'preferences','kind':'preference','subject':'user',
                  'statement':'用户长期偏好先看合成证据；原始时间未知，当前有效性待核实。','evidence_id':eid}]}
        with patch.object(self.model,'_call',return_value=(output,{'total_tokens':25})):
            result,usage=self.run_trial()
        self.assertEqual(result['claims'][0]['message_id'],'original')
        self.assertEqual(result['claims'][0]['quote'],self.env['messages'][0]['text'])
        self.assertEqual(result['claims'][0]['status'],'source_reported')
        self.assertFalse(usage['quality_approved'])
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) n FROM records').fetchone()['n'],0)
    def test_unconfigured_model_does_not_reserve(self):
        self.enable()
        with patch.object(Model,'configured',new_callable=PropertyMock,return_value=False):
            with self.assertRaisesRegex(Invalid,'模型未配置'):self.run_trial()
        self.assertEqual(budget.status(self.store,self.p,'personal')['tokens_spent'],0)

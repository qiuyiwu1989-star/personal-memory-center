"""Synthetic runtime tests: no real API keys or model calls."""
import os
import tempfile
import unittest
from unittest.mock import patch
from pipeline.memory_center.core import Store, Invalid
from pipeline.memory_center.configuration import draft, activate
from pipeline.memory_center.model import Model, ModelOutputError, PROMPT_VERSION

class ScopedRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.owner={'id':'owner','owner':'synthetic-runtime','scopes':['personal','project:demo'],'actions':['read','write'],'trusted_user':True}
        self.environment=patch.dict(os.environ,{'QIU_MEMORY_LLM_BASE':'https://model.example.invalid/v1'});self.environment.start()
        self.source={'owner':self.owner['owner'],'scope':'personal'}
    def tearDown(self):self.environment.stop();self.tmp.cleanup()
    def activate(self,kind,payload):
        vid=draft(self.store,self.owner,'personal',{'kind':kind,'label':'synthetic runtime','payload':payload})['id']
        activate(self.store,self.owner,'personal',vid,{'revision':0,'note':'Synthetic runtime validation only.'});return vid
    def test_translation_uses_scoped_model_not_extraction_instructions(self):
        vid=self.activate('model',{'base_url':os.environ['QIU_MEMORY_LLM_BASE'],'model':'synthetic-endpoint','max_tokens':1000})
        self.activate('prompt',{'instructions':'Synthetic extraction instruction.'})
        model=Model(self.store)
        with patch.object(model,'_call',return_value=({'text':'合成译文'},{'total_tokens':12})) as call:
            text,usage=model.translate_source(self.source,'Synthetic original.')
        self.assertEqual(text,'合成译文');self.assertEqual(call.call_args.kwargs['connection']['model'],'synthetic-endpoint')
        self.assertEqual(call.call_args.kwargs['max_tokens'],1000)
        self.assertNotIn('Synthetic extraction instruction.',call.call_args.args[0])
        self.assertEqual(usage['configuration_versions'],{'model_version':vid})
    def test_translation_other_scope_uses_baseline_without_version_leak(self):
        self.activate('model',{'base_url':os.environ['QIU_MEMORY_LLM_BASE'],'model':'synthetic-endpoint','max_tokens':1000})
        with patch.object(Model,'_call',return_value=({'text':'合成译文'},{'total_tokens':12})) as call:
            _,usage=Model(self.store).translate_source(dict(self.source,scope='project:demo'),'Synthetic.')
        self.assertEqual(call.call_args.kwargs,{})
        self.assertNotIn('configuration_versions',usage)
    def test_unknown_provider_failure_preserves_versions_without_private_error(self):
        vid=self.activate('model',{'base_url':os.environ['QIU_MEMORY_LLM_BASE'],'model':'synthetic-endpoint','max_tokens':1000})
        with patch.object(Model,'_call',side_effect=RuntimeError('synthetic-provider-private-body')):
            with self.assertRaises(ModelOutputError) as caught:Model(self.store).translate_source(self.source,'Synthetic.')
        self.assertNotIn('synthetic-provider-private-body',str(caught.exception))
        self.assertEqual(caught.exception.usage['configuration_versions'],{'model_version':vid})
        self.assertNotIn('total_tokens',caught.exception.usage)
        self.assertFalse(caught.exception.usage['attempt_measured'])
    def test_contract_failure_retains_measured_receipt(self):
        vid=self.activate('model',{'base_url':os.environ['QIU_MEMORY_LLM_BASE'],'model':'synthetic-endpoint','max_tokens':1000})
        with patch.object(Model,'_call',side_effect=ModelOutputError('synthetic truncation',{'total_tokens':20},'output_truncated')):
            with self.assertRaises(ModelOutputError) as caught:Model(self.store).translate_source(self.source,'Synthetic.')
        self.assertEqual(caught.exception.usage['total_tokens'],20)
        self.assertEqual(caught.exception.usage['configuration_versions']['model_version'],vid)
    def test_explicit_experiment_does_not_change_default(self):
        self.assertEqual(Model().method_version,PROMPT_VERSION)
        self.assertEqual(Model(method_version='2026-10-04.22').method_version,'2026-10-04.22')
        with self.assertRaises(Invalid):Model(method_version='unguarded')

    def test_explicit_v22_extract_has_matching_route_receipt(self):
        from pipeline.memory_center.modality import SCOPED_V22_GUARD_VERSION
        source={'source_type':'conversation','payload':__import__('json').dumps([{'id':'synthetic','role':'user','text':'我希望项目 Atlas 保留原文。如果评测通过，我计划发布项目 Orion。'}],ensure_ascii=False)}
        def reply(system, payload, version, **kwargs):
            self.assertEqual(version,'2026-10-04.22')
            self.assertEqual(len(payload['messages'][0]['evidence_spans']),2)
            return {'claims':[]},{'total_tokens':12,'method_version':version}
        with patch.object(Model,'_call',side_effect=reply):
            plan,usage=Model(method_version='2026-10-04.22').extract_source(source)
        self.assertEqual(plan['claims'],[])
        self.assertEqual(usage['condition_scope_guard_version'],SCOPED_V22_GUARD_VERSION)

import unittest
from pipeline.memory_center.evaluation import evidence_check, aggregate

class EvaluationTest(unittest.TestCase):
    def test_secondary_match_is_not_primary_or_validity(self):
        result=evidence_check({'quote':'Synthetic advice','messages':[{'text':'Synthetic advice'}]})
        self.assertEqual(result['evidence'],'secondary_quote_present')
        self.assertFalse(result['primary_available']);self.assertEqual(result['current_validity'],'unknown')

    def test_excluded_block_is_not_visible_source(self):
        message={'sender':'assistant','text':'Synthetic internal','content':[
            {'type':'thinking','thinking':'Synthetic internal'},{'type':'text','text':'Visible reply'}]}
        result=evidence_check({'quote':'Synthetic internal'},message)
        self.assertEqual(result['evidence'],'excluded_block_quote')
        self.assertEqual(result['matching_block_types'],['thinking'])
        self.assertEqual(evidence_check({'quote':'Visible reply'},message)['evidence'],'visible_quote_present')

    def test_statistics_never_certify_quality(self):
        result=aggregate([{'evidence':{'evidence':'visible_quote_present'},'disposition':'candidate',
                           'semantic_support':'supported'}])
        self.assertFalse(result['quality_gate_passed']);self.assertEqual(result['owner_confirmed'],0)


class ExtractionGuardTest(unittest.TestCase):
    def test_assistant_limit_and_romanized_names(self):
        from pipeline.memory_center.core import validate_plan,encoded,Invalid
        source={'source_type':'conversation','trusted_user':False,'payload':encoded([{'id':'1','role':'assistant','text':'Synthetic assistant proposal'}])}
        item={'topic':'projects','kind':'suggestion','subject':'assistant','statement':'合成：助手建议','message_id':'1','quote':'Synthetic assistant proposal'}
        with self.assertRaisesRegex(Invalid,'两条'):validate_plan({'claims':[item]*3},source)
        source={'source_type':'imported_summary','trusted_user':False,'payload':encoded([{'id':'1','role':'external','text':'Lin Wei is a synthetic colleague.'}])}
        item={'topic':'people','kind':'relationship','subject':'Lin Wei','statement':'合成：林伟（Lin Wei）是同事','message_id':'1','quote':'Lin Wei is a synthetic colleague.'}
        with self.assertRaisesRegex(Invalid,'猜测中文名'):validate_plan({'claims':[item]},source)
        item['statement']='摘要记载：Lin Wei 是同事，当前有效性未知。'
        self.assertEqual(validate_plan({'claims':[item]},source)[0]['status'],'imported_summary')

    def test_model_receives_explicit_source_type(self):
        from pipeline.memory_center.model import Model,PROMPT_VERSION
        from pipeline.memory_center.core import encoded
        class Capture(Model):
            def _call(self,system,payload,version,max_tokens=4096):return {'claims':[]},{'payload':payload,'version':version}
        result,version=Capture().extract_source({'source_type':'imported_summary','payload':encoded([{'id':'1','role':'external','text':'Synthetic recommendation'}])})
        self.assertEqual(version['payload']['source_type'],'imported_summary');self.assertEqual(version['version'],PROMPT_VERSION)

    def test_bounded_request_uses_same_shared_ledger(self):
        import tempfile
        from pipeline.memory_center.core import Store,encoded
        from pipeline.memory_center.budget import configure,reserve_request,settle,status
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            owner={'id':'synthetic-owner','owner':'synthetic','scopes':['personal'],'actions':['read','write'],'trusted_user':True}
            configure(store,owner,'personal',{'token_limit':5000})
            source={'owner':'synthetic','scope':'personal','payload':encoded({'messages':[]})}
            with store.db() as db:
                attempt=reserve_request(db,source,'synthetic-case','Synthetic system prompt',1024)
                self.assertIsNotNone(attempt);settle(db,attempt,{'total_tokens':20})
            self.assertEqual(status(store,owner,'personal')['tokens_spent'],20)

class SuiteGateTest(unittest.TestCase):
    def test_format_pass_is_not_quality_pass(self):
        from pipeline.memory_center.evaluation import suite_gate
        run={'sample_index':1,'version':'v','max_output_tokens':1024,'validation':'passed'}
        result=suite_gate([1,2],[run],'v',1024)
        self.assertEqual(result['missing_cases'],[2])
        self.assertEqual(result['review_pending_cases'],[1])
        self.assertFalse(result['ready_for_owner_quality_decision'])
        self.assertFalse(result['quality_approved'])

    def test_mixed_methods_duplicate_runs_and_failed_reviews_block(self):
        from pipeline.memory_center.evaluation import suite_gate
        runs=[{'sample_index':1,'version':'old','max_output_tokens':1024,'validation':'passed'},
              {'sample_index':2},{'sample_index':2}]
        result=suite_gate([1,2],runs,'v',1024)
        self.assertEqual(result['incomparable_cases'],[1]);self.assertEqual(result['failed_cases'],[2])

    def test_complete_review_only_makes_owner_decision_ready(self):
        from pipeline.memory_center.evaluation import suite_gate
        run={'sample_index':1,'version':'v','max_output_tokens':1024,'validation':'passed',
             'review':dict.fromkeys(['semantic_support','speaker_attribution','time_handling','scope_handling','durable_value'],'pass')}
        result=suite_gate([1],[run],'v',1024)
        self.assertTrue(result['ready_for_owner_quality_decision'])
        self.assertFalse(result['quality_approved']);self.assertFalse(result['production_dispatch_enabled'])
        run['review']['time_handling']='fail'
        self.assertEqual(suite_gate([1],[run],'v',1024)['failed_cases'],[1])

class TemporalScopeGuardTest(unittest.TestCase):
    def test_source_time_is_not_event_time_and_summary_is_not_anchor(self):
        from pipeline.memory_center.claim_context import evidence_context
        message={'created_at':'2025-09-27T06:46:20Z','source_title':'Synthetic writing discussion'}
        direct=evidence_context(message,'conversation')
        self.assertEqual(direct['relative_time_anchor'],'2025-09-27')
        self.assertIsNone(direct['event_time']);self.assertIsNone(direct['project_identity'])
        summary=evidence_context(message,'imported_summary')
        self.assertEqual(summary['date_role'],'summary_update');self.assertIsNone(summary['relative_time_anchor'])
        self.assertIsNone(evidence_context({'created_at':'2025-99-42'},'conversation')['source_date'])

    def test_new_method_requires_date_scope_and_drops_immediate_commands(self):
        from pipeline.memory_center.core import validate_plan,encoded,Invalid
        message={'id':'1','role':'user','text':'开始第六讲，不要虚构故事。','created_at':'2025-10-06T00:00:00Z','source_title':'合成课程讨论'}
        source={'source_type':'conversation','trusted_user':False,'payload':encoded([message]),'processing_method_version':'2026-10-01.6'}
        claim={'topic':'projects','kind':'decision','subject':'user','message_id':'1','quote':'不要虚构故事。','statement':'用户要求不要虚构故事。'}
        with self.assertRaisesRegex(Invalid,'来源日期'):validate_plan({'claims':[claim]},source)
        claim['statement']='2025-10-06，用户要求不要虚构故事。'
        with self.assertRaisesRegex(Invalid,'对话标题'):validate_plan({'claims':[claim]},source)
        claim['statement']='2025-10-06，在合成课程讨论中，用户要求不要虚构故事。'
        result=validate_plan({'claims':[claim]},source)[0]
        self.assertEqual(result['evidence_context']['conversation_title'],'合成课程讨论')
        claim['statement']+='开始第六讲。'
        with self.assertRaisesRegex(Invalid,'即时'):validate_plan({'claims':[claim]},source)
        source.pop('processing_method_version')
        self.assertEqual(len(validate_plan({'claims':[claim]},source)),1)

    def test_historical_start_report_is_not_an_imperative(self):
        from pipeline.memory_center.claim_context import contains_immediate_command
        self.assertFalse(contains_immediate_command('用户在去年开始了第六讲。'))
        self.assertTrue(contains_immediate_command('用户要求继续写下一章。'))

class DateRenderingTest(unittest.TestCase):
    def test_same_chinese_calendar_date_is_not_rejected_for_format(self):
        from pipeline.memory_center.claim_context import statement_has_date,contains_immediate_command
        self.assertTrue(statement_has_date('2025年9月27日，用户要求真实案例。','2025-09-27'))
        self.assertFalse(statement_has_date('2025年9月28日','2025-09-27'))
        self.assertTrue(contains_immediate_command('用户要求写一篇新闻稿。'))
        self.assertFalse(contains_immediate_command('项目长期约束：不要杜撰经历。'))

"""Entirely synthetic three-route evidence and freeze tests."""
import copy
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('answer_benchmark',Path(__file__).resolve().parents[1]/'scripts/memory_answer_benchmark.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

def contract():
    materials=[];tasks=[];raw=[];claims=[]
    for i in range(10):
        aid=f'synthetic-archive-{i}';cid=f'synthetic-candidate-{i}';conv=f'synthetic-conversation-{i}';split='development'if i<4 else'unseen'
        text=f'合成项目{i}曾选择甲方案。';raw.append(aid);claims.append(cid)
        materials.append({'conversation_id':conv,'archive_id':aid,'source_type':'conversation','messages':[{'id':'synthetic-user','role':'user','text':text},{'id':'synthetic-assistant','role':'assistant','text':f'合成项目{i}助手草稿建议乙方案。'}],'candidates':[{'id':cid,'topic':'projects','kind':'decision','subject':'user','statement':text,'message_id':'synthetic-user','quote':text,'status':'source_reported'}]})
        for n,(query,targets)in enumerate([(f'合成项目{i}选择甲方案',{'archive':[aid],'candidate':[cid],'combined':[aid,cid]}),(f'合成项目{i}助手草稿',{'archive':[aid],'candidate':[],'combined':[aid]}),(f'合成项目{i}现在仍然有效吗',{'archive':[],'candidate':[],'combined':[]})]):
            tasks.append({'task_id':f'synthetic-task-{i}-{n}','conversation_id':conv,'split':split,'query':query,'targets':targets,'expected_abstention':n==2,'answer_rubric':'Synthetic only; preserve attribution/time and do not claim current validity.'})
    return {'synthetic':True,'annotation_status':'synthetic_fixture','corpus':{'archive':raw,'candidate':claims,'combined':raw+claims},'materials':materials,'tasks':tasks}

class AnswerBenchmarkTests(unittest.TestCase):
    def test_30_tasks_grouped_and_actual_rehearsal_does_not_answer(self):
        c=contract();coverage=b.validate_materials(c)
        self.assertEqual(coverage['split_counts'],{'development':12,'challenge':0,'unseen':18})
        r=b.rehearse(c,max_chars=1600)
        self.assertTrue(r['all_within_budget']);self.assertEqual(r['model_calls'],0);self.assertEqual(r['answer_judge_status'],'not_run')
        self.assertEqual(r['contract_sha256'],b.digest(c))
        for route in r['baselines'].values():
            self.assertEqual(len(route),30)
            self.assertTrue(all(x['answer']is None and x['answer_judgment']is None for x in route))
        self.assertTrue(all(row['evidence']['trusted_context']['total']==0 for row in r['baselines']['combined']))
    def test_split_leakage_and_orphan_claim_rejected(self):
        c=contract();c['tasks'][0]['split']='challenge'
        with self.assertRaises(ValueError):b.validate_materials(c)
        c=contract();c['materials'][0]['candidates'][0]['message_id']='unknown'
        with self.assertRaises(ValueError):b.validate_materials(c)
    def test_known_challenge_does_not_become_unseen(self):
        c=contract()
        for task in c['tasks']:task['split']='challenge'
        self.assertEqual(b.validate_materials(c)['split_counts']['unseen'],0)
    def test_output_never_enters_public_repository(self):
        with self.assertRaises(ValueError):b.write_private(Path(__file__).parent/'private-benchmark.json',{})

if __name__=='__main__':unittest.main()

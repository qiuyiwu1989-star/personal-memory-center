#!/usr/bin/env python3
"""Validate/freeze acceptance tasks and score independent retrieval/answer reports.
No models, retrieval calls or production writes. Real contracts/reports stay private.
"""
import argparse
import hashlib
import json
from pathlib import Path

BASELINES = ('archive', 'candidate', 'combined')

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def validate(contract):
    if contract.get('annotation_status') not in ('synthetic_fixture','agent_review_provisional','human_reviewed'):
        raise ValueError('Explicit annotation provenance required')
    tasks=contract.get('tasks',[])
    if len(tasks)<30 or len({t['task_id'] for t in tasks})!=len(tasks):
        raise ValueError('At least 30 unique tasks required')
    corpus=contract.get('corpus',{})
    if set(corpus)!=set(BASELINES):raise ValueError('Three baseline corpora required')
    if any(len(ids)!=len(set(ids)) for ids in corpus.values()):raise ValueError('Duplicate corpus identity')
    if set(corpus['combined']) != set(corpus['archive'])|set(corpus['candidate']):
        raise ValueError('Combined corpus must union archive and candidate identities')
    seen={}
    for t in tasks:
        if t['split'] not in ('development','test') or not t.get('conversation_id') or not t.get('query'):
            raise ValueError('Conversation/split/query required')
        old=seen.setdefault(t['conversation_id'],t['split'])
        if old!=t['split']:raise ValueError('Conversation leakage between development/test')
        if set(t.get('targets',{}))!=set(BASELINES):raise ValueError('Complete baseline targets required')
        for b,targets in t['targets'].items():
            if len(targets)!=len(set(targets)) or not set(targets)<=set(corpus[b]):raise ValueError('Invalid target identities')
        if type(t.get('expected_abstention')) is not bool:raise ValueError('Explicit answer abstention required')
        if not t.get('answer_rubric'):raise ValueError('Independent answer rubric required')
    if set(seen.values())!={'development','test'}:raise ValueError('Both conversation splits required')
    return {'tasks':len(tasks),'conversations':len(seen),'development_tasks':sum(t['split']=='development' for t in tasks),'test_tasks':sum(t['split']=='test' for t in tasks)}

def score(contract,report,k=5):
    validate(contract)
    if type(k)is not int or not 1<=k<=100:raise ValueError('Invalid k')
    if report.get('contract_sha256')!=digest(contract):raise ValueError('Frozen contract receipt mismatch')
    if report.get('answer_judge_status') not in ('not_run','agent_review_provisional','human_reviewed','synthetic_fixture'):
        raise ValueError('Explicit answer judge status required')
    if set(report.get('baselines',{}))!=set(BASELINES):raise ValueError('All three baseline reports required')
    output={}
    for baseline,rows in report['baselines'].items():
        indexed={r['task_id']:r for r in rows}
        if len(indexed)!=len(rows) or set(indexed)!={t['task_id'] for t in contract['tasks']}:raise ValueError('Task coverage mismatch')
        metrics=[]
        for task in contract['tasks']:
            row=indexed[task['task_id']]
            if row.get('query')!=task['query']:raise ValueError('Frozen query changed')
            ids=row['retrieved_ids']
            if len(ids)!=len(set(ids)) or not set(ids)<=set(contract['corpus'][baseline]):raise ValueError('Unknown/duplicate retrieved identity')
            selected=ids[:k];targets=set(task['targets'][baseline]);hits=targets&set(selected)
            judged=row.get('answer_judgment')
            if report['answer_judge_status']=='not_run' and judged is not None:raise ValueError('Answers not run cannot be judged')
            if judged is not None:
                if not row.get('answer') or not isinstance(judged,dict):raise ValueError('Answer and judgment required')
                fields=('correct','attribution_correct','time_correct','citations_supported','abstained')
                if any(type(judged.get(f))is not bool for f in fields):raise ValueError('Complete independent answer judgments required')
                if not judged.get('rationale'):raise ValueError('Answer judgment rationale required')
            metrics.append({'task_id':task['task_id'],'split':task['split'],
                'precision_at_k':len(hits)/k if targets else None,
                'recall_at_k':len(hits)/len(targets) if targets else None,
                'mrr_at_k':next((1/(n+1) for n,rid in enumerate(selected) if rid in targets),0) if targets else None,
                'negative_abstention':not selected if not targets else None,
                'false_returns':len(set(selected)-targets),
                'answer_passed':all(judged[f] for f in ('correct','attribution_correct','time_correct','citations_supported')) and judged['abstained']==task['expected_abstention'] if judged else None})
        splits={}
        for split in ('development','test'):
            group=[r for r in metrics if r['split']==split];pos=[r for r in group if r['recall_at_k']is not None];neg=[r for r in group if r['negative_abstention']is not None];judged=[r for r in group if r['answer_passed']is not None]
            splits[split]={'tasks':len(group),**{field:sum(r[field] for r in pos)/len(pos) if pos else None for field in ('precision_at_k','recall_at_k','mrr_at_k')},'negative_tasks':len(neg),'negative_correct_abstentions':sum(r['negative_abstention'] for r in neg),'false_returns':sum(r['false_returns'] for r in group),'answers_judged':len(judged),'answers_passed':sum(r['answer_passed'] for r in judged) if judged else None}
        output[baseline]={'tasks':metrics,'summary':splits}
    return {'contract_sha256':digest(contract),'annotation_status':contract['annotation_status'],'answer_judge_status':report['answer_judge_status'],'baselines':output,'quality_approved':False,'model_calls':0,'limitation':'Scorer does not judge answer semantics; answer labels require separate review. Synthetic tests do not certify real data.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract',required=True,type=Path);parser.add_argument('--report',type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();contract=json.loads(args.contract.read_text());summary=validate(contract)
    result=score(contract,json.loads(args.report.read_text())) if args.report else {'contract_sha256':digest(contract),'status':'frozen_not_run','coverage':summary,'quality_approved':False}
    target=args.output.resolve();repo=Path(__file__).resolve().parents[1]
    if target==repo or repo in target.parents:parser.error('Reports must remain outside public repository')
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x')as f:target.chmod(0o600);json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'tasks':summary['tasks'],'status':'scored' if args.report else 'frozen_not_run','quality_approved':False}))

if __name__=='__main__':main()

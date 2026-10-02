#!/usr/bin/env python3
"""Offline three-route evidence rehearsal. No answer model, provider or live writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_memory_acceptance import digest
from pipeline.memory_center.core import Store,encoded
from pipeline.memory_center import source_discovery,reading
from pipeline.memory_center.evidence_bundle import bundle


def validate_materials(contract):
    tasks=contract.get('tasks',[])
    if len(tasks)<30 or len({t['task_id'] for t in tasks})!=len(tasks):raise ValueError('At least 30 unique tasks required')
    if contract.get('annotation_status')not in ('synthetic_fixture','agent_review_provisional','human_reviewed'):raise ValueError('Explicit label provenance required')
    corpus=contract.get('corpus',{})
    if set(corpus)!={'archive','candidate','combined'}:raise ValueError('Three route corpora required')
    if set(corpus['combined'])!=set(corpus['archive'])|set(corpus['candidate']):raise ValueError('Combined corpus mismatch')
    groups={}
    for task in tasks:
        if task['split']not in ('development','challenge','unseen'):raise ValueError('Unknown split')
        old=groups.setdefault(task['conversation_id'],task['split'])
        if old!=task['split']:raise ValueError('Conversation split leakage')
        if not task.get('query')or not task.get('answer_rubric'):raise ValueError('Frozen query/rubric required')
        if set(task['targets'])!=set(corpus):raise ValueError('Incomplete targets')
        for route,ids in task['targets'].items():
            if len(ids)!=len(set(ids))or not set(ids)<=set(corpus[route]):raise ValueError('Invalid targets')
    coverage={'tasks':len(tasks),'conversations':len(groups),'split_counts':{g:sum(t['split']==g for t in tasks)for g in ('development','challenge','unseen')}}
    materials=contract.get('materials',[])
    if not materials:raise ValueError('Frozen materials required')
    archive=[];candidates=[];seen=set()
    for item in materials:
        if item['conversation_id'] in seen:raise ValueError('One material per conversation required')
        seen.add(item['conversation_id']);archive.append(item['archive_id'])
        if not item.get('messages'):raise ValueError('Original messages required')
        if len({m['id'] for m in item['messages']})!=len(item['messages']):raise ValueError('Duplicate source message IDs')
        for row in item['candidates']:
            if row['message_id']not in {m['id'] for m in item['messages']}:raise ValueError('Candidate source message missing')
            candidates.append(row['id'])
    if set(archive)!=set(contract['corpus']['archive']) or set(candidates)!=set(contract['corpus']['candidate']):raise ValueError('Material corpus mismatch')
    if any(t['conversation_id'] not in seen for t in contract['tasks']):raise ValueError('Unknown task conversation')
    return coverage


def seed(store,contract):
    p={'id':'isolated-answer-rehearsal','owner':'rehearsal','scopes':['rehearsal'],'actions':['read','source_read','write'],'trusted_user':False}
    mappings={}
    with store.db()as db:
        for number,item in enumerate(contract['materials']):
            sid='rehearsal-source-'+str(number);mappings[sid]=item['archive_id'];messages=item['messages']
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,'rehearsal','rehearsal',sid,hashlib.sha256(encoded(messages).encode()).hexdigest(),item['source_type'],p['id'],0,encoded(messages),float(number)))
            for n,row in enumerate(item['candidates']):
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(row['id'],'rehearsal','rehearsal',row['topic'],row['kind'],row['subject'],row['statement'],row['status'],sid,row['message_id'],row['quote'],'active',1,None,float(n)))
    source_discovery.rebuild(store,p,'rehearsal')
    return p,mappings


def rehearse(contract,max_chars=6000,retrieval_mode='lexical-v1'):
    validate_materials(contract)
    if type(max_chars)is not int or not 1500<=max_chars<=16000:raise ValueError('Shared serialized budget must be 1500..16000')
    routes={key:[] for key in ('archive','candidate','combined')}
    with tempfile.TemporaryDirectory(prefix='memory-answer-rehearsal-')as directory:
        store=Store(directory);principal,mapping=seed(store,contract)
        for task in contract['tasks']:
            query=task['query']
            evidence={
                'archive':source_discovery.search(store,principal,'rehearsal',query,max_chars=max_chars),
                'candidate':reading.search_page(store.snapshot(principal,'rehearsal',query,limit=1000000,retrieval_mode=retrieval_mode),max_chars=max_chars),
                'combined':bundle(store,principal,'rehearsal',query,max_chars=max_chars,retrieval_mode=retrieval_mode)}
            for route,data in evidence.items():
                original=data.get('original_evidence',{}) if route=='combined' else data if route=='archive' else {}
                reports=data.get('source_reports',{}) if route=='combined' else data if route=='candidate' else {}
                # Keep evidence source identities separate but collapse same-source
                # chunk duplicates; multiple chunks do not add corroboration.
                raw_ids=[mapping[r['source_id']] for r in original.get('results',[])]+[r['id'] for r in reports.get('records',[])]
                ids=list(dict.fromkeys(raw_ids))
                routes[route].append({'task_id':task['task_id'],'query':query,'retrieved_ids':ids,'evidence':data,'serialized_chars':len(encoded(data)),'answer':None,'answer_judgment':None})
    return {'contract_sha256':digest(contract),'answer_judge_status':'not_run','baselines':routes,'retrieval_mode':retrieval_mode,'route_note':'Archive returns indexed visible snippets/locators; full-source expansion is NOT run. Combined uses actual evidence_bundle; ranking across groups is source-then-candidate grouping, not fused ranking.','max_chars':max_chars,'answers_generated':0,'model_calls':0,'quality_approved':False,'all_within_budget':all(r['serialized_chars']<=max_chars for rows in routes.values()for r in rows)}


def write_private(path,value):
    target=path.resolve();repo=Path(__file__).resolve().parents[1]
    if target==repo or repo in target.parents:raise ValueError('Private outputs must be outside public repository')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with target.open('x')as f:target.chmod(0o600);json.dump(value,f,ensure_ascii=False,indent=2)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--rehearse',action='store_true');parser.add_argument('--max-chars',type=int,default=6000)
    parser.add_argument('--retrieval-mode',choices=['lexical-v1','lexical-v2','lexical-v3'],default='lexical-v1')
    args=parser.parse_args();contract=json.loads(args.contract.read_text());coverage=validate_materials(contract)
    if args.rehearse:
        report=rehearse(contract,args.max_chars,args.retrieval_mode)
    else:report={'contract_sha256':digest(contract),'coverage':coverage,'status':'frozen_not_run','answers_generated':0,'quality_approved':False,'model_calls':0}
    write_private(args.output,report)
    print(json.dumps({'coverage':coverage,'status':'retrieval_rehearsed_answers_not_run' if args.rehearse else 'frozen_not_run','quality_approved':False,'model_calls':0}))

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Run frozen synthetic guard/review contracts. No model, database or network.
This checks deterministic behavior, never extraction semantic accuracy.
"""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:sys.path.insert(0,str(REPO))
from pipeline.memory_center.extraction_quality import review
from pipeline.memory_center.modality import modality_problem

FIXTURE=REPO/'tests/fixtures/memory_quality_contract_v1.json'
CATEGORIES={'owner_decision','third_party','conditional','correction','need_vs_plan'}

def evaluate(contract):
    if contract.get('synthetic') is not True or contract.get('annotation_status')!='synthetic_fixture' or contract.get('real_model_evaluation')!='not_run':
        raise ValueError('Only explicit synthetic, model-not-run contracts supported')
    cases=contract.get('cases',[])
    if not cases or len({c['case_id'] for c in cases})!=len(cases):raise ValueError('Unique nonempty cases required')
    if {c['category'] for c in cases}!=CATEGORIES:raise ValueError('Five coverage categories required')
    if contract.get('historical_case5')!='not_retested_not_passed':raise ValueError('Historical trial remains unresolved')
    frozen=copy.deepcopy(contract);rows=[]
    for case in cases:
        claim=case['probe_claim'];expected=case['expected_deterministic']
        if not isinstance(case.get('semantic_rubric'),str) or not case['semantic_rubric'].strip():raise ValueError('Independent semantic rubric required')
        if type(expected.get('guard_reject'))is not bool:raise ValueError('Explicit guard expectation required')
        if not isinstance(claim.get('quote'),str) or claim['quote'] not in case['source_text']:raise ValueError('Exact source evidence required')
        source={'messages':[{'id':'synthetic-probe','role':'user','text':case['source_text']}]}
        result=review([dict(claim,message_id='synthetic-probe')],source)
        codes=result['items'][0]['codes']
        rejected=modality_problem(claim['quote'],claim['statement'],claim['kind']) is not None
        missing=sorted(set(expected['required_review_codes'])-set(codes))
        unexpected=sorted(set(expected['forbidden_review_codes'])&set(codes))
        passed=rejected==expected['guard_reject'] and not missing and not unexpected
        rows.append({'case_id':case['case_id'],'category':case['category'],
            'deterministic_contract_passed':passed,'guard_reject':rejected,
            'review_codes':codes,'missing_codes':missing,'forbidden_codes_found':unexpected,
            'semantic_judgment':'not_run','semantics_verified':False})
        if result['quality_approved'] or result['semantics_verified']:raise AssertionError('Hints cannot approve semantics')
    if contract!=frozen:raise AssertionError('Contract mutated')
    digest=hashlib.sha256(json.dumps(contract,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'suite_version':contract['suite_version'],'contract_sha256':digest,
        'annotation_status':'synthetic_fixture','evaluation_kind':'offline_deterministic_contract',
        'model_calls':0,'quality_approved':False,'semantic_evaluation':'not_run',
        'historical_case5':'not_retested_not_passed','total':len(rows),
        'deterministic_passed':sum(r['deterministic_contract_passed'] for r in rows),
        'items':rows,'limitations':['Development probes are not an independent semantic holdout.',
            'Guard abstention is not correctness; stale corrections may escape lexical hints.',
            'No provider generation, extraction recall, real answer or production adoption was tested.']}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=evaluate(json.loads(FIXTURE.read_text()))
    if args.output:
        target=args.output.resolve()
        if target==REPO or REPO in target.parents:parser.error('Evaluation receipts must remain outside public repository')
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x')as handle:
            target.chmod(0o600);json.dump(result,handle,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('items','limitations')},ensure_ascii=False))
    return 0 if result['deterministic_passed']==result['total'] else 1

if __name__=='__main__':raise SystemExit(main())

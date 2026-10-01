#!/usr/bin/env python3
"""Isolated, zero-provider replay of existing extraction receipts, never live adoption.

Ready runs are replay fixtures, explicitly inserted after normal preview validation;
this does NOT simulate worker/model success or certify quality. Real records remain
candidates. Owner confirmation/correction scenarios use synthetic data only.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.memory_center.core import Store, Conflict, encoded
from pipeline.memory_center.reprocessing import preview, enqueue, control
from pipeline.memory_center.documents import define_topic, build_documents
from pipeline.memory_center.governance import context

SCOPE = 'pilot:isolated'
OWNER = {'id':'pilot-owner','owner':'pilot','scopes':[SCOPE],
         'actions':['read','write'],'trusted_user':True}
WRITER = dict(OWNER,id='receipt-importer',trusted_user=False)
READER = dict(OWNER,id='pilot-reader',actions=['read'],trusted_user=False)


def replay_ready(store, principal, source_id, claims, request_key, version):
    """Bind an already saved validated output to a local, no-worker ready fixture."""
    diff = preview(store,principal,source_id,{'claims':claims},version)
    run = enqueue(store,principal,source_id,request_key)
    with store.db() as db:
        db.execute("UPDATE extraction_runs SET state='ready',preview_id=?,usage=? WHERE id=?",
                   (diff['id'],encoded({'receipt_replay':True,'new_model_calls':0}),run['id']))
    return run, diff


def mcp_checks(store, source_id, message_id):
    from starlette.testclient import TestClient
    from pipeline.memory_center.service import create_app
    class NeverModel:
        configured = False
        def extract(self, *args):raise AssertionError('No model allowed')
    grant=dict(READER,token_sha256=hashlib.sha256(b'isolated-pilot-token').hexdigest())
    app=create_app(store,lambda:[grant],NeverModel(),run_worker=False)
    with TestClient(app,base_url='http://127.0.0.1:5078') as client:
        headers={'Authorization':'Bearer isolated-pilot-token','Accept':'application/json, text/event-stream'}
        def call(name,args):
            result=client.post('/mcp/',headers=headers,json={'jsonrpc':'2.0','id':1,
                'method':'tools/call','params':{'name':name,'arguments':args}}).json()
            return result['result']
        current=call('memory_context',{'scope':SCOPE,'query':'','max_chars':1600})
        assert not current.get('isError',False)
        content=json.loads(current['content'][0]['text'])
        assert content['records']==[]
        search=call('memory_search',{'scope':SCOPE,'query':'','max_chars':16000})
        assert not search.get('isError',False)
        candidates=json.loads(search['content'][0]['text'])
        assert candidates['records'] and all(r['governance']['state']=='candidate' for r in candidates['records'])
        denied=call('memory_context',{'scope':'other','query':''})
        assert denied.get('isError')
        source_denied=call('memory_source_get',{'source_id':source_id,'message_id':message_id})
        assert source_denied.get('isError')
        write_denied=call('memory_import',{'scope':SCOPE,'source_key':'blocked',
                       'messages':[{'id':'1','role':'user','text':'Synthetic blocked text'}]})
        assert write_denied.get('isError')
        grant['actions']=['read','source_read']
        source=call('memory_source_get',{'source_id':source_id,'message_id':message_id,'max_chars':1000})
        assert not source.get('isError',False)
        assert len(encoded(json.loads(source['content'][0]['text'])))<=1000
        doc=build_documents(store,READER,SCOPE)[0]
        offset=0;parts=[];page_count=0
        while True:
            result=call('memory_document_get',{'scope':SCOPE,'topic_id':doc['slug'],
                        'offset':offset,'max_chars':4000})
            assert not result.get('isError',False)
            data=json.loads(result['content'][0]['text'])
            assert len(encoded(data))<=4000
            parts.append(data['markdown']);page_count+=1
            if data['next_offset'] is None:break
            assert data['next_offset']>offset
            offset=data['next_offset']
        assert ''.join(parts)==doc['markdown']
    return {'candidate_search_count':len(candidates['records']), 'candidate_search_total':candidates['total'],
            'document_pages':page_count,'document_lossless':True,'trusted_context_empty':True,'cross_scope_denied':True,'source_read_requires_separate_permission':True,
            'read_only_write_denied':True,'source_page_bounded':True,'context_bounded':len(encoded(content))<=1600}


def run_pilot(store, cases, runs):
    indexed={r['sample_index']:r for r in runs}
    traces=[];new_count=0;duplicate_count=0;links=0
    for case in cases:
        run=indexed[case['sample_index']]
        if run.get('validation')!='passed':
            raise ValueError('Pilot requires all existing outputs validated')
        sid=store.ingest(WRITER,{'scope':SCOPE,'source_key':'pilot:'+str(case['sample_index']),
             'messages':case['messages'],'source_type':case.get('source_type','conversation'),
             'processing_policy':'archive'})['id']
        with store.db() as db:
            original=json.loads(db.execute('SELECT payload FROM sources WHERE id=?',(sid,)).fetchone()['payload'])
        assert all(original[i][k]==message[k] for i,message in enumerate(case['messages']) for k in ('id','role','text'))
        claims=run.get('validated_claims',[])
        first=preview(store,OWNER,sid,{'claims':claims},run['version'])
        assert all(x['comparison']=='new' for x in first['changes'])
        if not claims:
            traces.append({'sample_index':case['sample_index'],'source_id':sid,'candidate_count':0,
                           'result':'archived_empty_existing_output'});continue
        fixture,diff=replay_ready(store,OWNER,sid,claims,'pilot:'+str(case['sample_index']),run['version'])
        denied=False
        try: control(store,READER,fixture['id'],'apply',list(range(len(claims))))
        except PermissionError:denied=True
        assert denied
        applied=control(store,OWNER,fixture['id'],'apply',list(range(len(claims))))
        assert applied['verified'] is False
        new_count+=len(applied['new_candidate_ids'])
        repeated=preview(store,OWNER,sid,{'claims':claims},run['version'])
        duplicate_count+=sum(x['comparison']=='duplicate' for x in repeated['changes'])
        links+=sum(len(x['associations']) for x in repeated['changes'])
        # A second receipt can be adopted without duplicating or replacing records.
        again,_=replay_ready(store,OWNER,sid,claims,'repeat:'+str(case['sample_index']),run['version'])
        repeated_apply=control(store,OWNER,again['id'],'apply',list(range(len(claims))))
        assert repeated_apply['new_candidate_ids']==[]
        blocked=False
        try:control(store,OWNER,fixture['id'],'apply',[0])
        except Conflict:blocked=True
        assert blocked
        traces.append({'sample_index':case['sample_index'],'source_id':sid,
                       'candidate_count':len(claims),'preview':diff,'repeat_preview':repeated,
                       'new_candidate_ids':applied['new_candidate_ids']})
    rows=store.snapshot(OWNER,SCOPE,limit=1000000)['records']
    assert len(rows)==new_count
    assert all(r['governance']['state']=='candidate' for r in rows)
    define_topic(store,OWNER,SCOPE,'pilot-records','隔离试运行候选',['pilot:'])
    docs=build_documents(store,OWNER,SCOPE)
    assert docs and sum(d['claims'] for d in docs if not d['is_index'])==len(rows)
    usable=context(store,READER,SCOPE,'',max_chars=1600)
    assert usable['records']==[]
    with store.db() as db:
        scheduled=db.execute("SELECT count(*) n FROM jobs WHERE state!='archived'").fetchone()['n']
        attempts=db.execute('SELECT count(*) n FROM model_attempts').fetchone()['n']
        reviews=db.execute('SELECT count(*) n FROM record_governance').fetchone()['n']
    assert scheduled==attempts==reviews==0
    mcp=mcp_checks(store,rows[0]['source_id'],rows[0]['message_id']) if rows else {}
    return {'mcp':mcp,'source_count':len(cases),'candidate_count':len(rows),'duplicate_candidates_detected':duplicate_count,
            'association_count':links,'document_count':len(docs),'document_claim_count':sum(d['claims'] for d in docs if not d['is_index']),
            'usable_context_records':0,'model_calls':0,'actual_model_tokens':0,'worker_tasks':0,
            'governance_reviews':0,'production_writes':0,'operational_pilot_passed':True,
            'quality_approved':False,'bulk_resumed':False,'traces':traces,'documents':docs,
            'limitations':['Existing receipt replay, not new model extraction.','No real person identity or current-state confirmation.',
                           'Candidate adoption is not semantic or owner quality approval.','Source materials are partial samples, not a complete archive export.']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--results',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    repo=Path(__file__).resolve().parents[1];target=args.output.resolve()
    if target==repo or repo in target.parents:p.error('Private report must remain outside public repository')
    inputs=json.loads(args.input.read_text());results=json.loads(args.results.read_text())
    with tempfile.TemporaryDirectory(prefix='memory-pilot-') as directory:
        report=run_pilot(Store(directory),inputs['cases'],results['runs'])
        # Export content is embedded; removed temporary store paths are not durable references.
        for doc in report['documents']:doc.pop('export_path',None)
    report.update(input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                  results_sha256=hashlib.sha256(args.results.read_bytes()).hexdigest())
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x') as handle:
        target.chmod(0o600);json.dump(report,handle,ensure_ascii=False,indent=2)
    print(encoded({k:v for k,v in report.items() if k not in ('traces','documents','input_sha256','results_sha256','limitations')}))

if __name__=='__main__':main()

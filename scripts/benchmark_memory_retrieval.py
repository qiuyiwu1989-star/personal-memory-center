#!/usr/bin/env python3
"""Zero-provider retrieval rehearsal; private inputs/results must remain outside repo.

Ten scenario queries are fixed before reading candidates. Semantic precision/recall
requires independent relevance labels; these diagnostics never certify quality.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.memory_center.core import Store, encoded
from pipeline.memory_center.governance import context

TASKS = (
    ('writing-boundaries', '虚构人物'),
    ('writing-method', '写作结构'),
    ('project-configuration', '项目配置'),
    ('writing-style', '写作风格'),
    ('outline-reference', '文章大纲'),
    ('course-material', '课程讲稿'),
    ('durable-preferences', '长期偏好'),
    ('assistant-proposals', '助手建议'),
    ('people-attribution', '人物关系'),
    ('transient-command', '继续写'),
)


def seed_candidates(store, cases, runs):
    """Replay only existing validated outputs, with no jobs or model calls."""
    principal = {'id':'retrieval-rehearsal', 'owner':'rehearsal', 'scopes':['rehearsal'],
                 'actions':['read','write'], 'trusted_user':True}
    indexed = {r['sample_index']:r for r in runs}
    count = 0
    for index, case in enumerate(cases):
        run = indexed[case['sample_index']]
        if run.get('validation') != 'passed':
            continue
        source_id = f'source-{index}'
        messages = case['messages']
        with store.db() as db:
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (source_id,'rehearsal','rehearsal',source_id,
                        hashlib.sha256(encoded(messages).encode()).hexdigest(),
                        case.get('source_type','conversation'),'rehearsal',0,
                        encoded(messages),float(index)))
            for number, c in enumerate(run.get('validated_claims', [])):
                db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (f'r-{index}-{number}','rehearsal','rehearsal',c['topic'],c['kind'],
                            c['subject'],c['statement'],c['status'],source_id,c['message_id'],
                            c['quote'],'active',1,None,float(count)))
                count += 1
    return principal, count


def run_benchmark(store, principal, scope, tasks=TASKS, max_chars=1600,retrieval_mode='lexical-v1'):
    results = []
    for task_id, query in tasks:
        start = time.perf_counter()
        hits = store.snapshot(principal,scope,query,limit=5,retrieval_mode=retrieval_mode)['records']
        current = context(store,principal,scope,query,max_chars=max_chars,retrieval_mode=retrieval_mode)
        elapsed = (time.perf_counter()-start)*1000
        source_count = sum(bool(r['source_id'] and r['message_id'] and r['quote']) for r in hits)
        chars = len(encoded(current))
        results.append({'task_id':task_id,'query':query,'returned_candidates':len(hits),
                        'candidate_record_ids':[r['id'] for r in hits],
                        'source_linked':source_count,
                        'exact_query_phrase_matches':sum(query in r['statement'] for r in hits),
                        'source_date_known':sum(bool(r.get('source_date')) for r in hits),
                        'assistant_candidates':sum(r['status']=='agent_suggested' for r in hits),
                        'usable_context_records':len(current['records']),
                        'context_chars':chars,'within_char_budget':chars<=max_chars,
                        'approx_tokens_utf8_bytes_div4':(len(encoded(current).encode())+3)//4,
                        'elapsed_ms':round(elapsed,2),'semantic_relevance':'not_annotated'})
    from pipeline.memory_center.retrieval_ranking import RETRIEVAL_VERSION
    return {'method':retrieval_mode+'-isolated-replay','tasks':results,'task_count':len(results),
            'model_calls':0,'actual_model_tokens':0,'char_budget':max_chars,
            'token_estimate_note':'UTF-8 bytes / 4 diagnostic only; not model tokenizer or billed usage.',
            'quality_gate_passed':False,
            'limitation':'No independent relevance labels. Zero usable results is correct for unconfirmed candidates, not successful recall.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retrieval-mode',choices=['lexical-v1','lexical-v2','lexical-v3'],default='lexical-v1')
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--results',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    output=args.output.resolve()
    if output==repo or repo in output.parents:
        parser.error('Private report must be outside public repository')
    inputs=json.loads(args.input.read_text()); results=json.loads(args.results.read_text())
    with tempfile.TemporaryDirectory(prefix='memory-retrieval-') as directory:
        store=Store(directory)
        principal,count=seed_candidates(store,inputs['cases'],results['runs'])
        report=run_benchmark(store,principal,'rehearsal',retrieval_mode=args.retrieval_mode)
        report.update(candidate_count=count,input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                      results_sha256=hashlib.sha256(args.results.read_bytes()).hexdigest())
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as handle:
        output.chmod(0o600)
        json.dump(report,handle,ensure_ascii=False,indent=2)
    # No queries, IDs, source contents, or model outputs printed.
    print(encoded({'tasks':report['task_count'],'candidates':count,'model_calls':0,
                   'tasks_with_candidates':sum(t['returned_candidates']>0 for t in report['tasks']),
                   'source_links_complete':all(t['source_linked']==t['returned_candidates'] for t in report['tasks']),
                   'context_budgets_passed':all(t['within_char_budget'] for t in report['tasks']),
                   'quality_gate_passed':False}))

if __name__=='__main__':main()

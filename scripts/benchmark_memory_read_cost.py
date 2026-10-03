#!/usr/bin/env python3
"""Synthetic SQLite read baseline; no secrets, model, network, or live data.

Run each size in a separate process to make ru_maxrss process peaks comparable.
Three observations make p95 a descriptive maximum, not a load-test estimate.
"""
import argparse, contextlib, hashlib, json, platform, resource, statistics, sys, tempfile, time, tracemalloc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline.memory_center.core import Store, encoded
from pipeline.memory_center.governance import context
from pipeline.memory_center.evidence_bundle import bundle

CODE_SHA256={name:hashlib.sha256((Path(__file__).resolve().parents[1]/'pipeline'/'memory_center'/name).read_bytes()).hexdigest() for name in ('core.py','governance.py','evidence_bundle.py','reading.py')}


def fixture(directory, size):
    store=Store(directory)
    p={'id':'synthetic-owner','owner':'synthetic-owner','scopes':['synthetic'],
       'actions':['read','source_read','write'],'trusted_user':True}
    source=store.ingest(p,{'scope':'synthetic','source_key':'synthetic-baseline',
        'processing_policy':'archive','messages':[{'id':'m','role':'user','text':'Synthetic Atlas evidence.','created_at':'2026-01-01'}]})['id']
    with store.db() as db:
        db.executemany('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ((f'r{i:08d}',p['owner'],'synthetic','projects','claim','Atlas',f'Synthetic Atlas statement {i}.',
              'user_stated',source,'m','Synthetic Atlas evidence.','active',1,None,i) for i in range(size)))
        db.executemany('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',
            ((f'r{i:08d}','synthetic-holder','synthetic-subject','2026-01-01',None,'verified','P1',1,'Synthetic fixture',0)
             for i in range(0,size,100)))
    return store,p


def measure(store,p,method,repeats):
    original=store.db
    selects=[]
    @contextlib.contextmanager
    def observed():
        with original() as db:
            db.set_trace_callback(lambda sql:selects.append(sql) if sql.lstrip().upper().startswith('SELECT') else None)
            yield db
    store.db=observed
    timings=[];rows=[];peak=0
    try:
        for i in range(repeats):
            selects.clear()
            if i==0:tracemalloc.start()
            start=time.perf_counter()
            result=method(store,p,'synthetic','Atlas')
            elapsed=time.perf_counter()-start
            if i==0:
                _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            rows.append({'seconds':round(elapsed,6),'selects':len(selects),'response_chars':len(encoded(result)),
                'response_sha256':hashlib.sha256(encoded(result).encode()).hexdigest(),
                'trusted_total':result.get('total',result.get('trusted_context',{}).get('total')),
                'trusted_returned':len(result.get('records',result.get('trusted_context',{}).get('records',[]))),
                'candidate_total':result.get('source_reports',{}).get('total'),
                'candidate_returned':len(result.get('source_reports',{}).get('records',[])),
                'original_total':result.get('original_evidence',{}).get('total'),
                'original_returned':len(result.get('original_evidence',{}).get('results',[]))})
            # First observation includes tracing overhead; untraced observations
            # alone form the latency summary. Keep both for reproducibility.
            if i:timings.append(elapsed)
    finally:store.db=original
    times=timings or [rows[0]['seconds']]
    return {'observations':rows,'p50_seconds_untraced':round(statistics.median(times),6),
        'p95_seconds_descriptive_max_untraced':round(max(times),6),'tracemalloc_peak_bytes':peak}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--size',type=int,default=10000)
    parser.add_argument('--repeats',type=int,default=3);args=parser.parse_args()
    if not 1<=args.size<=100000 or not 1<=args.repeats<=10:parser.error('bounded synthetic parameters required')
    with tempfile.TemporaryDirectory(prefix='synthetic-memory-cost-') as directory:
        store,p=fixture(directory,args.size)
        report={'synthetic':True,'backend':'SQLite','python':platform.python_version(),'platform':platform.platform(),
           'code_sha256':CODE_SHA256,
           'records':args.size,'sources':1,'verified_fraction':0.01,'query':'Atlas','repeats':args.repeats,
           'index_state':'source discovery not rebuilt; raw evidence unavailable; no model calls',
           'context':measure(store,p,context,args.repeats),'bundle':measure(store,p,bundle,args.repeats)}
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['process_peak_rss_bytes']=rss if sys.platform=='darwin' else rss*1024
        print(json.dumps(report,indent=2))

if __name__=='__main__':main()

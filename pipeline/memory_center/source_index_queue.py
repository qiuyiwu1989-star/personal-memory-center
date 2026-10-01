"""Zero-provider, owner/scope-coalesced visible-source indexing.

Enqueue only inside an already-authorized ingest transaction. Technical work
never grants an external principal permissions or changes memory truth state.
"""
import math
from pathlib import Path
import re
import time
from .core import Invalid, permit, uid


def setup(store):
    with store.db() as db:
        db.executescript(Path(__file__).with_name('migrations').joinpath('006_scope_index_queue.sql').read_text())


def enqueue(db, owner, scope):
    """Internal hook; caller must have checked ingest permissions beforehand.

    Do not open/commit a separate transaction: source and dirty generation must
    either both commit or both roll back. A processing lease stays intact.
    """
    if any(not isinstance(value,str) or not 1 <= len(value) <= 1000 for value in (owner,scope)):
        raise Invalid('索引队列 owner/scope 无效')
    db.execute('INSERT INTO scope_index_queue '
               '(owner,scope,generation,indexed_generation,state,lease,lease_until,attempts,error_type,retry_after,updated,last_indexed) '
               "VALUES(?,?,1,0,'pending',NULL,NULL,0,NULL,NULL,?,NULL) "
               'ON CONFLICT(owner,scope) DO UPDATE SET generation=scope_index_queue.generation+1, '
               "state=CASE WHEN scope_index_queue.state='processing' THEN 'processing' ELSE 'pending' END, "
               'error_type=NULL,retry_after=NULL,updated=?', (owner,scope,time.time(),time.time()))


def _seconds(value, low, high, label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise Invalid(label+' 无效')


def work_once(store, lease_seconds=120, debounce_seconds=2):
    """Claim at most one merged scope; expired claims and bounded retries recover.

    Debounce avoids a full scope scan per individual source in an import burst.
    New generation during work remains dirty and becomes pending on completion.
    """
    from .source_discovery import rebuild
    _seconds(lease_seconds,1,900,'索引 lease')
    _seconds(debounce_seconds,0,60,'索引 debounce')
    now=time.time()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM scope_index_queue WHERE "
                       "(state='pending' AND updated<=?) OR (state='processing' AND lease_until<=?) "
                       "OR (state='failed' AND retry_after<=?) ORDER BY updated,owner,scope LIMIT 1",
                       (now-debounce_seconds,now,now)).fetchone()
        if not row:return {'state':'idle','model_calls':0,'extraction_tokens':0}
        row=dict(row);lease=uid();generation=row['generation']
        db.execute("UPDATE scope_index_queue SET state='processing',lease=?,lease_until=?,attempts=attempts+1 "
                   'WHERE owner=? AND scope=? AND generation=?',
                   (lease,now+lease_seconds,row['owner'],row['scope'],generation))
    technical={'id':'source-index-worker-v1','owner':row['owner'],'scopes':[row['scope']],
               'actions':['read','source_read','write'],'trusted_user':False}
    error_type=None
    try:
        counts=rebuild(store,technical,row['scope'])
    except Exception as error:
        # Never persist str(error), SQL, source text, provider payload, or stack.
        error_type=re.sub(r'[^A-Za-z0-9_]', '',type(error).__name__)[:80] or 'Exception'
        counts=None
    finished=time.time()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT generation,lease,state FROM scope_index_queue WHERE owner=? AND scope=?',
                           (row['owner'],row['scope'])).fetchone()
        if not current or current['lease']!=lease or current['state']!='processing':
            return {'state':'lease_lost','model_calls':0,'extraction_tokens':0}
        current_generation=current['generation']
        if current_generation!=generation:
            state='pending'
            db.execute("UPDATE scope_index_queue SET state='pending',lease=NULL,lease_until=NULL,retry_after=NULL,error_type=NULL "
                       'WHERE owner=? AND scope=? AND lease=? AND generation=?',
                       (row['owner'],row['scope'],lease,current_generation))
        elif error_type:
            state='failed'
            retry=finished+min(60,2**min(row['attempts']+1,6))
            db.execute("UPDATE scope_index_queue SET state='failed',lease=NULL,lease_until=NULL,error_type=?,retry_after=? "
                       'WHERE owner=? AND scope=? AND lease=? AND generation=?',
                       (error_type,retry,row['owner'],row['scope'],lease,generation))
        else:
            state='ready'
            db.execute("UPDATE scope_index_queue SET state='ready',indexed_generation=?,lease=NULL,lease_until=NULL, "
                       'attempts=0,error_type=NULL,retry_after=NULL,last_indexed=? '
                       'WHERE owner=? AND scope=? AND lease=? AND generation=?',
                       (generation,finished,row['owner'],row['scope'],lease,generation))
    result={'state':state,'generation':generation,'model_calls':0,'extraction_tokens':0,'facts_confirmed':False}
    if error_type:result['error_type']=error_type
    if counts is not None:result['index']=counts
    return result


def status(store,principal,scope):
    """Read-only queue metadata, excluding owner, lease token and source content."""
    permit(principal,scope,'read')
    if not isinstance(principal.get('owner'),str) or not principal['owner']:
        raise Invalid('索引状态需要明确 owner')
    with store.db() as db:
        row=db.execute('SELECT generation,indexed_generation,state,lease_until,error_type,retry_after,last_indexed '
                       'FROM scope_index_queue WHERE owner=? AND scope=?',(principal['owner'],scope)).fetchone()
    if not row:
        return {'state':'idle','generation':0,'indexed_generation':0,'dirty':False,'lease_active':False,
                'error_type':None,'retry_after':None,'last_indexed':None}
    result=dict(row)
    until=result.pop('lease_until')
    result['dirty']=result['generation']>result['indexed_generation']
    result['lease_active']=result['state']=='processing' and until is not None and until>time.time()
    return result

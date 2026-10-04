"""One ledger for new extraction, re-extraction and translation.

Legacy bulk jobs retain their existing reservation authority. Missing usage or a
crashed call keeps its reservation; it is never counted as a free request.
"""
import time
from .core import permit_model, Invalid, permit, encoded, uid

SCHEMA = '''
CREATE TABLE IF NOT EXISTS model_budgets(
 owner TEXT NOT NULL, scope TEXT NOT NULL, token_limit INTEGER NOT NULL,
 tokens_spent INTEGER NOT NULL, quality_approved INTEGER NOT NULL,
 note TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(owner,scope));
CREATE TABLE IF NOT EXISTS model_attempts(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 operation TEXT NOT NULL, reference_id TEXT NOT NULL, reservation INTEGER NOT NULL,
 charged INTEGER NOT NULL, state TEXT NOT NULL, usage TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS budget_events(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 actor TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
'''


def setup(store):
    with store.db() as db: db.executescript(SCHEMA)


def configure(store, principal, scope, body):
    permit(principal,scope,'write')
    if not principal.get('trusted_user'): raise PermissionError('仅本人可设置模型预算')
    permit_model(principal,scope)
    cap=body.get('token_limit');quality=body.get('quality_approved',False);note=body.get('note','')
    if type(cap) is not int or not 0<=cap<=100_000_000 or type(quality) is not bool:
        raise Invalid('预算需在 0–100,000,000 tokens 之间')
    if not isinstance(note,str) or len(note)>1000: raise Invalid('预算说明无效')
    if cap>100_000 and (not quality or not note.strip()):
        raise Invalid('超过样本预算前需本人记录质量验收依据')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM model_budgets WHERE owner=? AND scope=?',(principal['owner'],scope)).fetchone()
        spent=old['tokens_spent'] if old else 0
        if cap<spent: raise Invalid('上限不能低于已计量和预留用量')
        db.execute('INSERT INTO model_budgets VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner,scope) DO UPDATE SET '
                   'token_limit=excluded.token_limit,quality_approved=excluded.quality_approved,note=excluded.note,updated=excluded.updated',
                   (principal['owner'],scope,cap,spent,int(quality),note,time.time()))
        db.execute('INSERT INTO budget_events VALUES(?,?,?,?,?,?)',
                   (uid(),principal['owner'],scope,principal['id'],encoded(body),time.time()))
        # Explicit budget action wakes paused generic imports and runs, never legacy bulk.
        db.execute("UPDATE jobs SET state='received',error=NULL WHERE state='paused_budget' AND source_id IN "
                   "(SELECT id FROM sources WHERE owner=? AND scope=? AND principal!='archive-batch')",(principal['owner'],scope))
        db.execute("UPDATE extraction_runs SET state='received',error=NULL WHERE owner=? AND scope=? AND state='paused_budget'", (principal['owner'],scope))
    return status(store,principal,scope)


def status(store,principal,scope):
    permit(principal,scope,'read')
    with store.db() as db:
        row=db.execute('SELECT * FROM model_budgets WHERE owner=? AND scope=?',(principal['owner'],scope)).fetchone()
        unknown=db.execute("SELECT count(*) n FROM model_attempts WHERE owner=? AND scope=? AND state IN ('reserved','usage_unknown')",(principal['owner'],scope)).fetchone()['n']
        legacy=db.execute('SELECT sum(tokens_spent) spent,sum(token_limit) cap FROM bulk_batches WHERE owner=? AND scope=?',(principal['owner'],scope)).fetchone()
        totals=[dict(r) for r in db.execute('SELECT operation,sum(charged) tokens,count(*) attempts FROM model_attempts WHERE owner=? AND scope=? GROUP BY operation',(principal['owner'],scope))]
    return (dict(row) if row else {'scope':scope,'token_limit':0,'tokens_spent':0,'quality_approved':False,'note':''}) | {'unresolved_attempts':unknown,'operations':totals,'legacy_tokens_spent':legacy['spent'] or 0,'shared_token_limit':legacy['cap']}


def reserve(db,source,operation,reference_id):
    # UTF-8 byte count is a conservative input-token allowance, plus prompt/output.
    from .configuration import extra_reservation
    allowance=len(source['payload'].encode('utf-8'))+12000+extra_reservation(db,source['owner'],source['scope'])
    return _reserve(db,source,operation,reference_id,allowance)


def reserve_request(db,source,reference_id,system,max_output_tokens=2048):
    """Bound a quality request with its complete system and input byte allowance.

    Not exposed to clients. Output must use the exact same bounded max_tokens;
    UTF-8 request bytes are a conservative input allowance, plus envelope slack.
    """
    if not isinstance(system,str) or type(max_output_tokens) is not int or not 1<=max_output_tokens<=4096:
        raise Invalid('评测请求预留参数无效')
    allowance=len(source['payload'].encode('utf-8'))+len(system.encode('utf-8'))+max_output_tokens+1024
    return _reserve(db,source,'quality_evaluation',reference_id,allowance)


def _reserve(db,source,operation,reference_id,allowance):
    row=db.execute('SELECT * FROM model_budgets WHERE owner=? AND scope=?',(source['owner'],source['scope'])).fetchone()
    if not row or row['tokens_spent']+allowance>row['token_limit']:return None
    legacy=db.execute('SELECT sum(tokens_spent) spent,sum(token_limit) cap FROM bulk_batches WHERE owner=? AND scope=?',(source['owner'],source['scope'])).fetchone()
    if legacy['cap'] is not None and legacy['spent']+row['tokens_spent']+allowance>legacy['cap']:return None
    aid=uid()
    db.execute('UPDATE model_budgets SET tokens_spent=tokens_spent+? WHERE owner=? AND scope=?',(allowance,source['owner'],source['scope']))
    db.execute('INSERT INTO model_attempts VALUES(?,?,?,?,?,?,?,?,?,?)',
               (aid,source['owner'],source['scope'],operation,reference_id,allowance,allowance,'reserved',None,time.time()))
    return aid


def settle(db,attempt_id,usage):
    if not attempt_id:return
    row=db.execute('SELECT * FROM model_attempts WHERE id=?',(attempt_id,)).fetchone()
    if not row or row['state']!='reserved':return
    usage=usage if isinstance(usage,dict) else {}
    amount=usage.get('total_tokens')
    if type(amount) is not int or amount<0:
        a,b=usage.get('prompt_tokens'),usage.get('completion_tokens')
        amount=a+b if type(a) is int and a>=0 and type(b) is int and b>=0 else None
    if amount is None:
        db.execute("UPDATE model_attempts SET state='usage_unknown',usage=? WHERE id=?",(encoded(usage),attempt_id))
        return
    db.execute("UPDATE model_attempts SET charged=?,state='settled',usage=? WHERE id=?",(amount,encoded(usage),attempt_id))
    db.execute('UPDATE model_budgets SET tokens_spent=tokens_spent+? WHERE owner=? AND scope=?',(amount-row['reservation'],row['owner'],row['scope']))


def scoped_spent(db,owner,scope):
    row=db.execute('SELECT tokens_spent FROM model_budgets WHERE owner=? AND scope=?',(owner,scope)).fetchone()
    return row['tokens_spent'] if row else 0

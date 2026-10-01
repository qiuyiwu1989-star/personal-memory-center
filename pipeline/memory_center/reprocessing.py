"""Evidence-validated, non-destructive previews of revised extraction output.

This does not call a model or schedule work. A caller must separately authorize
and budget extraction. Matching a quote does not verify the resulting statement.
"""
import json
import time
from .core import Invalid, permit, validate_plan, uid, encoded

SCHEMA = '''
CREATE TABLE IF NOT EXISTS extraction_previews(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, method_version TEXT NOT NULL,
 source_digest TEXT NOT NULL, comparison TEXT NOT NULL, created REAL NOT NULL);
'''


def preview(store, principal, source_id, plan, method_version):
    if not isinstance(method_version,str) or not 1 <= len(method_version) <= 100:
        raise Invalid('需要方法版本')
    with store.db() as db:
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        source=db.execute('SELECT * FROM sources WHERE id=? AND owner=?',(source_id,principal['owner'])).fetchone()
        if not source:raise Invalid('来源不存在')
        permit(principal,source['scope'],'read');permit(principal,source['scope'],'write')
        source=dict(source)
        source['processing_method_version']=method_version
        claims=validate_plan(plan,source)
        old=[dict(r) for r in db.execute('SELECT * FROM records WHERE source_id=?',(source_id,))]
        changes=[]
        for claim in claims:
            identical=[r['id'] for r in old if r['statement']==claim['statement'] and r['message_id']==claim['message_id']]
            related=[r['id'] for r in old if r['subject']==claim['subject'] and r['kind']==claim['kind'] and r['lifecycle']=='active']
            changes.append({'candidate':claim,'comparison':'duplicate' if identical else 'related_needs_review' if related else 'new',
                            'existing_ids':identical or related, 'existing':[{'id':r['id'],'statement':r['statement'],'lifecycle':r['lifecycle'],'status':r['status']} for r in old if r['id'] in (identical or related)]})
        result={'id':uid(),'source_id':source_id,'method_version':method_version,'changes':changes,
                'policy':'preview-only-no-replacement','semantic_verified':False}
        db.execute('INSERT INTO extraction_previews VALUES(?,?,?,?,?,?)',
                   (result['id'],source_id,method_version,source['digest'],encoded(result),time.time()))
    return result

RUN_SCHEMA = '''
CREATE TABLE IF NOT EXISTS run_operations(
 run_id TEXT PRIMARY KEY, operation TEXT NOT NULL, record_id TEXT);
CREATE TABLE IF NOT EXISTS record_translations(
 record_id TEXT NOT NULL, language TEXT NOT NULL, text TEXT NOT NULL,
 run_id TEXT NOT NULL, reviewed REAL NOT NULL, PRIMARY KEY(record_id,language));
CREATE TABLE IF NOT EXISTS extraction_runs(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 source_id TEXT NOT NULL, source_digest TEXT NOT NULL, method_version TEXT NOT NULL,
 request_key TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL,
 lease TEXT, lease_until REAL, preview_id TEXT, error TEXT, usage TEXT, created REAL NOT NULL,
 UNIQUE(owner,scope,request_key));
'''


def setup(store):
    with store.db() as db:
        db.executescript(SCHEMA)
        db.executescript(RUN_SCHEMA)


def enqueue(store,principal,source_id,request_key,operation='reextract',record_id=None):
    from .model import PROMPT_VERSION
    if operation not in ('reextract','translate'):raise Invalid('整理操作无效')
    if not isinstance(request_key,str) or not 1<=len(request_key)<=160:raise Invalid('需要稳定的重跑请求键')
    setup(store)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        source=db.execute('SELECT * FROM sources WHERE id=? AND owner=?',(source_id,principal['owner'])).fetchone()
        if not source:raise Invalid('来源不存在')
        permit(principal,source['scope'],'read');permit(principal,source['scope'],'write')
        if operation=='translate':
            record=db.execute("SELECT id FROM records WHERE id=? AND owner=? AND source_id=? AND lifecycle='active'", (record_id,principal['owner'],source_id)).fetchone()
            if not record:raise Invalid('待翻译记录不存在或已被取代')
        old=db.execute('SELECT id,source_id,method_version FROM extraction_runs WHERE owner=? AND scope=? AND request_key=?',
                       (principal['owner'],source['scope'],request_key)).fetchone()
        if old:
            op=db.execute('SELECT operation,record_id FROM run_operations WHERE run_id=?',(old['id'],)).fetchone()
            if (op and (op['operation']!=operation or op['record_id']!=record_id)) or old['source_id']!=source_id or old['method_version']!=PROMPT_VERSION:raise Invalid('请求键已用于其他来源或方法版本')
            return {'id':old['id'],'duplicate':True}
        pending=db.execute("SELECT count(*) n FROM extraction_runs WHERE owner=? AND state IN ('received','processing','paused_budget')",(principal['owner'],)).fetchone()['n']
        if pending>=50:raise Invalid('重提炼队列最多 50 个待处理任务')
        rid=uid()
        db.execute('INSERT INTO extraction_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (rid,principal['owner'],source['scope'],source_id,source['digest'],PROMPT_VERSION,request_key,'received',0,None,None,None,None,None,time.time()))
        db.execute('INSERT INTO run_operations VALUES(?,?,?)',(rid,operation,record_id))
    return {'id':rid,'duplicate':False}


def listing(store,principal,scope,source_id=None):
    permit(principal,scope,'read');setup(store)
    with store.db() as db:
        rows=[dict(r) for r in db.execute('SELECT r.*,s.source_key FROM extraction_runs r JOIN sources s ON s.id=r.source_id WHERE r.owner=? AND r.scope=?'+
              (' AND r.source_id=?' if source_id else '')+' ORDER BY r.created DESC LIMIT 40',
              (principal['owner'],scope)+((source_id,) if source_id else ()))]
    with store.db() as db:
        operations={r['run_id']:dict(r) for r in db.execute('SELECT o.* FROM run_operations o JOIN extraction_runs r ON r.id=o.run_id WHERE r.owner=? AND r.scope=?',(principal['owner'],scope))}
    for row in rows:
        row.update(operations.get(row['id'],{'operation':'reextract'}))
        row.pop('lease',None);row['usage']=json.loads(row['usage']) if row['usage'] else None
    return {'runs':rows}


def get_preview(store,principal,preview_id):
    with store.db() as db:
        row=db.execute('SELECT p.comparison,s.scope FROM extraction_previews p JOIN sources s ON s.id=p.source_id WHERE p.id=? AND s.owner=?',
                       (preview_id,principal['owner'])).fetchone()
    if not row:raise Invalid('差异不存在')
    permit(principal,row['scope'],'read')
    return json.loads(row['comparison'])


def process_one(store,model):
    from .budget import reserve,settle
    from .model import PROMPT_VERSION
    setup(store)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        # Expired calls retain their ledger reservation and require explicit retry.
        db.execute("UPDATE extraction_runs SET state='failed',error='worker_interrupted',lease=NULL WHERE state='processing' AND lease_until<?",(time.time(),))
        run=db.execute("SELECT * FROM extraction_runs WHERE state='received' ORDER BY created LIMIT 1").fetchone()
        if not run:return False
        run=dict(run)
        if run['method_version']!=PROMPT_VERSION:
            db.execute("UPDATE extraction_runs SET state='failed',error='method_version_changed' WHERE id=?",(run['id'],));return True
        source=dict(db.execute('SELECT * FROM sources WHERE id=?',(run['source_id'],)).fetchone())
        operation=db.execute('SELECT * FROM run_operations WHERE run_id=?',(run['id'],)).fetchone()
        operation=dict(operation) if operation else {'operation':'reextract'}
        if operation['operation']=='translate':
            target=db.execute('SELECT * FROM records WHERE id=? AND owner=?',(operation['record_id'],run['owner'])).fetchone()
            if not target or target['lifecycle']!='active':
                db.execute("UPDATE extraction_runs SET state='failed',error='record_superseded' WHERE id=?",(run['id'],));return True
            target=dict(target)
            metered_source=dict(source,payload=encoded({'statement':target['statement']}))
        else: metered_source=source
        attempt=reserve(db,metered_source,operation['operation'],run['id'])
        if not attempt:
            db.execute("UPDATE extraction_runs SET state='paused_budget',error='模型预算未设置或已用尽' WHERE id=?",(run['id'],));return True
        lease=uid()
        db.execute("UPDATE extraction_runs SET state='processing',attempts=attempts+1,lease=?,lease_until=? WHERE id=?",(lease,time.time()+180,run['id']))
    usage=None
    try:
        if operation['operation']=='translate':
            translated,usage=model.translate(target['statement'])
            if not isinstance(translated,str) or not 1<=len(translated)<=2000:raise Invalid('翻译输出无效')
            comparison={'id':uid(),'source_id':source['id'],'method_version':'zh-projection-v1','operation':'translate','semantic_verified':False,
                        'changes':[{'comparison':'translation','candidate':{'record_id':target['id'],'original':target['statement'],'text':translated}}]}
            with store.db() as db:
                db.execute('INSERT INTO extraction_previews VALUES(?,?,?,?,?,?)',(comparison['id'],source['id'],'zh-projection-v1',source['digest'],encoded(comparison),time.time()))
        else:
            plan,usage=model.extract_source(source) if hasattr(model,'extract_source') else model.extract(json.loads(source['payload']))
        p={'id':'memory-worker','owner':run['owner'],'scopes':[run['scope']],'actions':['read','write']}
        if operation['operation']!='translate': comparison=preview(store,p,source['id'],plan,run['method_version'])
        with store.db() as db:
            db.execute("UPDATE extraction_runs SET state='ready',preview_id=?,usage=?,error=NULL,lease=NULL WHERE id=? AND lease=?",
                       (comparison['id'],encoded(usage),run['id'],lease))
    except Exception as exc:
        usage=getattr(exc,'usage',usage)
        error=str(exc) if isinstance(exc,Invalid) else type(exc).__name__
        with store.db() as db:
            db.execute("UPDATE extraction_runs SET state='failed',error=?,usage=?,lease=NULL WHERE id=? AND lease=?",(error[:160],encoded(usage),run['id'],lease))
    finally:
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');settle(db,attempt,usage)
    return True


def control(store,principal,run_id,action,indices=None):
    from .core import Conflict
    if not principal.get('trusted_user'):raise PermissionError('仅本人可应用或重试重提炼结果')
    if action not in ('apply','discard','retry'):raise Invalid('重提炼操作无效')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        run=db.execute('SELECT * FROM extraction_runs WHERE id=? AND owner=?',(run_id,principal['owner'])).fetchone()
        if not run:raise Invalid('任务不存在')
        permit(principal,run['scope'],'write')
        if action=='retry':
            if run['state']!='failed':raise Conflict('仅失败任务可重试')
            db.execute("UPDATE extraction_runs SET state='received',error=NULL WHERE id=?",(run_id,));return {'state':'received'}
        if run['state']!='ready':raise Conflict('只能处理待审核的结果')
        if action=='discard':
            db.execute("UPDATE extraction_runs SET state='discarded' WHERE id=?",(run_id,));return {'state':'discarded'}
        comparison=json.loads(db.execute('SELECT comparison FROM extraction_previews WHERE id=?',(run['preview_id'],)).fetchone()['comparison'])
        changes=comparison['changes']
        if not isinstance(indices,list) or not indices or any(type(i) is not int or not 0<=i<len(changes) for i in indices) or len(set(indices))!=len(indices):
            raise Invalid('需要选择有效的候选序号')
        if comparison.get('operation')=='translate':
            if indices!=[0]:raise Invalid('译文选择无效')
            candidate=changes[0]['candidate']
            target=db.execute("SELECT statement FROM records WHERE id=? AND owner=? AND lifecycle='active'",(candidate['record_id'],principal['owner'])).fetchone()
            if not target or target['statement']!=candidate['original']:raise Conflict('原记忆已变化，译文不再适用')
            db.execute('INSERT INTO record_translations VALUES(?,?,?,?,?) ON CONFLICT(record_id,language) DO UPDATE SET text=excluded.text,run_id=excluded.run_id,reviewed=excluded.reviewed',
                       (candidate['record_id'],'zh',candidate['text'],run_id,time.time()))
            db.execute("UPDATE extraction_runs SET state='applied' WHERE id=?",(run_id,))
            return {'state':'applied','translation_only':True,'verified':False}
        ids=[]
        for i in indices:
            claim=changes[i]['candidate']
            old=db.execute('SELECT id FROM records WHERE source_id=? AND message_id=? AND statement=?',
                           (run['source_id'],claim['message_id'],claim['statement'])).fetchone()
            if old:continue
            rid=uid();ids.append(rid)
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (rid,run['owner'],run['scope'],claim['topic'],claim['kind'],claim['subject'],claim['statement'],claim['status'],run['source_id'],claim['message_id'],claim['quote'],'active',1,None,time.time()))
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(uid(),rid,principal['id'],'reextract_candidate',None,time.time()))
        db.execute("UPDATE extraction_runs SET state='applied' WHERE id=?",(run_id,))
    return {'state':'applied','new_candidate_ids':ids,'verified':False}

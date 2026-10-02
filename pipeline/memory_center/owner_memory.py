"""Explicit owner maintenance, immutable revisions, no inferred confirmation.

Author identity is not the holder of a quoted judgment. External imports must
not call this human-only route. No model, extraction dispatch or new schema.
"""
import datetime
import hashlib
import json
import time
from .core import Invalid, Conflict, permit, encoded, uid
from .governance import metadata

_TOPICS={'profile','preferences','people','areas','projects','topics'}
_KINDS={'identity','preference','relationship','decision','plan','event','claim','suggestion'}
_BASE={'request_key','statement','topic','kind','subject','governance','explicit_confirmation','change_kind','previous_valid_until'}


def _auth(principal,scope):
    if principal.get('trusted_user') is not True:raise PermissionError('仅本人可维护陈述和审核字段')
    permit(principal,scope,'read');permit(principal,scope,'write')
    if any(not isinstance(principal.get(k),str) or not 1<=len(principal[k])<=160 for k in ('id','owner')):
        raise Invalid('本人身份无效')


def _request(body,revision=False):
    allowed=_BASE|({'revision','governance_revision'} if revision else set())
    if not isinstance(body,dict) or set(body)-allowed:raise Invalid('本人维护字段无效；不接受导入来源或角色')
    key=body.get('request_key')
    if not isinstance(key,str) or not 1<=len(key)<=160:raise Invalid('需要稳定 request_key')
    result={'request_key':key,'explicit_confirmation':body.get('explicit_confirmation',False)}
    if type(result['explicit_confirmation']) is not bool:raise Invalid('explicit_confirmation 必须是布尔值')
    for field,maximum in (('statement',2000),('subject',160)):
        if field in body:
            value=body[field]
            if not isinstance(value,str) or not 1<=len(value.strip())<=maximum:raise Invalid('陈述或对象文本无效')
            result[field]=value.strip()
    if not revision and 'statement' not in result:raise Invalid('需要本人填写陈述正文')
    for field,choices in (('topic',_TOPICS),('kind',_KINDS)):
        if field in body:
            if not isinstance(body[field],str) or body[field] not in choices:raise Invalid('主题或类型无效')
            result[field]=body[field]
    if revision:
        for field in ('revision','governance_revision'):
            value=body.get(field)
            if type(value) is not int or value<0:raise Invalid('需要记录与治理 revision')
            result[field]=value
    from .judgment_contract import normalize
    gov=body.get('governance',{})
    if not isinstance(gov,dict):raise Invalid('审核字段无效')
    values=normalize(dict(gov,state=gov.get('state','verified' if result['explicit_confirmation'] else 'candidate')))
    if (values['state']=='verified') != result['explicit_confirmation']:
        raise Invalid('verified 必须对应本次明确确认，不能从旧状态推断')
    from .temporal import request as temporal_request
    if 'change_kind' in body or 'previous_valid_until' in body:
        result.update(temporal_request(body))
    result['governance']=values
    return result


def _verified(db,principal,scope,governance):
    from .judgment_contract import validate_verified
    validate_verified(db,principal['owner'],scope,governance)


def _key(principal,scope,request,operation):
    return 'owner-memory:'+operation+':'+hashlib.sha256(encoded([
        principal['owner'],scope,principal['id'],request['request_key']]).encode()).hexdigest()


def _duplicate(db,principal,scope,key,digest):
    source=db.execute('SELECT id,digest FROM sources WHERE owner=? AND scope=? AND principal=? AND source_key=?',
                      (principal['owner'],scope,principal['id'],key)).fetchone()
    if not source:return None
    if source['digest']!=digest:raise Conflict('request_key 已用于不同内容，请使用新请求键')
    envelope=db.execute('SELECT metadata FROM source_envelopes WHERE source_id=?',(source['id'],)).fetchone()
    locator=json.loads(json.loads(envelope['metadata'])['locator'])
    record=db.execute('SELECT id,revision FROM records WHERE id=? AND owner=? AND scope=?',
                      (locator['record_id'],principal['owner'],scope)).fetchone()
    if not record:raise Conflict('幂等结果关联不完整')
    return {'id':record['id'],'revision':record['revision'],'source_id':source['id'],'duplicate':True,
            'explicit_confirmation':locator['explicit_confirmation'],'index_queued':False}


def _source(db,principal,scope,key,digest,record_id,statement,operation,confirmation,now):
    sid=uid();mid='owner-statement' if operation in ('create','statement_edit') else 'owner-review-audit'
    text=statement if mid=='owner-statement' else '本人审核元数据（不改变原陈述归属）：'+statement
    payload=encoded([{'id':mid,'role':'user','text':text,'source_title':'本人手动维护记录',
                      'created_at':datetime.datetime.fromtimestamp(now,datetime.timezone.utc).isoformat()}])
    source_type='document' if operation=='create' else 'correction'
    db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
               (sid,principal['owner'],scope,key,digest,source_type,principal['id'],1,payload,now))
    envelope={'author':principal['id'],'original_ref':'owner-memory://'+record_id,
              'locator':encoded({'record_id':record_id,'origin':'owner_manual_entry','operation':operation,
                                 'explicit_confirmation':confirmation})}
    db.execute('INSERT INTO source_envelopes VALUES(?,?,?)',(sid,encoded(envelope),'archive'))
    usage=encoded({'method':'owner_manual','operation':operation,'model_skipped':True,'total_tokens':0})
    db.execute('INSERT INTO jobs(id,source_id,state,usage,created) VALUES(?,?,?,?,?)',
               (uid(),sid,'archived',usage,now))
    from .source_index_queue import enqueue
    enqueue(db,principal['owner'],scope)
    return sid,mid


def _governance(db,principal,record_id,governance,previous,now):
    new=dict(governance,record_id=record_id,revision=1,reviewed=now)
    db.execute('INSERT INTO record_governance VALUES(?,?,?,?,?,?,?,?,?,?)',tuple(new[k] for k in (
        'record_id','holder','subject_id','as_of','valid_until','state','priority','revision','note','reviewed')))
    db.execute('INSERT INTO governance_events VALUES(?,?,?,?,?,?)',
               (uid(),record_id,principal['id'],encoded(previous),encoded(new),now))
    return new


def create(store,principal,scope,body):
    _auth(principal,scope);request=_request(body)
    key=_key(principal,scope,request,'create');digest=hashlib.sha256(encoded(request).encode()).hexdigest()
    now=time.time()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        duplicate=_duplicate(db,principal,scope,key,digest)
        if duplicate:return duplicate
        _verified(db,principal,scope,request['governance'])
        rid=uid();statement=request['statement']
        sid,mid=_source(db,principal,scope,key,digest,rid,statement,'create',request['explicit_confirmation'],now)
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (rid,principal['owner'],scope,request.get('topic','topics'),request.get('kind','claim'),
                    request.get('subject','未指定'),statement,'user_stated',sid,mid,statement,'active',1,None,now))
        governance=_governance(db,principal,rid,request['governance'],{},now)
        from .temporal import record as audit_change, request as temporal_request
        audit_change(store,db,principal,scope,rid,None,1,governance,key,temporal_request(request),now)
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(uid(),rid,principal['id'],'owner_create',None,now))
    return {'id':rid,'revision':1,'source_id':sid,'duplicate':False,
            'explicit_confirmation':request['explicit_confirmation'],'index_queued':True}


def revise(store,principal,scope,record_id,body):
    _auth(principal,scope);request=_request(body,revision=True)
    if not isinstance(record_id,str) or not record_id:raise Invalid('记录 ID 无效')
    key=_key(principal,scope,request,'revise')
    digest=hashlib.sha256(encoded(dict(request,record_id=record_id)).encode()).hexdigest();now=time.time()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        duplicate=_duplicate(db,principal,scope,key,digest)
        if duplicate:return duplicate
        old=db.execute('SELECT * FROM records WHERE id=? AND owner=? AND scope=?',
                       (record_id,principal['owner'],scope)).fetchone()
        if not old:raise Invalid('记录不存在或不可访问')
        old=dict(old)
        previous=metadata(old,db.execute('SELECT * FROM record_governance WHERE record_id=?',(record_id,)).fetchone())
        if old['lifecycle']!='active' or request['revision']!=old['revision'] or request['governance_revision']!=previous['revision']:
            raise Conflict('记录或审核已变化，请刷新')
        _verified(db,principal,scope,request['governance'])
        statement=request.get('statement',old['statement']);changed=statement!=old['statement'];rid=uid()
        audit_sid,mid=_source(db,principal,scope,key,digest,rid,statement if changed else encoded(request['governance']),
                              'statement_edit' if changed else 'governance_edit',request['explicit_confirmation'],now)
        db.execute("UPDATE records SET lifecycle='superseded' WHERE id=? AND owner=? AND scope=?",
                   (record_id,principal['owner'],scope))
        db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (rid,principal['owner'],scope,request.get('topic',old['topic']),request.get('kind',old['kind']),
                    request.get('subject',old['subject']),statement,'user_stated' if changed else old['status'],
                    audit_sid if changed else old['source_id'],mid if changed else old['message_id'],
                    statement if changed else old['quote'],'active',old['revision']+1,record_id,now))
        if not changed:
            # Same assertion/evidence: retain existing display translations.
            # Changed text must not inherit a now-stale translation.
            db.execute('INSERT INTO record_translations(record_id,language,text,run_id,reviewed) '
                       'SELECT ?,language,text,run_id,reviewed FROM record_translations WHERE record_id=?',
                       (rid,record_id))
        governance=_governance(db,principal,rid,request['governance'],previous,now)
        from .temporal import record as audit_change, request as temporal_request
        audit_change(store,db,principal,scope,rid,record_id,old['revision']+1,governance,key,temporal_request(request),now)
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                   (uid(),rid,principal['id'],'owner_statement_edit' if changed else 'owner_governance_edit',record_id,now))
    return {'id':rid,'revision':old['revision']+1,'source_id':audit_sid,'duplicate':False,
            'explicit_confirmation':request['explicit_confirmation'],'index_queued':True,
            'original_evidence_preserved':not changed}

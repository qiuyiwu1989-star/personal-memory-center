"""Scoped read-only governance gaps, never repair identities or effective time."""
import datetime
import json
from .core import Invalid, encoded, permit
from .dependency_audit import _exists

CATEGORIES = ('missing_holder','missing_subject_id','missing_as_of',
              'invalid_effective_date','dangling_supersedes','expired_active',
              'unresolved_entity_reference','cross_scope_entity_reference',
              'source_missing_or_outside_scope','source_payload_invalid',
              'source_message_missing','source_quote_missing_or_mismatch',
              'source_original_locator_missing')


def diagnose(store, principal, scope, sample_limit=3, max_chars=6000, today=None):
    """Aggregate all revisions in one authorized scope without any writes.

    Cross-scope findings inspect only explicitly readable scopes. Unknown
    references remain unresolved; no outside-owner IDs or body text is emitted.
    Stores must already exist: this function never initializes optional tables.
    """
    permit(principal,scope,'read');permit(principal,scope,'source_read')
    if not isinstance(principal.get('owner'),str) or not principal['owner']:
        raise Invalid('归属空间无效')
    if type(sample_limit) is not int or not 0<=sample_limit<=10:
        raise Invalid('样本上限为 0–10')
    if type(max_chars) is not int or not 1000<=max_chars<=16000:
        raise Invalid('诊断整包预算为 1000–16000 字符')
    date=today or datetime.date.today().isoformat()
    try:
        if datetime.date.fromisoformat(date).isoformat()!=date:raise ValueError()
    except (ValueError,TypeError):raise Invalid('诊断日期需为 YYYY-MM-DD') from None
    counts={k:0 for k in CATEGORIES};samples={k:[] for k in CATEGORIES}
    missing=[];owner=principal['owner']
    def flag(category,record_id):
        counts[category]+=1
        if len(samples[category])<sample_limit:samples[category].append(record_id)
    with store.db() as db:
        records=[dict(r) for r in db.execute('SELECT id,source_id,message_id,quote,supersedes,lifecycle '
                                           'FROM records WHERE owner=? AND scope=? ORDER BY id',(owner,scope))]
        ids={r['id'] for r in records}
        governed={}
        if _exists(store,db,'record_governance'):
            governed={r['record_id']:dict(r) for r in db.execute('SELECT g.* FROM record_governance g '
                      'JOIN records r ON r.id=g.record_id WHERE r.owner=? AND r.scope=?',(owner,scope))}
        else:missing.append('record_governance')
        entities={};other_entities=set()
        if _exists(store,db,'memory_entities'):
            entities={r['id'] for r in db.execute('SELECT id FROM memory_entities WHERE owner=? AND scope=?',(owner,scope))}
            # Never probe an inaccessible scope merely to classify a reference.
            for other_scope in sorted(set(principal.get('scopes',[]))-{scope}):
                other_entities.update(r['id'] for r in db.execute('SELECT id FROM memory_entities WHERE owner=? AND scope=?',
                                                               (owner,other_scope)))
        else:missing.append('memory_entities')
        sources={r['id']:dict(r) for r in db.execute('SELECT DISTINCT s.id,s.payload FROM sources s JOIN records r ON r.source_id=s.id '
                  'WHERE s.owner=? AND s.scope=? AND r.owner=? AND r.scope=?',(owner,scope,owner,scope))}
        envelopes={}
        if _exists(store,db,'source_envelopes'):
            envelopes={r['source_id']:r['metadata'] for r in db.execute('SELECT DISTINCT e.source_id,e.metadata FROM source_envelopes e '
                       'JOIN sources s ON s.id=e.source_id JOIN records r ON r.source_id=s.id '
                       'WHERE s.owner=? AND s.scope=? AND r.owner=? AND r.scope=?',(owner,scope,owner,scope))}
        else:missing.append('source_envelopes')
        parsed={}
        for record in records:
            rid=record['id'];g=governed.get(rid,{})
            for field in ('holder','subject_id','as_of'):
                if not g.get(field):flag('missing_'+field,rid)
            invalid_entity=False;cross_scope=False
            for field in ('holder','subject_id'):
                eid=g.get(field)
                if eid and eid!='owner:'+owner and eid not in entities:
                    invalid_entity=True
                    if eid in other_entities:cross_scope=True
            if invalid_entity:flag('unresolved_entity_reference',rid)
            if cross_scope:flag('cross_scope_entity_reference',rid)
            dates_valid=True
            for field in ('as_of','valid_until'):
                value=g.get(field)
                if value:
                    try:
                        if datetime.date.fromisoformat(value).isoformat()!=value:raise ValueError()
                    except (ValueError,TypeError):dates_valid=False
            if not dates_valid:flag('invalid_effective_date',rid)
            if dates_valid and record['lifecycle']=='active' and g.get('valid_until') and g['valid_until']<=date:
                flag('expired_active',rid)
            if record['supersedes'] and record['supersedes'] not in ids:flag('dangling_supersedes',rid)
            source=sources.get(record['source_id'])
            if not source:
                flag('source_missing_or_outside_scope',rid);continue
            sid=source['id']
            if sid not in parsed:
                try:
                    messages=json.loads(source['payload'])
                    if not isinstance(messages,list) or any(not isinstance(m,dict) or not isinstance(m.get('id'),str)
                                                           or not isinstance(m.get('text'),str) for m in messages):raise ValueError()
                    parsed[sid]={m['id']:m for m in messages}
                except (ValueError,TypeError):parsed[sid]=None
            messages=parsed[sid]
            if messages is None:flag('source_payload_invalid',rid)
            else:
                message=messages.get(record['message_id'])
                if message is None:flag('source_message_missing',rid)
                elif not record['quote'] or record['quote'] not in message['text']:
                    flag('source_quote_missing_or_mismatch',rid)
            try:envelope=json.loads(envelopes.get(sid,'{}'))
            except (ValueError,TypeError):envelope={}
            if not isinstance(envelope,dict) or not any(isinstance(envelope.get(k),str) and envelope[k].strip()
                                                       for k in ('original_ref','locator')):
                flag('source_original_locator_missing',rid)
    result={'scope':scope,'read_only':True,'record_count':len(records),'active_count':sum(r['lifecycle']=='active' for r in records),
            'counts':counts,'coverage_missing':missing,'cross_scope_coverage':'authorized-scopes-only',
            'samples':{},'truncated':False}
    if len(encoded(result))>max_chars:raise Invalid('诊断摘要超过预算')
    for category,record_ids in samples.items():
        for rid in record_ids:
            candidate=dict(result,samples={k:list(v) for k,v in result['samples'].items()})
            candidate['samples'].setdefault(category,[]).append(rid)
            # Reserve the longer false representation before finalizing flag.
            if len(encoded(candidate))<=max_chars:result=candidate
            else:result['truncated']=True
    return result

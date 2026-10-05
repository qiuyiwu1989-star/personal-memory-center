"""Read-only, scoped governance receipts. No model, projection rebuild or DDL."""
import datetime
import json
import re
from .core import Invalid, permit
from .governance import metadata, usable
from .dependency_audit import _exists

_REF = re.compile(r'^- 记录：([^\s]+) / v\d+ /', re.M)


def _page(value, name, upper):
    try:
        if isinstance(value, bool): raise ValueError()
        result = int(value)
        if str(result) != str(value) or not 0 <= result <= upper: raise ValueError()
        return result
    except (ValueError, TypeError):
        raise Invalid(name+'无效') from None


def _usage(raw):
    try: data = json.loads(raw or 'null') or {}
    except (ValueError, TypeError): data = {}
    if not isinstance(data, dict): data = {}
    tokens = {key: data.get(key) if type(data.get(key)) is int and data[key] >= 0 else None
              for key in ('prompt_tokens','completion_tokens','total_tokens')}
    # Never infer a provider's total, price, or successful no-cost call.
    state = 'model_skipped' if data.get('model_skipped') is True else 'measured' if any(v is not None for v in tokens.values()) else 'unknown'
    return {'state':state, **tokens, 'monetary_cost':None,'currency':None}, data.get('method_version')


def _record(raw, messages):
    row = dict(raw)
    governed = {key:row.pop('g_'+key) for key in ('record_id','holder','subject_id','as_of','valid_until','state','priority','revision','note','reviewed')}
    row['governance'] = metadata(row, governed if governed['record_id'] is not None else None)
    row['usable'] = usable(row)
    reasons = []
    g = row['governance']
    if row['lifecycle'] != 'active': reasons.append('inactive_revision')
    if g['state'] != 'verified': reasons.append('not_verified')
    if not all(g.get(k) for k in ('holder','subject_id','as_of')): reasons.append('incomplete_attribution_or_time')
    if g.get('as_of') and str(g['as_of']) > datetime.date.today().isoformat(): reasons.append('not_yet_effective')
    if g.get('valid_until') and str(g['valid_until']) <= datetime.date.today().isoformat(): reasons.append('expired')
    if not row['usable'] and not reasons: reasons.append('invalid_governance')
    msg = messages.get(row['message_id'],{})
    row['evidence'] = {'source_id':row['source_id'],'message_id':row['message_id'],
                       'message_present':bool(msg),'role':msg.get('role'),'created_at':msg.get('created_at'),'date':msg.get('created_at')}
    row['exclusion_reasons'] = reasons
    return row


def source_ledger(store, principal, scope, source_id, limit=20, offset=0):
    permit(principal, scope, 'read')
    limit = _page(limit,'limit',100); offset = _page(offset,'offset',10000)
    if limit < 1: raise Invalid('limit无效')
    if not isinstance(source_id,str) or not 1 <= len(source_id) <= 300: raise Invalid('来源不存在或不可访问')
    owner = principal['owner']
    fields = ('record_id','holder','subject_id','as_of','valid_until','state','priority','revision','note','reviewed')
    columns = ','.join('g.'+k+' g_'+k for k in fields)
    where = 'r.source_id=? AND r.owner=? AND r.scope=?'
    params = (source_id,owner,scope)
    summary = dict(records_total=0,current_usable=0,candidate=0,historical=0,rejected=0,evidence_message_count=0,source_message_count=0)
    with store.db() as db:
        source = db.execute('SELECT id,scope,source_key,source_type,digest,created,payload FROM sources WHERE id=? AND owner=? AND scope=?',params).fetchone()
        if not source: raise Invalid('来源不存在或不可访问')
        source = dict(source)
        messages = {m['id']:m for m in json.loads(source.pop('payload'))}
        summary['source_message_count'] = len(messages)
        source['message_count'] = len(messages)
        envelope = db.execute('SELECT policy,metadata FROM source_envelopes WHERE source_id=?',(source_id,)).fetchone()
        source['processing_policy'] = envelope['policy'] if envelope else 'legacy'
        source['visibility'] = json.loads(envelope['metadata']).get('visibility','unknown') if envelope else 'unknown'
        used_messages = set()
        # Stream summary metadata; never materialize the complete record set.
        for raw in db.execute('SELECT r.id,r.source_id,r.message_id,r.lifecycle,'+columns+' FROM records r LEFT JOIN record_governance g ON g.record_id=r.id WHERE '+where,params):
            item = _record(raw,messages); summary['records_total'] += 1
            summary['current_usable'] += int(item['usable'])
            state = item['governance']['state']
            summary['candidate'] += int(state == 'candidate' and item['lifecycle']=='active')
            summary['historical'] += int(state == 'historical' or item['lifecycle']!='active')
            summary['rejected'] += int(state == 'rejected')
            if item['evidence']['message_present']: used_messages.add(item['message_id'])
        summary['evidence_message_count'] = len(used_messages)
        records = [_record(r,messages) for r in db.execute('SELECT r.id,r.source_id,r.message_id,r.statement,r.kind,r.subject,r.lifecycle,r.revision,r.supersedes,'+columns+' FROM records r LEFT JOIN record_governance g ON g.record_id=r.id WHERE '+where+' ORDER BY r.created DESC,r.id LIMIT ? OFFSET ?',params+(limit,offset))]
        jobs = []
        for raw in db.execute('SELECT id,state,attempts,error,usage,created FROM jobs WHERE source_id=? ORDER BY created DESC LIMIT ? OFFSET ?',(source_id,limit,offset)):
            job = dict(raw); job['usage'],job['method_version'] = _usage(job.pop('usage')); job['error_present'] = bool(job.pop('error')); job['kind']='initial_extraction'; jobs.append(job)
        jobs_total = db.execute('SELECT count(*) n FROM jobs WHERE source_id=?',(source_id,)).fetchone()['n']
        runs = [dict(r) for r in db.execute('SELECT id,state,attempts,error,usage,method_version,created FROM extraction_runs WHERE source_id=? AND owner=? AND scope=? ORDER BY created DESC,id LIMIT ? OFFSET ?',params+(limit,offset))]
        for run in runs:
            run['usage'],_ = _usage(run.pop('usage')); run['error_present']=bool(run.pop('error'));run['kind']='reprocessing'
        runs_total = db.execute('SELECT count(*) n FROM extraction_runs WHERE source_id=? AND owner=? AND scope=?',params).fetchone()['n']
        documents = []; document_scan_total = 0; inspected = 0
        if _exists(store,db,'document_versions'):
            document_scan_total=db.execute('SELECT count(*) n FROM document_versions WHERE owner=? AND scope=?',(owner,scope)).fetchone()['n']
            for doc in db.execute('SELECT slug,revision,markdown,created FROM document_versions WHERE owner=? AND scope=? ORDER BY created DESC,slug,revision DESC LIMIT ? OFFSET ?',(owner,scope,limit,offset)):
                inspected += 1
                refs = list(set(_REF.findall(doc['markdown'] or '')))
                matched = 0
                for start in range(0,len(refs),200):
                    batch=refs[start:start+200]
                    matched += db.execute('SELECT count(*) n FROM records r WHERE '+where+' AND r.id IN ('+','.join('?' for _ in batch)+')',params+tuple(batch)).fetchone()['n']
                if matched: documents.append({'slug':doc['slug'],'revision':doc['revision'],'created':doc['created'],'referenced_records_count':matched,'relationship':'stored_record_reference'})
        attempt_where = ('a.owner=? AND a.scope=? AND (a.reference_id IN (SELECT id FROM jobs WHERE source_id=?) '
                         'OR a.reference_id IN (SELECT id FROM extraction_runs WHERE source_id=? AND owner=? AND scope=?))')
        attempt_params = (owner,scope,source_id,source_id,owner,scope)
        attempts_total = db.execute('SELECT count(*) n FROM model_attempts a WHERE '+attempt_where,attempt_params).fetchone()['n']
        attempts = [dict(r) for r in db.execute('SELECT a.id,a.operation,a.reference_id,a.reservation,a.charged,a.state,a.usage,a.created FROM model_attempts a WHERE '+attempt_where+' ORDER BY a.created DESC,a.id LIMIT ? OFFSET ?',attempt_params+(limit,offset))]
        for attempt in attempts:
            attempt['usage'],attempt['method_version'] = _usage(attempt.pop('usage'))
            attempt['charged_is_accounting_not_measured_usage'] = True
        withdrawal = None
        if _exists(store,db,'source_withdrawals'):
            row=db.execute('SELECT created FROM source_withdrawals WHERE source_id=? AND owner=? AND scope=?',params).fetchone()
            if row: withdrawal={'state':'withdrawn','created':row['created'],'archive_retained':True}
    source['withdrawal'] = withdrawal
    source['state'] = 'withdrawn' if withdrawal else 'active'
    for record in records: record['source_withdrawn'] = bool(withdrawal)
    if withdrawal:
        # Source withdrawal overrides stored judgments even before projections refresh.
        summary['current_usable']=0
        for record in records:
            record['usable']=False;record['exclusion_reasons'].append('source_withdrawn')
    return {'source':source,'summary':summary,'records':records,'jobs':jobs,'runs':runs,'attempts':attempts,'documents':documents,
            'pagination':{'limit':limit,'offset':offset,'records':{'total':summary['records_total'],'truncated':offset+len(records)<summary['records_total']},'jobs':{'total':jobs_total,'truncated':offset+len(jobs)<jobs_total},'runs':{'total':runs_total,'truncated':offset+len(runs)<runs_total},'attempts':{'total':attempts_total,'truncated':offset+len(attempts)<attempts_total},'documents':{'scan_total':document_scan_total,'inspected':inspected,'coverage':'partial' if offset or inspected<document_scan_total else 'complete','truncated':offset+inspected<document_scan_total}},
            'policy':'scoped-read-only-no-model-v1','cost_note':'Token measurements are not monetary prices; absent measurements remain unknown. Document links cover only the inspected stored projection window.'}


def record_ledger(store, principal, scope, record_id, limit=20, offset=0):
    permit(principal,scope,'read')
    if not isinstance(record_id,str) or not 1 <= len(record_id)<=300: raise Invalid('记忆不存在或不可访问')
    with store.db() as db:
        row=db.execute('SELECT id,source_id,message_id,revision,lifecycle FROM records WHERE id=? AND owner=? AND scope=?',(record_id,principal['owner'],scope)).fetchone()
    if not row: raise Invalid('记忆不存在或不可访问')
    result=source_ledger(store,principal,scope,row['source_id'],limit,offset)
    result['focal_record']=dict(row)
    return result

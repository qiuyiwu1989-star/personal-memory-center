"""Non-destructive source dependency preview; no DDL, deletion, or model calls."""
import json
import re
from .core import Invalid, encoded, permit

_DENIED = '来源不存在或不可访问'
_DOCUMENT_RECORD = re.compile(r'^- 记录：([^\s]+) / v\d+ /', re.M)


def _exists(store, db, table):
    if store.dsn:
        return bool(db.execute('SELECT table_name FROM information_schema.tables WHERE table_schema=? AND table_name=?',
                               ('memory_center',table)).fetchone())
    return bool(db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())


def preview(store, principal, scope, source_id, max_chars=6000):
    """Return bounded affected-object metadata, never content or action authority.

    Direct links are exact DB relationships. Topic rules are only potential
    impact; documents are explicitly linked by their stored record references.
    All document revisions are inspected without rebuilding the projection.
    """
    try:
        permit(principal,scope,'read')
        permit(principal,scope,'source_read')
    except PermissionError:
        raise Invalid(_DENIED) from None
    if not isinstance(principal.get('owner'),str) or not principal['owner']:
        raise Invalid(_DENIED)
    if not isinstance(source_id,str) or not 1 <= len(source_id) <= 300:
        raise Invalid(_DENIED)
    if type(max_chars) is not int or not 500 <= max_chars <= 16000:
        raise Invalid('依赖预览预算需为 500–16000 字符')
    counts = {'records':0,'jobs':0,'extraction_runs':0,'topic_rules':0,'document_versions':0,'index_chunks':0}
    objects = []
    missing = []
    runs = []
    with store.db() as db:
        source = db.execute('SELECT id,source_key,digest FROM sources WHERE id=? AND owner=? AND scope=?',
                            (source_id,principal['owner'],scope)).fetchone()
        if not source:
            raise Invalid(_DENIED)
        records = [dict(row) for row in db.execute(
            'SELECT id,lifecycle,status,revision,supersedes FROM records WHERE source_id=? AND owner=? AND scope=? ORDER BY id',
            (source_id,principal['owner'],scope))]
        record_ids = {row['id'] for row in records}
        counts['records'] = len(records)
        objects.extend(dict(row,kind='record',relationship='direct_source') for row in records)
        jobs = [dict(row) for row in db.execute('SELECT j.id,j.state FROM jobs j JOIN sources s ON s.id=j.source_id '
                                              'WHERE s.id=? AND s.owner=? AND s.scope=? ORDER BY j.id',
                                              (source_id,principal['owner'],scope))]
        counts['jobs'] = len(jobs)
        objects.extend(dict(row,kind='job',relationship='direct_source') for row in jobs)
        if _exists(store,db,'extraction_runs'):
            runs = [dict(row) for row in db.execute(
                'SELECT id,state,method_version,source_digest FROM extraction_runs WHERE source_id=? AND owner=? AND scope=? ORDER BY id',
                (source_id,principal['owner'],scope))]
            counts['extraction_runs'] = len(runs)
            objects.extend(dict(row,kind='extraction_run',relationship='direct_source') for row in runs)
        else:
            missing.append('extraction_runs')
        if _exists(store,db,'document_topics'):
            for topic in db.execute('SELECT slug,prefixes FROM document_topics WHERE owner=? AND scope=? ORDER BY slug',
                                    (principal['owner'],scope)):
                try:
                    prefixes = json.loads(topic['prefixes'])
                except (ValueError,TypeError):
                    missing.append('invalid_topic_rule')
                    continue
                if not isinstance(prefixes,list) or not all(isinstance(p,str) for p in prefixes):
                    missing.append('invalid_topic_rule')
                    continue
                if any(source['source_key'].startswith(prefix) for prefix in prefixes):
                    counts['topic_rules'] += 1
                    objects.append({'kind':'topic_rule','slug':topic['slug'],'relationship':'potential_prefix_match'})
        else:
            missing.append('document_topics')
        if _exists(store,db,'document_versions'):
            for document in db.execute('SELECT slug,revision,markdown FROM document_versions WHERE owner=? AND scope=? ORDER BY slug,revision',
                                       (principal['owner'],scope)):
                referenced = sorted(set(_DOCUMENT_RECORD.findall(document['markdown'] or '')) & record_ids)
                if referenced:
                    counts['document_versions'] += 1
                    objects.append({'kind':'document_projection','slug':document['slug'],'revision':document['revision'],
                                    'relationship':'stored_record_reference','referenced_records_count':len(referenced)})
        else:
            missing.append('document_versions')
        if _exists(store,db,'source_discovery_chunks'):
            row = db.execute('SELECT count(*) n FROM source_discovery_chunks WHERE source_id=? AND owner=? AND scope=?',
                             (source_id,principal['owner'],scope)).fetchone()
            counts['index_chunks'] = row['n']
        else:
            missing.append('source_discovery_chunks')
    risks = []
    if counts['records']:
        risks.append('record_evidence_dependency')
    if any(row['state'] in ('received','processing','queued','running','ready') for row in jobs + runs):
        risks.append('unfinished_processing')
    if counts['topic_rules'] or counts['document_versions']:
        risks.append('projection_and_history_dependency')
    if counts['index_chunks']:
        risks.append('derived_index_dependency')
    if missing:
        risks.append('incomplete_optional_table_coverage')
    result = {'source_id':source_id,'preview_only':True,'deletion_supported':False,'counts':counts,
              'risks':risks,'coverage_missing':sorted(set(missing)),'objects':[],'truncated':bool(objects)}
    if len(encoded(result)) > max_chars:
        raise Invalid('依赖摘要超过预算，请提高 max_chars')
    for item in objects:
        candidate = dict(result,objects=result['objects']+[item])
        candidate['truncated'] = len(candidate['objects']) < len(objects)
        if len(encoded(candidate)) > max_chars:
            break
        result = candidate
    return result

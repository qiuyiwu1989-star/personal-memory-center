"""Bounded candidate associations; never combine evidence or change validity.

Call with owner/scope-filtered records. This pure helper also refuses explicit
cross-owner/scope matches. Different source attribution, date or project context
cannot become an exact-duplicate suggestion. No model calls or writes occur.
"""
import re


def _text(value):
    return re.sub(r'\s+', ' ', value).strip() if isinstance(value, str) else ''


def _attribution(item):
    context = item.get('evidence_context') or {}
    status = item.get('status')
    return (item.get('source_type'), item.get('role'), status,
            context.get('source_date'), context.get('conversation_title'),
            context.get('date_role'), context.get('event_time'))


def candidate_links(candidate, records, limit=20):
    """Suggest links while keeping each record, quote and old revision intact.

    ``exact_statement`` means normalized text repeats, not independent
    corroboration. ``same_evidence`` means two claims cite the same source span,
    not that their meanings agree. Unknown attribution is not filled in.
    """
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('candidate link limit must be 1..20')
    if not isinstance(candidate, dict):
        raise ValueError('candidate must be a mapping')
    result=[]
    for record in records:
        if not isinstance(record, dict) or not record.get('id'):
            continue
        if candidate.get('id') == record['id']:
            continue
        if any(candidate.get(k) != record.get(k) for k in ('owner','scope')):
            continue
        if _attribution(candidate) != _attribution(record):
            continue
        statement=_text(candidate.get('statement'))
        exact=(len(statement)>=5 and statement==_text(record.get('statement')) and
               all(candidate.get(k)==record.get(k) for k in ('topic','kind','subject')))
        same=(bool(candidate.get('source_id')) and bool(candidate.get('message_id')) and
              bool(candidate.get('quote')) and
              all(candidate.get(k)==record.get(k) for k in ('source_id','message_id','quote')))
        if not exact and not same:
            continue
        result.append({'record_id':record['id'], 'relation':'exact_statement' if exact else 'same_evidence',
                       'evidence':{k:record.get(k) for k in ('source_id','message_id','quote')},
                       'policy':'association_only_not_merge_or_confirmation'})
        if len(result)>=limit:
            break
    return result

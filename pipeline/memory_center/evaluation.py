"""Deterministic source checks, separate from semantic/owner acceptance."""
from collections import Counter
from .claude import visible_blocks


def evidence_check(record, original_message=None):
    quote=record.get('quote','')
    if not isinstance(quote,str) or not quote:
        return {'evidence':'missing_quote','primary_available':False}
    if original_message is None:
        present=any(quote in m.get('text','') for m in record.get('messages',[]))
        return {'evidence':'secondary_quote_present' if present else 'quote_missing',
                'primary_available':False,'current_validity':'unknown'}
    visible=any(quote in text for _,text in visible_blocks(original_message))
    block_types=[]
    for b in original_message.get('content') or []:
        if isinstance(b,dict):
            text=b.get('text') or b.get('thinking') or ''
            if isinstance(text,str) and quote in text: block_types.append(b.get('type'))
    return {'evidence':'visible_quote_present' if visible else 'excluded_block_quote' if block_types else 'quote_missing',
            'primary_available':True,'matching_block_types':sorted(set(block_types)),
            'source_sender':original_message.get('sender'),
            'current_validity':'unknown'}


def aggregate(reviews):
    """Summarize explicit evaluations; no automatic verification or writeback."""
    return {'sample_count':len(reviews),
            'evidence_counts':dict(Counter(r['evidence']['evidence'] for r in reviews)),
            'disposition_counts':dict(Counter(r['disposition'] for r in reviews)),
            'semantic_counts':dict(Counter(r['semantic_support'] for r in reviews)),
            'owner_confirmed':sum(r.get('owner_confirmed',False) is True for r in reviews),
            'quality_gate_passed':False}


def suite_gate(expected_ids,runs,version,max_output_tokens):
    """Check comparable coverage and explicit reviews; never approve production."""
    expected=set(expected_ids)
    if len(expected)!=len(expected_ids) or not expected:
        raise ValueError('Expected case identifiers must be unique and nonempty')
    grouped={}
    for run in runs:grouped.setdefault(run.get('sample_index'),[]).append(run)
    reasons=[];missing=[];review_pending=[];failed=[];incomparable=[]
    for case in sorted(expected):
        items=grouped.get(case,[])
        if not items:missing.append(case);continue
        if len(items)!=1:failed.append(case);continue
        run=items[0]
        if run.get('version')!=version or run.get('max_output_tokens')!=max_output_tokens:
            incomparable.append(case);continue
        if run.get('error_type') or run.get('validation')!='passed':failed.append(case);continue
        review=run.get('review') or {}
        # Each dimension is an evaluator's explicit evidence-based judgment.
        dimensions=('semantic_support','speaker_attribution','time_handling','scope_handling','durable_value')
        if any(review.get(key) not in ('pass','fail') for key in dimensions):review_pending.append(case)
        elif any(review[key]=='fail' for key in dimensions):failed.append(case)
    unexpected=sorted(set(grouped)-expected,key=str)
    for key,value in [('missing_cases',missing),('incomparable_cases',incomparable),
                      ('review_pending_cases',review_pending),('failed_cases',failed),('unexpected_cases',unexpected)]:
        if value:reasons.append(key)
    return {'expected_count':len(expected),'observed_count':len(set(grouped)&expected),
            'version':version,'max_output_tokens':max_output_tokens,
            'missing_cases':missing,'incomparable_cases':incomparable,
            'review_pending_cases':review_pending,'failed_cases':failed,'unexpected_cases':unexpected,
            'blocking_reasons':reasons,'ready_for_owner_quality_decision':not reasons,
            'quality_approved':False,'production_dispatch_enabled':False}

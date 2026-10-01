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

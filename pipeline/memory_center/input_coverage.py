"""Source coverage accounting for offline evaluation; never quality approval.

Uses the same routing as extraction. Does not truncate, submit to a model, or
change sources. Counts Unicode characters, not provider tokens.
"""
import hashlib
from .core import Invalid
from .extraction_input import prepare_request


def audit_input_coverage(source_type, messages, *, version):
    if source_type not in ('conversation', 'document', 'imported_summary'):
        raise Invalid('Unsupported coverage source type')
    if not isinstance(messages, list) or not messages or len(messages) > 1000:
        raise Invalid('Invalid coverage messages')
    seen=set()
    for m in messages:
        if (not isinstance(m,dict) or not isinstance(m.get('id'),str)
                or not m['id'] or m['id'] in seen
                or m.get('role') not in ('user','assistant','external')
                or not isinstance(m.get('text'),str) or not m['text'].strip()
                or len(m['text']) > 1_000_000):
            raise Invalid('Invalid coverage message')
        seen.add(m['id'])
    _,spans,routes=prepare_request(source_type,messages,version=version)
    rows=[]
    for m in messages:
        text=m['text'];ranges=sorted((s['start'],s['end'],s['quote'])
            for s in spans.values() if s['message_id']==m['id'])
        covered=0;previous=0
        for start,end,quote in ranges:
            if start<previous or not 0<=start<end<=len(text) or text[start:end]!=quote:
                raise Invalid('Coverage span mismatch')
            covered+=end-start;previous=end
        reasons=[]
        if len(text)>20000:reasons.append('message_exceeds_ingest_limit')
        if covered<len(text):reasons.append('source_not_fully_in_evidence')
        rows.append({'message_id':m['id'],'role':m['role'],'characters':len(text),
            'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'evidence_characters':covered,'excluded_characters':len(text)-covered,
            'span_count':len(ranges),'route':routes[m['id']],
            'blocking_input_reasons':reasons})
    return {'audit_version':'input-coverage-v1','method_version':version,
        'items':rows,'total_characters':sum(r['characters']for r in rows),
        'evidence_characters':sum(r['evidence_characters']for r in rows),
        'input_ready_without_segmentation':len(messages)<=100 and all(r['characters']<=20000 for r in rows),
        'full_evidence_coverage':all(r['excluded_characters']==0 for r in rows),
        'model_calls':0,'quality_approved':False,
        'limitations':['Excluded text may contain valuable material; routing is not a semantic judgment.',
            'Full character coverage does not establish correct attribution or preserved conditions.',
            'Ingest-sized messages do not establish provider request token fit.']}

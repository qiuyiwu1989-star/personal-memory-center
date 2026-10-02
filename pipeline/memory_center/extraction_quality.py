"""Auditable review hints, not semantic verification or an adoption decision."""
import hashlib
import json
import re
from .modality import CONDITION, WISH, PLAN, evidence_ranges

QUALITY_POLICY_VERSION='extraction-quality-review-v1'
FACT_SIGNAL=re.compile(r'名叫|叫做|命名为|名称(?:为|是)|已(?:经)?(?:完成|部署|采用)|\b(?:named|called|completed|deployed)\b',re.I)
TASK_SIGNAL=re.compile(r'(?:请|帮我|麻烦|用户(?:请求|要求)|\b(?:please|requests?)\b).{0,24}(?:调研|比较|评估|总结|生成|整理|写一|画一|research|compare|evaluate|summarize|generate)',re.I)
ENDURING_SIGNAL=re.compile(r'长期|持续|每次|始终|必须|不得|禁止|约束|\b(?:always|ongoing|must|never)\b',re.I)


def _semantic(claim, source=None):
    """Strip only exact server source labels, never guessed project/title text."""
    statement=claim['statement']
    context=claim.get('evidence_context') or {}
    if not context and source:
        from .claim_context import evidence_context
        messages=json.loads(source['payload']) if isinstance(source.get('payload'),str) else source.get('messages',[])
        message=next((m for m in messages if m.get('id')==claim.get('message_id')),None)
        if message:context=evidence_context(message,source.get('source_type','conversation'))
    if isinstance(context,dict):
        date=context.get('source_date')
        title=context.get('conversation_title')
        prefix=('来源消息日期：'+date+'（非事件成立时间，当前有效性待核实）。') if isinstance(date,str) and date else ''
        if claim.get('topic')=='projects' and isinstance(title,str) and title:
            prefix+='来源对话：'+title+'。'
        if prefix and statement.startswith(prefix):return statement[len(prefix):]
    # Resolver output precedes core evidence_context. Remove its exact leading
    # labels with anchored bounds; do not strip summary/date attribution prose.
    statement=re.sub(r'^来源消息日期：\d{4}-\d{2}-\d{2}（非事件成立时间，当前有效性待核实）。','',statement)
    if statement.startswith('来源对话：'):
        title=claim.get('_source_title')
        if isinstance(title,str) and statement.startswith('来源对话：'+title+'。'):
            statement=statement[len('来源对话：'+title+'。'):]
    return statement


def _clauses(text):
    # Exact clause overlap only, not semantic similarity. Ignore punctuation
    # and outer whitespace at these narrow boundaries; preserve inner bytes.
    if CONDITION.search(text):return []
    return [part.strip().rstrip('。；;') for part in re.split(r'[。；;]',text)
            if len(part.strip().rstrip('。；;'))>=8]


def review(claims, source=None):
    """Return metadata-only diagnostics; never mutate input.

    Labels archive_only/review_required are suggestions for a later explicit
    governance decision. Candidate payloads and evidence remain unchanged.
    """
    if not isinstance(claims,list) or any(not isinstance(c,dict) or not isinstance(c.get('statement'),str) or not isinstance(c.get('quote'),str) for c in claims):
        raise ValueError('quality review requires resolved claims with statement and quote')
    items=[];seen={};previous=[]
    for index,claim in enumerate(claims):
        text=_semantic(claim,source);quote=claim['quote'];findings=[]
        def flag(code,explanation,**metadata):
            findings.append({'code':code,'explanation':explanation,'signal_only':True,**metadata})
        if CONDITION.search(quote) and not CONDITION.search(text):
            flag('condition_scope_review','证据含条件，陈述未检测到条件标记；需核对条件是否约束本条，不能仅凭词法认定遗漏。')
        if (WISH.search(text) or PLAN.search(text)) and FACT_SIGNAL.search(text):
            flag('mixed_statement_review','陈述同时含已述事实与意愿信号；需判断是否为两个命题，不能直接合并成一种模态。')
        ranges=evidence_ranges(text)
        if len(ranges)>1:
            flag('multiple_clause_review','陈述存在可独立分段的主体边界；需审查是否应拆分，边界本身不证明多个事实。',ranges=[list(r) for r in ranges[:6]])
        transient=bool(TASK_SIGNAL.search(text) and not ENDURING_SIGNAL.search(text))
        if transient:
            flag('transient_task_review','陈述像一次性处理请求，未检测到持续约束；建议只留档案，长期价值仍待核实。')
        key=tuple(json.dumps(claim.get(k),sort_keys=True) for k in ('topic','kind','subject','status'))+(text,)
        if key in seen:
            flag('exact_duplicate','同归属类型下存在逐字相同陈述；关联先前候选，不作近义去重。',duplicate_of=seen[key])
        else:seen[key]=index
        clauses=set(_clauses(text))
        for old_index,old_claim,old_clauses in previous:
            if all(claim.get(k)==old_claim.get(k) for k in ('topic','subject','status')):
                shared=clauses & old_clauses
                if shared and text!=_semantic(old_claim,source):
                    flag('exact_clause_overlap','候选间存在逐字共同片段；需核对重复与额外限定，不据此删除或拼接。',
                         related_index=old_index,clause_hashes=sorted(hashlib.sha256(s.encode()).hexdigest() for s in shared)[:3])
        previous.append((index,claim,clauses))
        disposition='archive_only' if transient else 'review_required' if findings else 'candidate'
        items.append({'claim_index':index,'disposition':disposition,'findings':findings[:6],
                      'codes':[f['code'] for f in findings[:6]],
                      'semantics_verified':False})
    return {'quality_policy_version':QUALITY_POLICY_VERSION,
        'quality_approved':False,'semantics_verified':False,
        'items':items,'total':len(items),
        'review_required':sum(i['disposition']=='review_required' for i in items),
        'archive_only':sum(i['disposition']=='archive_only' for i in items)}


def review_notes(result, claims):
    """Separate bounded display notes keyed by statements, not assessment data."""
    notes={}
    for item in result['items']:
        index=item['claim_index']
        if item['findings'] and 0<=index<len(claims):
            note='；'.join(f['explanation'] for f in item['findings'])[:400]
            statement=claims[index]['statement']
            if statement in notes and note not in notes[statement]:
                notes[statement]=(notes[statement]+'；'+note)[:400]
            else:notes[statement]=note
    return notes

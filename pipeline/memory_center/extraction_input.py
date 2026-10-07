"""Lossless source spans and conservative archive routing, without a model."""
import re
from .claim_context import contains_immediate_command
from .core import Invalid


def _visible_range(text):
    """Separate an outer request from a clearly pasted chapter/role template.

    This is source routing, never a claim that the template is false. All bytes
    remain in the archived source; only this extraction request is reduced.
    """
    role = re.search(r'(?:^|\n)(?:#{1,6}\s*)?(?:你是|你将扮演)', text)
    if role and len(text)-role.start()>400 and re.search(r'核心使命|角色设定|职责|工作流程',text[role.start():]):
        return role.start(), 'role_template'
    chapter = re.search(r'(?:^|\n|[。！？])\s*(?:#{1,6}\s*)?第[一二三四五六七八九十百\d]+章[:：]',text)
    if chapter and (len(text)-chapter.start()>400 or all(word in text[chapter.start():] for word in ('核心观点','内容架构','章末思考'))):
        return chapter.start(), 'pasted_chapter'
    if all(word in text for word in ('核心观点','内容架构','章末思考')):
        return 0, 'chapter_outline'
    specification=(len(text)>800 and (len(re.findall(r'^#{1,6}\s',text,re.M))>=3 or len(re.findall(r'^\d+\.',text,re.M))>=3) and
                   bool(re.search(r'核心使命|你是|你将扮演|角色设定',text)))
    return (0, 'role_template') if specification else (len(text), None)


def _configuration_hint(text):
    # Prioritization only: the model must still establish exact support. A
    # transient request next to a list does not erase a stated configuration.
    return bool(re.search(r'系统|工作台|架构|配置',text) and
                (re.search(r'(?:包含|组成|分为|设有|由).{0,24}(?:智能体|模块|agent)',text,re.I) or
                 (re.search(r'[一二三四五六七八九十\d]+[个种类大]?\s*(?:智能体|模块|agent)',text,re.I) and
                  len(re.findall(r'智能体|模块|agent',text,re.I))>=2)))


VISIBILITY_VALUES=frozenset(('unknown','visible_only','complete_visible'))


def source_visibility(source_metadata=None):
    """Project a declaration only; never infer coverage or authority from DATA.

    Legacy rows, malformed JSON and unsupported values fail conservatively to
    unknown. No reference dereference, content inspection or permission copying.
    """
    if isinstance(source_metadata,str):
        import json
        try:source_metadata=json.loads(source_metadata)
        except (ValueError,TypeError):source_metadata=None
    status=source_metadata.get('visibility') if isinstance(source_metadata,dict) else None
    if not isinstance(status,str) or status not in VISIBILITY_VALUES:status='unknown'
    return {'status':status,'declaration_only':True,'attachments_verified':False}


def prepare_request(source_type,messages,*,version=None,source_metadata=None):
    prepared=[];spans={};routes={}
    for index,message in enumerate(messages):
        text=message['text']
        end_of_evidence,reference_reason=_visible_range(text)
        assistant_reference=source_type=='conversation' and message['role']=='assistant'
        if assistant_reference:
            end_of_evidence=0;route='assistant_reference'
        elif reference_reason:
            route='mixed_reference_document' if text[:end_of_evidence].strip() else 'reference_document'
        else:route='conversation'
        routes[message['id']]=route
        pieces=[]
        if end_of_evidence and not assistant_reference:
            start=0
            # Strip only a leading immediate command clause, preserving all
            # remaining constraints and list context byte-for-byte.
            prefix=re.match(r'[^，。\n]+[，。\n]',text[:end_of_evidence])
            if prefix and contains_immediate_command(prefix.group()):start=prefix.end()
            for match in re.finditer(r'.+?(?:\n\s*\n|$)',text[start:end_of_evidence],re.S):
                body=match.group();offset=start+match.start();part=0
                if version in ('2026-10-01.14','2026-10-02.15','2026-10-02.16','2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22'):
                    from .modality import evidence_ranges,evidence_modality
                    if version in ('2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22'):
                        from .modality import scoped_evidence_ranges
                        if version in ('2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22'):
                            from .modality import scoped_evidence_ranges_v19
                            if version == '2026-10-04.22':
                                from .modality import scoped_evidence_ranges_v22
                                ranges=scoped_evidence_ranges_v22(body)
                            else:ranges=scoped_evidence_ranges_v19(body)
                        else:ranges=scoped_evidence_ranges(body)
                    else:ranges=evidence_ranges(body)
                else:ranges=[(0,len(body))]
                while part<len(body):
                    atom_end=next(end for begin,end in ranges if begin<=part<end)
                    end=min(atom_end,part+1000)
                    if end<atom_end:
                        boundary=max(body.rfind('。',part,end),body.rfind('\n',part,end))
                        if boundary>part+300:end=boundary+1
                    quote=body[part:end];sid=f'e{index}-{offset+part}'
                    part=end
                    if not quote.strip():continue
                    if quote.strip().strip('。.!！') in ('继续','好的','好','yes','ok','continue'):continue
                    if source_type=='imported_summary' and re.search(r'SKILL\.md.*\d+\s*lines',quote):continue
                    spans[sid]={'message_id':message['id'],'quote':quote,'start':offset+end-len(quote),'end':offset+end,'_source_title':message.get('source_title'),'_source_type':source_type,'_created_at':message.get('created_at')}
                    if version in ('2026-10-01.14','2026-10-02.15','2026-10-02.16','2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22'):spans[sid]['_modality']=evidence_modality(quote)
                    pieces.append({'evidence_id':sid,'text':quote,
                                   'priority_hint':'explicit_configuration' if _configuration_hint(quote) else 'ordinary'})
                    if version in ('2026-10-01.14','2026-10-02.15','2026-10-02.16','2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22'):pieces[-1]['modality_hint']=spans[sid]['_modality']
        prepared.append({'id':message['id'],'role':message['role'],'source_title':message.get('source_title'),
                         'created_at':message.get('created_at'),'route':route,'reference_reason':reference_reason,
                         'evidence_spans':pieces})
    request={'source_type':source_type,'messages':prepared}
    if version in ('2026-10-02.16','2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22'):request['source_visibility']=source_visibility(source_metadata)
    return request,spans,routes


def resolve_plan(plan,spans,*,version=None):
    if not isinstance(plan,dict) or not isinstance(plan.get('claims'),list):raise Invalid('模型输出不符合 claims 协议')
    resolved=[]
    for claim in plan['claims']:
        if not isinstance(claim,dict) or claim.get('evidence_id') not in spans:raise Invalid('模型选择了不存在的证据片段')
        evidence=spans[claim['evidence_id']]
        # Do not allow an independently supplied conflicting locator or quote.
        if ('message_id' in claim and claim['message_id']!=evidence['message_id']) or ('quote' in claim and claim['quote']!=evidence['quote']):
            raise Invalid('证据定位与所选片段冲突')
        attached = claim | {k:v for k,v in evidence.items() if not k.startswith('_')}
        if version in ('2026-10-03.21','2026-10-04.22'):
            from .qualifications import qualification_problem
            if not isinstance(claim.get('statement'), str):
                raise Invalid('模型陈述必须为文本')
            problem = qualification_problem(evidence['quote'], claim['statement'], claim.get('kind'))
            if problem: raise Invalid(problem)
        if version in ('2026-10-01.14','2026-10-02.15','2026-10-02.16','2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22'):
            from .modality import evidence_modality,modality_problem
            if not isinstance(claim.get('statement'),str):raise Invalid('模型陈述必须为文本')
            problem=modality_problem(evidence['quote'],claim['statement'],claim.get('kind'))
            if problem:raise Invalid(problem)
            attached['modality']=evidence_modality(evidence['quote'])
        # Source scope is metadata, not an inferred project name or proof of
        # the claim. Legacy methods are unchanged; v12 adds an explicit label.
        title = evidence.get('_source_title')
        if version in ('2026-10-01.12','2026-10-01.13','2026-10-01.14','2026-10-02.15','2026-10-02.16','2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22') and claim.get('topic')=='projects' and evidence.get('_source_type')!='imported_summary' and isinstance(title,str) and title and isinstance(claim.get('statement'),str):
            attached['statement'] = '来源对话：'+title+'。'+claim['statement']
        if version in ('2026-10-01.13','2026-10-01.14','2026-10-02.15','2026-10-02.16','2026-10-03.17','2026-10-03.18','2026-10-03.19','2026-10-03.20','2026-10-03.21','2026-10-04.22') and evidence.get('_source_type')!='imported_summary' and isinstance(attached.get('statement'),str):
            from .claim_context import evidence_context
            date = evidence_context({'created_at':evidence.get('_created_at')},evidence.get('_source_type'))['source_date']
            if date:
                attached['statement'] = '来源消息日期：'+date+'（非事件成立时间，当前有效性待核实）。'+attached['statement']
        resolved.append(attached)
    return {'claims':resolved}

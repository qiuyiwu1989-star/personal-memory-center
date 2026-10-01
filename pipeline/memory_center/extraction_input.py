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


def prepare_request(source_type,messages):
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
                while part<len(body):
                    end=min(len(body),part+1000)
                    if end<len(body):
                        boundary=max(body.rfind('。',part,end),body.rfind('\n',part,end))
                        if boundary>part+300:end=boundary+1
                    quote=body[part:end];sid=f'e{index}-{offset+part}'
                    part=end
                    if not quote.strip():continue
                    if quote.strip().strip('。.!！') in ('继续','好的','好','yes','ok','continue'):continue
                    if source_type=='imported_summary' and re.search(r'SKILL\.md.*\d+\s*lines',quote):continue
                    spans[sid]={'message_id':message['id'],'quote':quote,'start':offset+end-len(quote),'end':offset+end}
                    pieces.append({'evidence_id':sid,'text':quote,
                                   'priority_hint':'explicit_configuration' if _configuration_hint(quote) else 'ordinary'})
        prepared.append({'id':message['id'],'role':message['role'],'source_title':message.get('source_title'),
                         'created_at':message.get('created_at'),'route':route,'reference_reason':reference_reason,
                         'evidence_spans':pieces})
    return {'source_type':source_type,'messages':prepared},spans,routes


def resolve_plan(plan,spans):
    if not isinstance(plan,dict) or not isinstance(plan.get('claims'),list):raise Invalid('模型输出不符合 claims 协议')
    resolved=[]
    for claim in plan['claims']:
        if not isinstance(claim,dict) or claim.get('evidence_id') not in spans:raise Invalid('模型选择了不存在的证据片段')
        evidence=spans[claim['evidence_id']]
        # Do not allow an independently supplied conflicting locator or quote.
        if ('message_id' in claim and claim['message_id']!=evidence['message_id']) or ('quote' in claim and claim['quote']!=evidence['quote']):
            raise Invalid('证据定位与所选片段冲突')
        resolved.append(claim | evidence)
    return {'claims':resolved}

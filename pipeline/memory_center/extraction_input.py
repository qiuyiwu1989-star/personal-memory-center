"""Lossless source spans and conservative archive routing, without a model."""
import re
from .claim_context import contains_immediate_command
from .core import Invalid


def prepare_request(source_type,messages):
    prepared=[];spans={};routes={}
    for index,message in enumerate(messages):
        text=message['text']
        # Whole pasted role specifications/outlines are reference documents.
        specification=(len(text)>800 and (len(re.findall(r'^#{1,6}\s',text,re.M))>=3 or len(re.findall(r'^\d+\.',text,re.M))>=3) and
                       bool(re.search(r'核心使命|你是|你将扮演|角色设定',text)))
        outline=all(word in text for word in ('核心观点','内容架构','章末思考'))
        route='reference_document' if specification or outline else 'conversation'
        routes[message['id']]=route
        pieces=[]
        if route=='conversation':
            start=0
            # Strip only a leading immediate command clause, preserving all
            # remaining constraints and list context byte-for-byte.
            prefix=re.match(r'[^，。\n]+[，。\n]',text)
            if prefix and contains_immediate_command(prefix.group()):start=prefix.end()
            for match in re.finditer(r'.+?(?:\n\s*\n|$)',text[start:],re.S):
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
                    pieces.append({'evidence_id':sid,'text':quote})
        prepared.append({'id':message['id'],'role':message['role'],'source_title':message.get('source_title'),
                         'created_at':message.get('created_at'),'route':route,'evidence_spans':pieces})
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

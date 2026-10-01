"""No-model, preview-only conversation plan for a new visible-text parser.

A preview is not an extraction batch. It never resumes jobs or applies memories.
"""
from collections import Counter
import hashlib
from .claude import PARSER_VERSION,visible_blocks
from .bulk import _segments
from .core import Invalid,encoded


def preview(conversations,previous=()):
    if not isinstance(conversations,list): raise Invalid('对话归档需为列表')
    seen=set();rows=[];plans=[];blocks=Counter();old_by_conversation={}
    for segment in previous:
        old_by_conversation.setdefault(segment['conversation_id'],[]).append(segment)
    for conversation in conversations:
        cid=conversation.get('uuid') if isinstance(conversation,dict) else None
        if not isinstance(cid,str) or not cid or cid in seen:raise Invalid('对话标识缺失或重复')
        seen.add(cid);segments=list(_segments(conversation))
        flattened_chars=visible_chars=0
        for raw in conversation.get('chat_messages') or []:
            if not isinstance(raw,dict):continue
            body=raw.get('text');flattened_chars+=len(body) if isinstance(body,str) else 0
            visible_chars+=sum(len(text) for _,text in visible_blocks(raw))
            for block in raw.get('content') or []:
                if isinstance(block,dict):blocks[block.get('type','unknown')]+=1
        old=old_by_conversation.get(cid,[])
        hashes=[]
        for index,messages in enumerate(segments):
            digest=hashlib.sha256(encoded(messages).encode()).hexdigest();hashes.append(digest)
            plans.append({'conversation_id':cid,'segment_index':index,'parser_version':PARSER_VERSION,
                          'digest':digest,'messages':messages})
        rows.append({'conversation_id':cid,'old_segments':len(old),'new_segments':len(segments),
                     'old_states':dict(Counter(s['state'] for s in old)),
                     'flattened_chars':flattened_chars,'visible_chars':visible_chars,
                     'payload_changed':bool(old) and [s.get('digest') for s in sorted(old,key=lambda s:s['segment_index'])]!=hashes})
    unmatched=sorted(set(old_by_conversation)-seen)
    return {'parser_version':PARSER_VERSION,'policy':'preview-only-no-model-no-dispatch-no-writeback',
            'summary':{'conversations':len(rows),'old_conversation_segments':sum(r['old_segments'] for r in rows),
                       'new_conversation_segments':len(plans),'no_visible_text_conversations':sum(r['new_segments']==0 for r in rows),
                       'flattened_chars':sum(r['flattened_chars'] for r in rows),'visible_chars':sum(r['visible_chars'] for r in rows),
                       'excluded_block_types':dict((k,v) for k,v in blocks.items() if k!='text'),
                       'changed_conversations':sum(r['payload_changed'] for r in rows),'unmatched_previous_conversations':len(unmatched)},
            'conversation_changes':rows,'planned_segments':plans,'unmatched_previous_conversations':unmatched}

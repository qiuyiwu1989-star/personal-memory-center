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


PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_replans(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, batch_id TEXT NOT NULL,
 scope TEXT NOT NULL, archive_digest TEXT NOT NULL, parser_version TEXT NOT NULL,
 payload TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, adopted REAL);
"""


class Replans:
    """Immutable plans; adoption selects an input version, never dispatches jobs."""
    def __init__(self,store):
        self.store=store
        with store.db() as db:db.executescript(PLAN_SCHEMA)

    def _batch(self,principal,batch_id):
        from .core import permit
        with self.store.db() as db:
            row=db.execute('SELECT * FROM bulk_batches WHERE id=? AND owner=?',
                           (batch_id,principal['owner'])).fetchone()
        if not row:raise Invalid('未找到提炼批次')
        permit(principal,row['scope'],'read')
        if not principal.get('trusted_user'):raise PermissionError('仅本人可管理重规划')
        return dict(row)

    def create(self,principal,batch_id):
        import json,time
        from .bulk import _source_file
        from .core import permit
        batch=self._batch(principal,batch_id);permit(principal,batch['scope'],'write')
        path=_source_file(self.store,batch['source_batch'],principal['owner'],'conversations.json')
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        with self.store.db() as db:
            old=[dict(r) for r in db.execute("SELECT conversation_id,segment_index,state,payload FROM bulk_segments WHERE batch_id=? AND source_type='conversation'",(batch_id,))]
            evidence=[dict(r) for r in db.execute("SELECT r.id,r.message_id,r.quote,s.conversation_id FROM records r JOIN sources o ON o.id=r.source_id JOIN bulk_segments s ON s.source_key=o.source_key AND s.batch_id=? WHERE r.owner=? AND r.scope=? AND s.source_type='conversation'",(batch_id,principal['owner'],batch['scope']))]
        for row in old:row['digest']=hashlib.sha256(row.pop('payload').encode()).hexdigest()
        result=preview(json.loads(raw),old)
        result['evidence_mappings']=map_evidence(evidence,result['planned_segments'])
        result['summary']['evidence_states']=dict(Counter(r['state'] for r in result['evidence_mappings']))
        plan_id=hashlib.sha256(encoded([principal['owner'],batch_id,digest,PARSER_VERSION]).encode()).hexdigest()
        with self.store.db() as db:
            db.execute('INSERT INTO archive_replans VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                       (plan_id,principal['owner'],batch_id,batch['scope'],digest,PARSER_VERSION,encoded(result),'preview',time.time(),None))
        return self.get(principal,batch_id)

    def get(self,principal,batch_id,offset=0):
        import json
        self._batch(principal,batch_id)
        if type(offset) is not int or offset<0:raise Invalid('分页位置无效')
        with self.store.db() as db:
            row=db.execute('SELECT * FROM archive_replans WHERE owner=? AND batch_id=? ORDER BY created DESC,id DESC LIMIT 1',(principal['owner'],batch_id)).fetchone()
        if not row:return {'plan':None}
        data=json.loads(row['payload'])
        return {'plan':{'id':row['id'],'state':row['state'],'parser_version':row['parser_version'],
                'summary':data['summary'],'dispatch_enabled':False,
                'conversation_changes':data['conversation_changes'][offset:offset+25],
                'evidence_mappings':data['evidence_mappings'][offset:offset+25],
                'offset':offset,'adopted':row['adopted']}}

    def adopt(self,principal,batch_id,plan_id):
        import time
        from .bulk import _source_file
        from .core import permit
        batch=self._batch(principal,batch_id);permit(principal,batch['scope'],'write')
        path=_source_file(self.store,batch['source_batch'],principal['owner'],'conversations.json')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM archive_replans WHERE id=? AND owner=? AND batch_id=?',(plan_id,principal['owner'],batch_id)).fetchone()
            if not row or row['parser_version']!=PARSER_VERSION or row['archive_digest']!=digest:raise Invalid('规划已过时，请重新生成预览')
            db.execute("UPDATE archive_replans SET state='adopted_waiting_quality',adopted=? WHERE id=? AND state='preview'",(time.time(),plan_id))
        return self.get(principal,batch_id)


def map_evidence(records,segments):
    """Exact locator + quotation only. Mapping does not validate a judgment."""
    by_conversation={}
    for segment in segments:
        by_conversation.setdefault(segment['conversation_id'],[]).extend(segment['messages'])
    result=[]
    for record in records:
        original=record['message_id'].split('#',1)[0]
        matches=[m['id'] for m in by_conversation.get(record['conversation_id'],[])
                 if m['id'].split('#',1)[0]==original and record['quote'] and record['quote'] in m['text']]
        result.append({'record_id':record['id'],'old_message_id':record['message_id'],
                       'new_message_ids':matches,'state':'mapped' if len(matches)==1 else 'ambiguous' if matches else 'unresolved'})
    return result

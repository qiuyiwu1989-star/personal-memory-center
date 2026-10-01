"""Explicit current-parser bulk projection to archive-only readable sources.

Default dry-run. No model, budget change, bulk state mutation or fact upgrade.
"""
import hashlib
import json
import re
from .claude import PARSER_VERSION
from .core import Invalid, encoded, permit

_ALLOWED_MESSAGE_KEYS = {'id','role','text','source_title','created_at'}
_EXCLUDED_TAG = re.compile(r'<\s*(?:thinking|think|analysis|tool_use|tool_result)(?:[\s>])',re.I)
_INTERNAL_PRINCIPAL = 'archive-readable-import-v1'


def _body(batch, segment):
    if segment['source_type'] not in ('conversation','imported_summary'):
        raise Invalid('可读归档仅接受对话或导入摘要')
    try:
        messages=json.loads(segment['payload'])
    except (TypeError,ValueError):
        raise Invalid('可读归档消息投影无效') from None
    if not isinstance(messages,list) or not 1 <= len(messages) <= 100:
        raise Invalid('可读归档消息投影无效')
    ids=set()
    for message in messages:
        if not isinstance(message,dict) or set(message)-_ALLOWED_MESSAGE_KEYS:
            raise Invalid('无法证明消息是可见正文投影')
        if message.get('role') not in ('user','assistant','external'):
            raise Invalid('无法证明消息角色是可见正文角色')
        mid=message.get('id');text=message.get('text')
        if not isinstance(mid,str) or not 1 <= len(mid) <= 100 or mid in ids:
            raise Invalid('可读归档消息标识无效')
        ids.add(mid)
        if not isinstance(text,str) or not text.strip() or _EXCLUDED_TAG.search(text):
            raise Invalid('无法证明消息是排除 thinking/tool 的可见正文')
        for key in ('source_title','created_at'):
            if key in message and (not isinstance(message[key],str) or len(message[key])>300):
                raise Invalid('可读归档消息元信息无效')
    if len(encoded(messages))>24000:
        raise Invalid('可读归档分段超过安全上限')
    key='claude:readable:'+hashlib.sha256(encoded([batch['owner'],batch['scope'],batch['id'],segment['id'],segment['source_key']]).encode()).hexdigest()
    metadata={'parser_version':PARSER_VERSION,'parent_source_key':segment['source_key'],
              'original_ref':'archive://'+batch['source_batch']+'/'+segment['conversation_id'],
              'locator':encoded({'bulk_batch_id':batch['id'],'segment_id':segment['id'],
                                 'conversation_id':segment['conversation_id'],'segment_index':segment['segment_index']})}
    if batch.get('_archive_digest'):
        metadata['locator']=encoded({'archive_batch_id':batch['source_batch'],
            'archive_file':'conversations.json','archive_sha256':batch['_archive_digest'],
            'conversation_id':segment['conversation_id'],'segment_index':segment['segment_index'],
            'segment_id':segment['id']})
    if any(not isinstance(v,str) or len(v)>1000 for v in metadata.values()):
        raise Invalid('可读归档关联元信息过长')
    body={'scope':batch['scope'],'source_key':key,'source_type':segment['source_type'],
          'messages':messages,'processing_policy':'archive','source_metadata':metadata}
    digest=hashlib.sha256((segment['source_type']+encoded(messages)+encoded(metadata)).encode()).hexdigest()
    return body,digest


def import_batch(store, principal, scope, batch_id, dry_run=True):
    """Preview or explicitly import a marked visible batch; never dispatch it."""
    permit(principal,scope,'read');permit(principal,scope,'source_read');permit(principal,scope,'write')
    if not isinstance(principal.get('owner'),str) or not principal['owner']:
        raise Invalid('可读归档需要明确 owner')
    if not isinstance(batch_id,str) or not 1 <= len(batch_id) <= 300 or type(dry_run) is not bool:
        raise Invalid('可读归档参数无效')
    with store.db() as db:
        batch=db.execute('SELECT * FROM bulk_batches WHERE id=? AND owner=? AND scope=?',
                         (batch_id,principal['owner'],scope)).fetchone()
        if not batch:raise Invalid('归档批次不存在或不可访问')
        marker=db.execute('SELECT parser_version FROM bulk_batch_parsers WHERE batch_id=?',(batch_id,)).fetchone()
        if not marker or marker['parser_version']!=PARSER_VERSION:
            raise Invalid('归档批次不是当前可见正文 parser_version；仅保留原件，不导入旧投影')
        batch=dict(batch)
        segments=[dict(row) for row in db.execute('SELECT * FROM bulk_segments WHERE batch_id=? ORDER BY conversation_id,segment_index,id',(batch_id,))]
        existing={(row['source_key'],row['digest']) for row in db.execute(
            'SELECT source_key,digest FROM sources WHERE owner=? AND scope=? AND principal=?',
            (principal['owner'],scope,_INTERNAL_PRINCIPAL))}
    # Validate the whole plan before the first write. A crash may leave some
    # archive-only sources; repeating import safely completes the remainder.
    prepared=[(segment,*_body(batch,segment)) for segment in segments]
    return _apply(store,principal,batch,prepared,existing,dry_run)


def _apply(store,principal,batch,prepared,existing,dry_run):
    scope=batch['scope']
    internal={'id':_INTERNAL_PRINCIPAL,'owner':principal['owner'],'scopes':[scope],
              'actions':[a for a in ('read','source_read','write') if a in principal['actions']],
              'trusted_user':False}
    result={'dry_run':dry_run,'batch_id':batch['id'],'parser_version':PARSER_VERSION,'segments':len(prepared),
            'conversations':len({segment['conversation_id'] for segment,_,_ in prepared if segment['source_type']=='conversation'}),
            'summary_materials':len({segment['conversation_id'] for segment,_,_ in prepared if segment['source_type']=='imported_summary'}),
            'messages':sum(len(body['messages']) for _,body,_ in prepared),
            'visible_chars':sum(len(m['text']) for _,body,_ in prepared for m in body['messages']),
            'new_sources':0,'duplicates':0,'imported_sources':0,'model_calls':0,'extraction_tokens':0,
            'bulk_state_changed':False,'facts_confirmed':False,'policy':'archive-only'}
    for segment,body,digest in prepared:
        duplicate=(body['source_key'],digest) in existing
        result['duplicates' if duplicate else 'new_sources']+=1
        if not dry_run:
            imported=store.ingest(internal,body)
            if not imported['duplicate']:result['imported_sources']+=1
        existing.add((body['source_key'],digest))
    return result


def import_archive(store,principal,scope,archive_batch_id,dry_run=True):
    """Independently parse a verified archive snapshot; ignore old bulk plans.

    Narrower than the general Claude parser: flattened-only messages lack
    structured visibility proof and are rejected, never copied by fallback.
    """
    from .bulk import _source_file
    from .replan import preview
    permit(principal,scope,'read');permit(principal,scope,'source_read');permit(principal,scope,'write')
    permit(principal,'claude:archive','read');permit(principal,'claude:archive','source_read')
    if (not isinstance(principal.get('owner'),str) or not principal['owner'] or type(dry_run) is not bool
            or not isinstance(archive_batch_id,str) or not re.fullmatch(r'[0-9a-f]{64}',archive_batch_id)):
        raise Invalid('可读归档参数或 owner 无效')
    path=_source_file(store,archive_batch_id,principal['owner'],'conversations.json')
    with store.db() as db:
        catalog=db.execute("SELECT f.sha256 FROM archive_files f JOIN archive_batches b ON b.id=f.batch_id "
                           "WHERE b.id=? AND b.owner_id=? AND b.status='archived_verified' AND f.path=?",
                           (archive_batch_id,principal['owner'],'conversations.json')).fetchone()
        existing={(row['source_key'],row['digest']) for row in db.execute(
            'SELECT source_key,digest FROM sources WHERE owner=? AND scope=? AND principal=?',
            (principal['owner'],scope,_INTERNAL_PRINCIPAL))}
    if not catalog:raise Invalid('已核验原归档不存在或不可访问')
    raw=path.read_bytes();archive_digest=hashlib.sha256(raw).hexdigest()
    if archive_digest!=catalog['sha256']:raise Invalid('读取时原归档哈希变化，拒绝导入')
    try:
        conversations=json.loads(raw)
    except (ValueError,UnicodeError):
        raise Invalid('对话归档不是有效 JSON') from None
    if not isinstance(conversations,list):raise Invalid('对话归档需为列表')
    for conversation in conversations:
        if not isinstance(conversation,dict):raise Invalid('对话归档结构无效')
        for message in conversation.get('chat_messages') or []:
            if isinstance(message,dict) and 'content' not in message and isinstance(message.get('text'),str) and message['text'].strip():
                raise Invalid('仅有 flattened text，无法证明排除了 thinking/tool；拒绝导入')
    plan=preview(conversations)
    batch={'id':'archive-readable:'+archive_batch_id,'owner':principal['owner'],
           'scope':scope,'source_batch':archive_batch_id,'_archive_digest':archive_digest}
    segments=[]
    for item in plan['planned_segments']:
        if item['parser_version']!=PARSER_VERSION:raise Invalid('归档可见投影 parser 版本变化')
        source_key='archive:'+archive_batch_id+':'+item['conversation_id']+':part:'+str(item['segment_index'])
        segment={'id':hashlib.sha256(source_key.encode()).hexdigest(),
                 'conversation_id':item['conversation_id'],'segment_index':item['segment_index'],
                 'source_key':source_key,'source_type':'conversation','payload':encoded(item['messages'])}
        segments.append(segment)
    prepared=[(segment,*_body(batch,segment)) for segment in segments]
    def verify_unchanged():
        verified=_source_file(store,archive_batch_id,principal['owner'],'conversations.json')
        if hashlib.sha256(verified.read_bytes()).hexdigest()!=archive_digest:
            raise Invalid('原归档哈希在处理中变化，拒绝继续')
    verify_unchanged()
    result=_apply(store,principal,batch,prepared,existing,dry_run)
    verify_unchanged()
    result.update(archive_batch_id=archive_batch_id,archive_sha256=archive_digest,
                  coverage='conversations.json-only',total_archive_conversations=plan['summary']['conversations'],
                  no_visible_text_conversations=plan['summary']['no_visible_text_conversations'])
    return result

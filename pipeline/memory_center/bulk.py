"""Resumable, metered Claude archive planning and bounded dispatch."""
import hashlib
import json
import re
import os
import time
from pathlib import Path
from .core import Invalid, encoded, permit
from .budget import scoped_spent

SCOPE = os.environ.get('QIU_MEMORY_HISTORY_SCOPE','claude:history')
RESERVE_TOKENS = 35000  # 24k source chars + 4k output tokens + prompt, rounded upward.
TOPICS = ('profile', 'preferences', 'people', 'areas', 'projects', 'topics')


def setup(store):
    with store.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS bulk_batches(
          id TEXT PRIMARY KEY, owner TEXT NOT NULL, source_batch TEXT NOT NULL,
          scope TEXT NOT NULL, state TEXT NOT NULL, token_limit INTEGER NOT NULL,
          tokens_spent INTEGER NOT NULL DEFAULT 0, total_segments INTEGER NOT NULL,
          sampled_segments INTEGER NOT NULL, total_conversations INTEGER NOT NULL,
          no_text_conversations INTEGER NOT NULL, memory_documents INTEGER NOT NULL,
          created REAL NOT NULL,
          UNIQUE(owner,source_batch));
        CREATE TABLE IF NOT EXISTS bulk_segments(
          id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
          segment_index INTEGER NOT NULL, source_key TEXT NOT NULL,
          payload TEXT NOT NULL, source_type TEXT NOT NULL, phase TEXT NOT NULL, state TEXT NOT NULL,
          job_id TEXT, attempts_counted INTEGER NOT NULL DEFAULT 0,
          reserved_attempts INTEGER NOT NULL DEFAULT 0,
          reserved_tokens INTEGER NOT NULL DEFAULT 0,
          spent_tokens INTEGER NOT NULL DEFAULT 0,
          error TEXT, created REAL NOT NULL,
          UNIQUE(batch_id,conversation_id,segment_index));
        CREATE INDEX IF NOT EXISTS bulk_segments_order ON bulk_segments(batch_id,phase,state,created);
        ''')


def _messages(conversation):
    title = str(conversation.get('name') or '未命名对话')[:120]
    for index, raw in enumerate(conversation.get('chat_messages') or []):
        if not isinstance(raw, dict):
            continue
        body = raw.get('text')
        if not isinstance(body, str) or not body.strip():
            continue
        role = {'human':'user', 'assistant':'assistant'}.get(raw.get('sender'), 'external')
        original_id = str(raw.get('uuid') or ('message-'+str(index)))[:75]
        date = str(raw.get('created_at') or '')[:80]
        # Long messages remain addressable by original id plus an explicit part suffix.
        for part, start in enumerate(range(0, len(body), 12000)):
            text = body[start:start+12000]
            if not text.strip():
                continue
            yield {'id':original_id+'#'+str(part), 'role':role, 'text':text,
                   'source_title':title, 'created_at':date}


def _segments(conversation):
    group = []
    for message in _messages(conversation):
        candidate = group + [message]
        if group and (len(candidate)>100 or len(encoded(candidate))>20000):
            yield group
            group = []
        group.append(message)
        if len(encoded(group))>24000:
            raise Invalid('单条原话超出分段上限')
    if group:
        yield group


def _source_file(store, batch_id, owner, relative_path):
    if not re.fullmatch(r'[0-9a-f]{64}', batch_id):
        raise Invalid('归档批次标识无效')
    with store.db() as db:
        row = db.execute('SELECT b.id,f.sha256,f.bytes FROM archive_batches b JOIN archive_files f ON f.batch_id=b.id '
                         "WHERE b.id=? AND b.owner_id=? AND b.status='archived_verified' AND f.path=?",
                         (batch_id,owner,relative_path)).fetchone()
    if not row:
        raise Invalid('未找到已验证的对话归档')
    path = store.directory/'archives'/batch_id/relative_path
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=row['bytes']:
        raise Invalid('服务器缺少已校验的归档读取副本')
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    if h.hexdigest()!=row['sha256']:
        raise Invalid('归档读取副本校验失败')
    return path


class Bulk:
    def __init__(self, store):
        self.store=store
        setup(store)

    def create(self, principal, batch_id, token_limit=1_000_000):
        permit(principal,'claude:archive','read')
        permit(principal,SCOPE,'write')
        if not principal.get('trusted_user'):
            raise PermissionError('仅本人可启动全量提炼')
        if type(token_limit) is not int or not 100_000<=token_limit<=10_000_000:
            raise Invalid('模型上限须为 10 万至 1000 万 tokens')
        with self.store.db() as db:
            old=db.execute('SELECT id FROM bulk_batches WHERE owner=? AND source_batch=?', (principal['owner'],batch_id)).fetchone()
        if old:
            return self.status(principal,old['id'])
        path=_source_file(self.store,batch_id,principal['owner'],'conversations.json')
        conversations=json.loads(path.read_text())
        if not isinstance(conversations,list):
            raise Invalid('归档对话格式无效')
        seen=set(); planned=[]; no_text=0
        for c in conversations:
            if not isinstance(c,dict) or not isinstance(c.get('uuid'),str) or c['uuid'] in seen:
                raise Invalid('对话标识缺失或重复')
            seen.add(c['uuid'])
            segments=list(_segments(c))
            if not segments:no_text+=1
            for index,messages in enumerate(segments):
                key='claude:archive:'+batch_id+':'+c['uuid']+':part:'+str(index)
                planned.append((c['uuid'],index,key,encoded(messages),str(c.get('created_at') or ''),'conversation'))
        with self.store.db() as db:
            expected=db.execute('SELECT count(*) AS n FROM archive_conversations WHERE batch_id=?',(batch_id,)).fetchone()['n']
            memory_paths=[r['path'] for r in db.execute("SELECT path FROM archive_files WHERE batch_id=? AND path LIKE ?",(batch_id,"memories/%.json"))]
        if len(seen)!=expected:
            raise Invalid('归档对话目录数量不一致')
        memory_documents=0
        for relative in memory_paths:
            memory=json.loads(_source_file(self.store,batch_id,principal['owner'],relative).read_text())
            items=[]
            if memory.get('conversations_memory'):
                items.append(('global-summary',memory['conversations_memory'],''))
            for file in memory.get('memory_files',[]):
                items.append(('file:'+str(file['path']),file['content'],str(file.get('updated_at') or '')))
            for key,value in memory.get('project_memories',{}).items():
                items.append(('project:'+key,value if isinstance(value,str) else encoded(value),''))
            for key,text,date in items:
                if not isinstance(text,str) or not text.strip():continue
                memory_documents+=1
                item_id='memory:'+hashlib.sha256((relative+key).encode()).hexdigest()[:24]
                for index,start in enumerate(range(0,len(text),12000)):
                    message={'id':item_id+'#'+str(index),'role':'external','text':text[start:start+12000],
                             'source_title':key[:120], 'created_at':date[:80]}
                    source_key='claude:archive:'+batch_id+':'+item_id+':part:'+str(index)
                    planned.append((item_id,index,source_key,encoded([message]),'', 'imported_summary'))
        # Sample ten conversations across the archive timeline; one segment each.
        eligible=sorted({(date,cid) for cid,_,_,_,date,kind in planned if kind=='conversation'})
        sampled=set()
        if eligible:
            for i in range(min(10,len(eligible))):
                sampled.add(eligible[round(i*(len(eligible)-1)/max(1,min(10,len(eligible))-1))][1])
        batch='claude-'+batch_id[:24]
        first_sample=set()
        rows=[]
        for cid,index,key,payload,date,kind in planned:
            phase='sample' if cid in sampled and cid not in first_sample else 'summary' if kind=='imported_summary' else 'remaining'
            if phase=='sample':first_sample.add(cid)
            rows.append((hashlib.sha256(key.encode()).hexdigest()[:32],batch,cid,index,key,payload,kind,phase,'planned',None,0,0,0,0,None,time.time()))
        from .documents import setup as documents_setup
        documents_setup(self.store)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT id FROM bulk_batches WHERE owner=? AND source_batch=?',(principal['owner'],batch_id)).fetchone()
            if old:
                return self.status(principal,old['id'])
            db.execute('INSERT INTO bulk_batches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (batch,principal['owner'],batch_id,SCOPE,'running',token_limit,0,len(rows),len(first_sample),
                        len(seen),no_text,memory_documents,time.time()))
            for row in rows:
                db.execute('INSERT INTO bulk_segments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',row)
            # Six category documents replace thousands of per-segment files.
            for topic in TOPICS:
                db.execute('INSERT INTO document_topics VALUES(?,?,?,?,?) ON CONFLICT(owner,scope,slug) DO NOTHING',
                           (principal['owner'],SCOPE,'history-'+topic,
                            {'profile':'个人','preferences':'偏好','people':'人物','areas':'领域','projects':'项目','topics':'主题'}[topic]+' · Claude 历史',
                            encoded(['claude:archive:'+batch_id+':'])))
        return self.status(principal,batch)

    def status(self,principal,batch_id):
        permit(principal,'claude:archive','read')
        with self.store.db() as db:
            batch=db.execute('SELECT * FROM bulk_batches WHERE id=? AND owner=?',(batch_id,principal['owner'])).fetchone()
            if not batch:
                raise Invalid('未找到导入批次')
            counts={r['state']:r['n'] for r in db.execute('SELECT state,count(*) AS n FROM bulk_segments WHERE batch_id=? GROUP BY state',(batch_id,))}
            samples=db.execute("SELECT count(*) AS n,coalesce(sum(spent_tokens),0) AS spent FROM bulk_segments WHERE batch_id=? AND phase='sample' AND state IN ('applied','failed')",(batch_id,)).fetchone()
            errors=[dict(r) for r in db.execute("SELECT conversation_id,segment_index,error FROM bulk_segments WHERE batch_id=? AND state='failed' ORDER BY created LIMIT 10",(batch_id,))]
        b=dict(batch);b['counts']=counts;b['sample_done']=samples['n']
        b['estimated_total_tokens']=round(samples['spent']/samples['n']*batch['total_segments']) if samples['n'] else None
        b['recent_errors']=errors
        return b

    def list(self,principal):
        permit(principal,'claude:archive','read')
        with self.store.db() as db:
            ids=[r['id'] for r in db.execute('SELECT id FROM bulk_batches WHERE owner=? ORDER BY created DESC',(principal['owner'],))]
        return [self.status(principal,id) for id in ids]

    def control(self,principal,batch_id,action,token_limit=None):
        with self.store.db() as db:
            scoped=db.execute('SELECT scope FROM bulk_batches WHERE id=? AND owner=?',(batch_id,principal['owner'])).fetchone()
        if not scoped:raise Invalid('未找到导入批次')
        permit(principal,scoped['scope'],'write')
        if not principal.get('trusted_user'):
            raise PermissionError('仅本人可控制批次')
        if action not in ('pause','resume','retry_failed','set_limit'):
            raise Invalid('无效操作')
        if action=='set_limit':
            if type(token_limit) is not int or not 100000<=token_limit<=100000000:
                raise Invalid('用量上限需在 100,000–100,000,000 tokens 之间')
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT token_limit,tokens_spent,state FROM bulk_batches WHERE id=? AND owner=?',(batch_id,principal['owner'])).fetchone()
                if not row:raise Invalid('未找到导入批次')
                if token_limit<=row['token_limit'] or token_limit<row['tokens_spent']+RESERVE_TOKENS:
                    raise Invalid('新上限需高于现有上限，并留出下一次请求的预算')
                quality=db.execute('SELECT quality_approved,note FROM model_budgets WHERE owner=? AND scope=?',(principal['owner'],scoped['scope'])).fetchone()
                if not quality or not quality['quality_approved'] or not quality['note'].strip():
                    raise Invalid('扩大历史批次前需本人记录质量验收依据')
                if row['state'] not in ('paused_budget','paused'):
                    raise Invalid('仅暂停的批次可调整上限')
                db.execute("UPDATE bulk_batches SET token_limit=?,state='running' WHERE id=?",(token_limit,batch_id))
            return self.status(principal,batch_id)
        if action=='retry_failed':
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                batch=db.execute('SELECT state,tokens_spent,token_limit,scope FROM bulk_batches WHERE id=? AND owner=?',(batch_id,principal['owner'])).fetchone()
                candidate=db.execute("SELECT s.job_id,s.attempts_counted FROM bulk_segments s JOIN jobs j ON j.id=s.job_id WHERE s.batch_id=? AND s.state='failed' AND j.state='failed' ORDER BY s.created LIMIT 1",(batch_id,)).fetchone()
                if not batch or not candidate:raise Invalid('没有可重试的失败任务')
                if batch['tokens_spent']+scoped_spent(db,principal['owner'],batch['scope'])+RESERVE_TOKENS>batch['token_limit']:
                    raise Invalid('达到模型用量上限；不能重试')
                db.execute("UPDATE jobs SET state='received',error=NULL WHERE id=?",(candidate['job_id'],))
                db.execute("UPDATE bulk_segments SET state='queued',error=NULL,reserved_attempts=?,reserved_tokens=? WHERE job_id=?",
                           (candidate['attempts_counted']+1,RESERVE_TOKENS,candidate['job_id']))
                db.execute("UPDATE bulk_batches SET state='running',tokens_spent=tokens_spent+? WHERE id=?",(RESERVE_TOKENS,batch_id))
            return self.status(principal,batch_id)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM bulk_batches WHERE id=? AND owner=?',(batch_id,principal['owner'])).fetchone()
            if not row:raise Invalid('未找到导入批次')
            if action=='resume' and row['state']=='paused_budget':
                raise Invalid('达到模型用量上限；需先明确提高上限')
            if action=='resume' and row['state']=='paused_error':
                raise Invalid('请先重试失败任务')
            if row['state']!='completed':
                db.execute('UPDATE bulk_batches SET state=? WHERE id=?',('paused' if action=='pause' else 'running',batch_id))
        return self.status(principal,batch_id)

    def tick(self):
        """Reconcile exactly one outstanding job, then enqueue at most one more."""
        with self.store.db() as db:
            batches=[dict(r) for r in db.execute("SELECT * FROM bulk_batches WHERE state IN ('running','paused','paused_budget','paused_error')")]
        for b in batches:
            with self.store.db() as db:
                active=[dict(r) for r in db.execute("SELECT s.id,s.state,s.job_id,s.attempts_counted,s.reserved_attempts,s.reserved_tokens,"
                    "j.state job_state,j.attempts,j.usage,j.error,j.lease_until FROM bulk_segments s LEFT JOIN jobs j ON j.id=s.job_id "
                    "WHERE s.batch_id=? AND s.state='queued'",(b['id'],))]
            for s in active:
                if s['job_state']=='processing' and s['lease_until'] is not None and s['lease_until']<time.time() and s['attempts']>=s['reserved_attempts']:
                    with self.store.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        current=db.execute('SELECT state,tokens_spent,token_limit,owner,scope FROM bulk_batches WHERE id=?',(b['id'],)).fetchone()
                        if current['tokens_spent']+scoped_spent(db,current['owner'],current['scope'])+RESERVE_TOKENS>current['token_limit']:
                            db.execute("UPDATE jobs SET state='failed',error='budget_reclaim',lease=NULL,lease_until=NULL WHERE id=? AND state='processing'",(s['job_id'],))
                            db.execute("UPDATE bulk_batches SET state='paused_budget' WHERE id=?",(b['id'],))
                        else:
                            db.execute('UPDATE bulk_segments SET reserved_attempts=reserved_attempts+1,reserved_tokens=reserved_tokens+? WHERE id=?',
                                       (RESERVE_TOKENS,s['id']))
                            db.execute('UPDATE bulk_batches SET tokens_spent=tokens_spent+? WHERE id=?',(RESERVE_TOKENS,b['id']))
                    continue
                if s['job_state'] not in ('applied','failed') or s['attempts']<=s['attempts_counted']:
                    continue
                usage=(json.loads(s['usage']) if s['usage'] else None) or {}
                if not isinstance(usage,dict):usage={}
                amount=usage.get('total_tokens')
                if type(amount) is not int or amount<0:
                    prompt,completion=usage.get('prompt_tokens'),usage.get('completion_tokens')
                    amount=prompt+completion if type(prompt) is int and type(completion) is int else None
                # Missing usage retains the reserve, including a crashed attempt.
                unmetered=amount is None
                if unmetered:
                    amount=RESERVE_TOKENS
                with self.store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    current=db.execute('SELECT attempts_counted FROM bulk_segments WHERE id=?',(s['id'],)).fetchone()
                    if current['attempts_counted']<s['attempts']:
                        settled=s['reserved_tokens']-RESERVE_TOKENS+amount
                        db.execute('UPDATE bulk_segments SET state=?,attempts_counted=?,reserved_tokens=0,spent_tokens=spent_tokens+?,error=? WHERE id=?',
                                   (s['job_state'],s['attempts'],settled,s['error'],s['id']))
                        db.execute('UPDATE bulk_batches SET tokens_spent=tokens_spent+? WHERE id=?',(amount-RESERVE_TOKENS,b['id']))
                        if unmetered and s['job_state']=='failed':
                            db.execute("UPDATE bulk_batches SET state='paused_error' WHERE id=? AND state='running'",(b['id'],))
            with self.store.db() as db:
                row=db.execute('SELECT state,tokens_spent,token_limit,owner,scope FROM bulk_batches WHERE id=?',(b['id'],)).fetchone()
                extra=scoped_spent(db,row['owner'],row['scope'])
                counts={r['state']:r['n'] for r in db.execute('SELECT state,count(*) AS n FROM bulk_segments WHERE batch_id=? GROUP BY state',(b['id'],))}
            if row['state']!='running':continue
            if counts.get('queued',0):continue
            if counts.get('planned',0)==0:
                with self.store.db() as db:db.execute('UPDATE bulk_batches SET state=? WHERE id=?',
                                                     ('completed_with_errors' if counts.get('failed',0) else 'completed',b['id']))
                continue
            if row['tokens_spent']+extra+RESERVE_TOKENS>row['token_limit']:
                with self.store.db() as db:db.execute("UPDATE bulk_batches SET state='paused_budget' WHERE id=?",(b['id'],))
                continue
            with self.store.db() as db:
                next_segment=db.execute("SELECT * FROM bulk_segments WHERE batch_id=? AND state='planned' ORDER BY CASE phase WHEN 'sample' THEN 0 WHEN 'summary' THEN 1 ELSE 2 END,created,id LIMIT 1",(b['id'],)).fetchone()
            principal={'id':'archive-batch','owner':b['owner'],'scopes':[b['scope']],'actions':['write'],'trusted_user':False}
            result=self.store.ingest(principal,{'scope':b['scope'],'source_type':next_segment['source_type'],'source_key':next_segment['source_key'],'messages':json.loads(next_segment['payload'])})
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute('SELECT * FROM bulk_batches WHERE id=?',(b['id'],)).fetchone()
                segment=db.execute('SELECT state FROM bulk_segments WHERE id=?',(next_segment['id'],)).fetchone()
                if current['state']!='running' or segment['state']!='planned':continue
                if current['tokens_spent']+scoped_spent(db,current['owner'],current['scope'])+RESERVE_TOKENS>current['token_limit']:
                    db.execute("UPDATE bulk_batches SET state='paused_budget' WHERE id=?",(b['id'],));continue
                db.execute("UPDATE jobs SET state='received',error=NULL WHERE id=? AND state='paused_budget'",(result['job_id'],))
                db.execute('UPDATE bulk_segments SET state=?,job_id=?,reserved_attempts=1,reserved_tokens=? WHERE id=?',
                           ('queued',result['job_id'],RESERVE_TOKENS,next_segment['id']))
                db.execute('UPDATE bulk_batches SET tokens_spent=tokens_spent+? WHERE id=?',(RESERVE_TOKENS,b['id']))


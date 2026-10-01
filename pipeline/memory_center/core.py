"""Local pilot: private SQLite, durable jobs, evidence-backed immutable versions."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


def uid():
    return uuid.uuid4().hex


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class Invalid(ValueError):
    pass


class Conflict(Invalid):
    pass


class Store:
    def __init__(self, directory, dsn=None):
        self.dsn = dsn
        self.storage = "postgresql" if dsn else "private-sqlite"
        self.directory = Path(directory).expanduser().resolve()
        repo = Path(__file__).resolve().parents[2]
        public = Path(os.environ.get('QIUYIWU_ROOT', '/var/www/html')).resolve()
        if any(self.directory == p or p in self.directory.parents for p in (repo, public)):
            raise Invalid('记忆数据必须位于网站目录之外')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.path = self.directory / 'memory.sqlite3'
        # Precreate with private permissions, including first-run initialization.
        if not self.dsn:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            self.path.chmod(0o600)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sources(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
              source_key TEXT NOT NULL, digest TEXT NOT NULL, source_type TEXT NOT NULL,
              principal TEXT NOT NULL, trusted_user INTEGER NOT NULL,
              payload TEXT NOT NULL, created REAL NOT NULL,
              UNIQUE(owner,scope,principal,source_key,digest));
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, source_id TEXT UNIQUE NOT NULL,
              state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
              lease TEXT, lease_until REAL, error TEXT, usage TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS records(
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
              topic TEXT NOT NULL, kind TEXT NOT NULL, subject TEXT NOT NULL,
              statement TEXT NOT NULL, status TEXT NOT NULL,
              source_id TEXT NOT NULL, message_id TEXT NOT NULL, quote TEXT NOT NULL,
              lifecycle TEXT NOT NULL, revision INTEGER NOT NULL,
              supersedes TEXT, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS record_scope ON records(owner,scope,lifecycle);
            CREATE TABLE IF NOT EXISTS events(
              id TEXT PRIMARY KEY, record_id TEXT NOT NULL, actor TEXT NOT NULL,
              operation TEXT NOT NULL, previous_id TEXT, created REAL NOT NULL);
            ''')

        from .governance import setup
        setup(self)
        from .budget import setup as setup_budget
        setup_budget(self)
        from .bulk import setup as setup_bulk
        setup_bulk(self)
        from .reprocessing import setup as setup_runs
        setup_runs(self)
        from .entities import setup as setup_entities
        setup_entities(self)

    @contextmanager
    def db(self):
        if self.dsn:
            from .postgres import connect
            with connect(self.dsn) as db:
                yield db
            return
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, principal, body):
        scope = body.get('scope', 'personal')
        permit(principal, scope, 'write')
        messages = body.get('messages')
        source_key = body.get('source_key')
        source_type = body.get('source_type', 'conversation')
        policy = body.get('processing_policy', 'extract')
        if policy not in ('archive', 'extract'): raise Invalid('处理策略需为 archive / extract')
        envelope = body.get('source_metadata', {})
        allowed = {'original_ref', 'original_date', 'author', 'locator', 'parser_version', 'parent_source_key'}
        if not isinstance(envelope, dict) or set(envelope) - allowed or any(not isinstance(v,str) or len(v)>1000 for v in envelope.values()):
            raise Invalid('来源元信息无效；权限由服务端取得')
        if not isinstance(source_key, str) or not 1 <= len(source_key) <= 300:
            raise Invalid('source_key 必须是稳定来源标识，1–300 字符')
        if source_type not in ('conversation', 'imported_summary', 'document'):
            raise Invalid('不支持的来源类型')
        if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
            raise Invalid('每批需 1–100 条消息')
        ids = set()
        for m in messages:
            if not isinstance(m, dict) or m.get('role') not in ('user', 'assistant', 'external'):
                raise Invalid('保留消息角色：user / assistant / external')
            if not isinstance(m.get('id'), str) or not 1 <= len(m['id']) <= 100 or m['id'] in ids:
                raise Invalid('消息 id 必须唯一')
            if not isinstance(m.get('text'), str) or not m['text'].strip():
                raise Invalid('消息正文不能为空')
            ids.add(m['id'])
        normalized = []
        for m in messages:
            item = {k: m[k] for k in ('id', 'role', 'text')}
            for key in ('source_title', 'created_at'):
                if key in m:
                    if not isinstance(m[key], str) or len(m[key]) > 300:
                        raise Invalid('来源元信息无效')
                    item[key] = m[key]
            normalized.append(item)
        payload = encoded(normalized)
        if len(payload) > 24000:
            raise Invalid('单批上限 24,000 字符，请按会话分段')
        digest = hashlib.sha256((source_type + payload + (encoded(envelope) if envelope else '')).encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT s.id,j.id job_id FROM sources s JOIN jobs j ON j.source_id=s.id '
                             'WHERE owner=? AND scope=? AND principal=? AND source_key=? AND digest=?',
                             (principal['owner'], scope, principal['id'], source_key, digest)).fetchone()
            if old:
                return dict(old) | {'duplicate': True}
            # Archival never schedules a model call. Extraction is a separate explicit policy.
            pending = db.execute("SELECT count(*) AS n FROM jobs j JOIN sources s ON s.id=j.source_id WHERE s.owner=? AND j.state IN ('received','processing')", (principal['owner'],)).fetchone()['n']
            if policy == 'extract' and pending >= 50:
                raise Invalid('待处理队列已达50批，请等待处理后再提交')
            sid, jid = uid(), uid()
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (sid, principal['owner'], scope, source_key, digest, source_type,
                        principal['id'], int(bool(principal.get('trusted_user'))), payload, time.time()))
            db.execute('INSERT INTO jobs(id,source_id,state,created) VALUES(?,?,?,?)',
                       (jid, sid, 'archived' if policy == 'archive' else 'received', time.time()))
            db.execute('INSERT INTO source_envelopes VALUES(?,?,?)', (sid, encoded(envelope), policy))
            return {'id': sid, 'job_id': jid, 'duplicate': False}

    def process_one(self, model):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute("SELECT * FROM jobs WHERE state='received' OR "
                             "(state='processing' AND lease_until<?) ORDER BY created LIMIT 1", (time.time(),)).fetchone()
            if not job:
                return False
            source = dict(db.execute('SELECT * FROM sources WHERE id=?', (job['source_id'],)).fetchone())
            external = db.execute('SELECT s.reserved_attempts,s.reserved_tokens FROM bulk_segments s JOIN bulk_batches b ON b.id=s.batch_id WHERE s.job_id=? AND b.owner=? AND b.scope=?', (job['id'],source['owner'],source['scope'])).fetchone()
            from .budget import reserve, settle
            attempt = None
            if source['principal']=='archive-batch' and not external:
                db.execute("UPDATE jobs SET state='paused_budget',error='等待历史批次分配预留' WHERE id=?",(job['id'],))
                return True
            if external and source['principal']=='archive-batch':
                from .claude import PARSER_VERSION
                metadata=db.execute('SELECT metadata FROM source_envelopes WHERE source_id=?',(source['id'],)).fetchone()
                if not metadata or json.loads(metadata['metadata']).get('parser_version')!=PARSER_VERSION:
                    db.execute("UPDATE jobs SET state='paused_budget',error='需按可见正文重新规划旧批次' WHERE id=?",(job['id'],))
                    return True
            if external:
                if external['reserved_attempts'] <= job['attempts'] or external['reserved_tokens'] <= 0:
                    return False
            else:
                attempt = reserve(db, source, 'extract', job['id'])
                if not attempt:
                    db.execute("UPDATE jobs SET state='paused_budget',error='模型预算未设置或已用尽（含历史总上限）' WHERE id=?", (job['id'],))
                    return True
            lease = uid()
            db.execute("UPDATE jobs SET state='processing',attempts=attempts+1,lease=?,lease_until=? WHERE id=?",
                       (lease, time.time() + 180, job['id']))
            source = dict(db.execute('SELECT * FROM sources WHERE id=?', (job['source_id'],)).fetchone())
        usage = None
        try:
            plan, usage = model.extract_source(source) if hasattr(model,'extract_source') else model.extract(json.loads(source['payload']))
            source['processing_method_version'] = (usage or {}).get('method_version')
            try:
                claims = validate_plan(plan, source)
            except Invalid:
                # Archive model output can mix good evidence with a misquoted
                # claim. Keep independently verified claims; never admit the bad one.
                if not source['source_key'].startswith('claude:archive:') or not isinstance(plan, dict) or not isinstance(plan.get('claims'), list) or len(plan['claims']) > 30:
                    raise
                claims = []
                rejected = 0
                for candidate in plan['claims']:
                    try:
                        claims.extend(validate_plan({'claims':[candidate]}, source))
                    except Invalid:
                        rejected += 1
                if not claims:
                    raise
                claims = validate_plan({'claims':claims},source)
                usage = dict(usage or {}) | {'discarded_unsupported_claims':rejected}
            from .documents import setup
            setup(self)
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT lease,state FROM jobs WHERE id=?', (job['id'],)).fetchone()
                if current['lease'] != lease or current['state'] != 'processing':
                    return True
                for c in claims:
                    # Same-source evidence is not independent corroboration; exact duplicates are ignored.
                    exists = db.execute('SELECT id FROM records WHERE owner=? AND scope=? AND source_id=? '
                                        'AND message_id=? AND statement=?',
                                        (source['owner'], source['scope'], source['id'], c['message_id'], c['statement'])).fetchone()
                    if exists:
                        continue
                    rid = uid()
                    db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (rid, source['owner'], source['scope'], c['topic'], c['kind'], c['subject'],
                                c['statement'], c['status'], source['id'], c['message_id'], c['quote'],
                                'active', 1, None, time.time()))
                    db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                               (uid(), rid, 'memory-worker', 'extract', None, time.time()))
                topics = db.execute('SELECT prefixes FROM document_topics WHERE owner=? AND scope=?', (source['owner'], source['scope'])).fetchall()
                if claims and not any(source['source_key'].startswith(prefix) for topic in topics for prefix in json.loads(topic['prefixes'])):
                    first = json.loads(source['payload'])[0]
                    title = first.get('source_title') or '新导入资料'
                    slug = 'source-' + hashlib.sha256(source['source_key'].encode()).hexdigest()[:16]
                    db.execute('INSERT INTO document_topics VALUES(?,?,?,?,?) ON CONFLICT(owner,scope,slug) DO NOTHING', (source['owner'],source['scope'],slug,title[:120],encoded([source['source_key']])))
                db.execute("UPDATE jobs SET state='applied',lease=NULL,lease_until=NULL,error=NULL,usage=? WHERE id=?",
                           (encoded(usage), job['id']))
        except Exception as exc:
            usage = getattr(exc, 'usage', usage)
            # Never put provider responses, tokens or source text in errors/logs.
            error = str(exc) if isinstance(exc, Invalid) else type(exc).__name__
            with self.db() as db:
                db.execute("UPDATE jobs SET state='failed',error=?,usage=?,lease=NULL,lease_until=NULL WHERE id=? AND lease=?",
                           (error[:160], encoded(usage), job['id'], lease))
        finally:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                settle(db, attempt, usage)
        return True

    def snapshot(self, principal, scope, query='', history=False, limit=100, governance_filter=None):
        permit(principal, scope, 'read')
        if not isinstance(query, str) or len(query) > 500:
            raise Invalid('查询上限 500 字符')
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT r.*,s.source_key,s.source_type,s.payload source_payload,j.usage processing_usage '
                    'FROM records r JOIN sources s ON s.id=r.source_id LEFT JOIN jobs j ON j.source_id=s.id '
                    'WHERE r.owner=? AND r.scope=? '
                    + ('' if history else "AND r.lifecycle='active' ") + 'ORDER BY r.created DESC', (principal['owner'], scope))]
            jobs = [dict(r) for r in db.execute('SELECT j.*,s.payload source_payload,s.source_key FROM jobs j JOIN sources s ON s.id=j.source_id '
                    'WHERE s.owner=? AND s.scope=? ORDER BY j.created DESC LIMIT 40', (principal['owner'], scope))]
        from .governance import metadata, usable
        with self.db() as db:
            governed = {r['record_id']: dict(r) for r in db.execute('SELECT g.* FROM record_governance g JOIN records r ON r.id=g.record_id WHERE r.owner=? AND r.scope=?', (principal['owner'], scope))}
        with self.db() as db:
            translations = {r['record_id']:r['text'] for r in db.execute("SELECT t.record_id,t.text FROM record_translations t JOIN records r ON r.id=t.record_id WHERE r.owner=? AND r.scope=? AND t.language='zh'", (principal['owner'],scope))}
        for row in rows:
            row['display_statement'] = translations.get(row['id'],row['statement'])
            row['translated'] = row['id'] in translations
            row['governance'] = metadata(row, governed.get(row['id']))
            row['usable'] = usable(row)
            messages = json.loads(row.pop('source_payload'))
            evidence = next((m for m in messages if m['id'] == row['message_id']), {})
            row['source_title'] = evidence.get('source_title', row['source_key'])
            row['source_date'] = evidence.get('created_at')
            from .claim_context import evidence_context
            row['evidence_context'] = evidence_context(evidence,row['source_type'])
            usage = json.loads(row.pop('processing_usage') or 'null') or {}
            row['review_note'] = (usage.get('review_notes') or {}).get(row['statement'])
            row['processing_method'] = usage.get('method', 'llm' if row['message_id'] != 'correction' else 'owner_correction')
        if query.strip():
            terms = set(re.findall(r'[a-z0-9_]+|[\u4e00-\u9fff]', query.lower()))
            def score(row):
                text = ' '.join(row[k] for k in ('statement', 'display_statement', 'subject', 'topic')).lower()
                return sum(t in text for t in terms) + 5 * (query.lower() in text)
            rows = sorted((r for r in rows if score(r)), key=score, reverse=True)
        if governance_filter:
            if governance_filter not in ('candidate','verified','owner_corrected','historical','rejected','usable','history'):
                raise Invalid('治理筛选无效')
            rows=[r for r in rows if (r['usable'] if governance_filter=='usable' else (r['governance']['state']=='historical' or r['lifecycle']!='active') if governance_filter=='history' else r['governance']['state']==governance_filter)]
        status_counts={}
        for row in rows:status_counts[row['status']]=status_counts.get(row['status'],0)+1
        for job in jobs:
            source_messages = json.loads(job.pop('source_payload'))
            job['source_title'] = source_messages[0].get('source_title', job['source_key']) if source_messages else job['source_key']
            job.pop('lease', None)
            job['usage'] = json.loads(job['usage']) if job['usage'] else None
            if isinstance(job['usage'], dict):
                job['usage'].pop('review_notes', None)
        return {'records': rows[:limit], 'total': len(rows), 'truncated': len(rows) > limit,
                'status_counts':status_counts,'jobs': jobs, 'scope': scope, 'retrieval': 'lexical-v1', 'generated_at': time.time()}

    def materials(self, principal, offset=0, limit=40):
        """Owner workbench inventory. Keep source payloads out of the list response."""
        if not principal.get('trusted_user') or 'read' not in principal.get('actions', []):
            raise PermissionError('仅本人可查看资料清单')
        if type(offset) is not int or not 0 <= offset <= 10000 or type(limit) is not int or not 1 <= limit <= 100:
            raise Invalid('分页范围无效')
        scopes=principal.get('scopes') or []
        if not scopes:return {'materials':[],'total':0,'offset':offset,'limit':limit}
        marks=','.join('?' for _ in scopes)
        where=f"s.owner=? AND s.scope IN ({marks}) AND s.source_type!='correction' AND s.principal!='archive-batch'"
        params=(principal['owner'],*scopes)
        with self.db() as db:
            total=db.execute('SELECT count(*) n FROM sources s WHERE '+where,params).fetchone()['n']
            rows=[dict(r) for r in db.execute(
                'SELECT s.id,s.scope,s.source_key,s.source_type,s.payload,s.created,j.id job_id,j.state,j.attempts,j.error,j.usage,'
                '(SELECT count(*) FROM records r WHERE r.source_id=s.id) AS claim_count '
                'FROM sources s LEFT JOIN jobs j ON j.source_id=s.id WHERE '+where+
                ' ORDER BY s.created DESC LIMIT ? OFFSET ?',params+(limit,offset))]
        for row in rows:
            messages=json.loads(row.pop('payload'))
            row['title']=messages[0].get('source_title') or row['source_key'] if messages else row['source_key']
            row['preview']=' '.join(m['text'] for m in messages)[:180]
            row['message_count']=len(messages)
            usage=json.loads(row.pop('usage') or 'null') or {}
            row['method_version']=usage.get('method_version','legacy')
        return {'materials':rows,'total':total,'offset':offset,'limit':limit}

    def material(self, principal, source_id):
        if not principal.get('trusted_user') or 'read' not in principal.get('actions', []):
            raise PermissionError('仅本人可查看原始资料')
        with self.db() as db:
            row=db.execute('SELECT id,owner,scope,source_key,source_type,principal,payload FROM sources WHERE id=? AND owner=?',
                           (source_id,principal['owner'])).fetchone()
        if not row or row['source_type']=='correction' or row['principal']=='archive-batch':
            raise Invalid('资料不存在')
        permit(principal,row['scope'],'read')
        result=dict(row);result.pop('owner',None);result.pop('principal',None);result['messages']=json.loads(result.pop('payload'))
        with self.db() as db:
            envelope=db.execute('SELECT * FROM source_envelopes WHERE source_id=?',(source_id,)).fetchone()
        result['source_metadata']=json.loads(envelope['metadata']) if envelope else {}
        result['processing_policy']=envelope['policy'] if envelope else 'legacy'
        return result

    def correct(self, principal, rid, body):
        # Correction is explicit owner input, never a model-invented update operation.
        if not principal.get('trusted_user'):
            raise PermissionError('仅本人凭据可纠正')
        statement = body.get('statement')
        if not isinstance(statement, str) or not 1 <= len(statement.strip()) <= 2000:
            raise Invalid('纠正文需 1–2000 字符')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM records WHERE id=? AND owner=?', (rid, principal['owner'])).fetchone()
            if not row:
                raise Invalid('记录不存在')
            permit(principal, row['scope'], 'write')
            if row['lifecycle'] != 'active' or body.get('revision') != row['revision']:
                raise Conflict('记录已变化，请刷新后再纠正')
            sid, newid = uid(), uid()
            payload = encoded([{'id': 'correction', 'role': 'user', 'text': statement}])
            db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (sid, row['owner'], row['scope'], 'correction:' + newid,
                        hashlib.sha256(payload.encode()).hexdigest(), 'correction', principal['id'], 1, payload, time.time()))
            db.execute("UPDATE records SET lifecycle='superseded' WHERE id=?", (rid,))
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (newid, row['owner'], row['scope'], row['topic'], row['kind'], row['subject'], statement,
                        'user_stated', sid, 'correction', statement, 'active', row['revision'] + 1, rid, time.time()))
            db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                       (uid(), newid, principal['id'], 'correction', rid, time.time()))
            return {'id': newid, 'revision': row['revision'] + 1}

    def retry(self, principal, jid):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT j.state,s.scope FROM jobs j JOIN sources s ON s.id=j.source_id '
                             'WHERE j.id=? AND s.owner=?', (jid, principal['owner'])).fetchone()
            if not row:
                raise Invalid('任务不存在')
            permit(principal, row['scope'], 'write')
            if row['state'] != 'failed':
                raise Conflict('只有失败任务可以重试')
            db.execute("UPDATE jobs SET state='received',error=NULL WHERE id=?", (jid,))


def permit(principal, scope, action):
    if scope not in principal.get('scopes', []) or action not in principal.get('actions', []):
        raise PermissionError('该凭据无此范围的权限')


def validate_plan(plan, source):
    if not isinstance(plan, dict) or not isinstance(plan.get('claims'), list) or len(plan['claims']) > 12:
        raise Invalid('模型输出不符合 claims 协议')
    messages = {m['id']: m for m in json.loads(source['payload'])}
    claims = []
    for c in plan['claims']:
        if not isinstance(c, dict):
            raise Invalid('记忆项格式错误')
        for field, maximum in [('statement', 1200), ('subject', 160), ('quote', 2000), ('message_id', 100)]:
            if not isinstance(c.get(field), str) or not 1 <= len(c[field]) <= maximum:
                raise Invalid('记忆字段缺失或超长')
        if c.get('topic') not in ('profile', 'preferences', 'people', 'areas', 'projects', 'topics'):
            raise Invalid('主题分类无效')
        if c.get('kind') not in ('identity', 'preference', 'relationship', 'decision', 'plan', 'event', 'claim', 'suggestion'):
            raise Invalid('记忆类型无效')
        message = messages.get(c['message_id'])
        if not message or c['quote'] not in message['text']:
            raise Invalid('证据必须逐字匹配来源消息')
        if c.get('topic')=='people' or c.get('kind')=='relationship':
            for alias, romanized in re.findall(r'([\u4e00-\u9fff]{2,8})[（(]([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)+)[）)]',c['statement']):
                if romanized in message['text'] and alias not in message['text']:
                    raise Invalid('不能为来源中的拼音姓名猜测中文名，请保留原名')
        acknowledgement=message['text'].strip().casefold().strip('。.!！')
        if acknowledgement in ('继续','好的','好','是的','yes','ok','continue') and c['statement'].strip().casefold().strip('。.!！')!=acknowledgement:
            raise Invalid('简短确认消息不能独立支持扩展记忆，请引用完整依据')
        # Role/status never comes from model output. Summary labels do not establish direct testimony.
        status = 'source_reported'
        if source['source_type'] == 'imported_summary':
            status = 'imported_summary'
        elif message['role'] == 'assistant':
            status = 'agent_suggested'
        elif message['role'] == 'user' and source['trusted_user']:
            status = 'user_stated'
        from .claim_context import evidence_context, contains_immediate_command
        if source.get('processing_method_version') == '2026-10-01.6':
            if contains_immediate_command(c['statement']):
                raise Invalid('即时开工或续写指令不能混入长期记忆，请只提取明确的项目约束')
            context = evidence_context(message,source['source_type'])
            if source['source_type'] != 'imported_summary':
                if context['source_date'] and context['source_date'] not in c['statement']:
                    raise Invalid('历史陈述必须保留来源日期，不能把历史要求当成当前状态')
                if c['topic']=='projects' and context['conversation_title'] and context['conversation_title'] not in c['statement']:
                    raise Invalid('项目陈述必须保留来源对话标题，不能猜测项目身份或使用模糊指代')
            elif not c['statement'].startswith(('摘要记载','摘要主张')):
                raise Invalid('二手摘要必须明确归属，不能升格为本人陈述')
        claims.append(c | {'status': status, 'evidence_context': evidence_context(message,source['source_type'])})
    if sum(c['status']=='agent_suggested' for c in claims)>2:
        raise Invalid('单批最多保留两条必要的助手建议')
    return claims

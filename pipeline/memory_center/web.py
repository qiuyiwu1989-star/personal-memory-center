"""Scoped bearer auth is independent of the old nginx Basic Auth boundary."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
from flask import Blueprint, Flask, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException
from .core import Store, Invalid, Conflict, permit, encoded
from .model import Model, PROMPT_VERSION

PREFIX = '/api/inside/memory-center/v1'


def load_grants(path):
    grants = json.loads(Path(path).read_text())
    if not isinstance(grants, list) or not grants:
        raise Invalid('需配置独立 Agent 凭据')
    for grant in grants:
        if not all(k in grant for k in ('token_sha256', 'id', 'owner', 'scopes', 'actions')):
            raise Invalid('凭据配置缺字段')
    return grants


def blueprint(store, grants, model, browser_principal=None):
    bp = Blueprint('memory_center', __name__, url_prefix=PREFIX)

    @bp.before_request
    def authenticate():
        if request.content_length and request.content_length > 150000:
            return jsonify(error='请求过大'), 413
        if browser_principal is not None and not request.headers.get('Authorization'):
            principal = browser_principal()
            if principal is not None:
                g.memory_principal = principal
                return None
        if getattr(g, 'local_memory_principal', None) is not None:
            g.memory_principal = g.local_memory_principal
            return None
        token = request.headers.get('Authorization', '')
        if not token.startswith('Bearer ') or len(token) > 500:
            return jsonify(error='需要记忆中心独立凭据'), 401
        digest = hashlib.sha256(token[7:].encode()).hexdigest()
        principal = next((p for p in (grants() if callable(grants) else grants) if hmac.compare_digest(p['token_sha256'], digest)), None)
        if principal is None:
            return jsonify(error='凭据无效'), 401
        g.memory_principal = principal
        # Enforce limit here too, because the host application permits larger media uploads.
        if request.content_length and request.content_length > 150000:
            return jsonify(error='请求过大'), 413

    @bp.after_request
    def private(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @bp.errorhandler(Invalid)
    @bp.errorhandler(PermissionError)
    def invalid(exc):
        return jsonify(error=str(exc)), 403 if isinstance(exc, PermissionError) else 409 if isinstance(exc, Conflict) else 400

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise Invalid('请求应为 JSON 对象')
        return data

    @bp.get('/status')
    def status():
        p = g.memory_principal
        return jsonify(principal=p['id'], scopes=p['scopes'], actions=p['actions'],
                       can_correct=bool(p.get('trusted_user')), model_configured=model.configured,
                       mode='production' if store.dsn else 'local-pilot', storage=store.storage, automatic_replacement=False,
                       default_scope=p.get('default_scope','personal'), method_version=PROMPT_VERSION)

    @bp.post('/sources')
    def ingest():
        return jsonify(store.ingest(g.memory_principal, body())), 202

    @bp.get('/entities')
    def entity_list():
        from .entities import listing
        return jsonify(listing(store,g.memory_principal,request.args.get('scope','personal')))

    @bp.post('/entities')
    def entity_register():
        from .entities import register
        data=body()
        return jsonify(register(store,g.memory_principal,data.get('scope','personal'),data))

    @bp.post('/records/<record_id>/translate')
    def translate_record(record_id):
        from .reprocessing import enqueue
        with store.db() as db:
            row=db.execute('SELECT source_id FROM records WHERE id=? AND owner=?',(record_id,g.memory_principal['owner'])).fetchone()
        if not row:raise Invalid('记录不存在')
        return jsonify(enqueue(store,g.memory_principal,row['source_id'],body().get('request_key'),'translate',record_id)),202

    @bp.get('/overview')
    def overview():
        from .governance import usable
        p=g.memory_principal;scope=request.args.get('scope','personal');permit(p,scope,'read')
        snapshot=store.snapshot(p,scope,history=True,limit=1000000)
        active=[r for r in snapshot['records'] if r['lifecycle']=='active']
        with store.db() as db:
            sources=db.execute("SELECT count(*) n FROM sources WHERE owner=? AND scope=? AND source_type!='correction'",(p['owner'],scope)).fetchone()['n']
            tasks={r['state']:r['n'] for r in db.execute('SELECT j.state,count(*) n FROM jobs j JOIN sources s ON s.id=j.source_id WHERE s.owner=? AND s.scope=? GROUP BY j.state',(p['owner'],scope))}
        return jsonify(sources=sources,records=len(active),usable=sum(usable(r) for r in active),
                       candidates=sum(r['governance']['state']=='candidate' for r in active),
                       historical=sum(r['governance']['state']=='historical' or r['lifecycle']!='active' for r in snapshot['records']),
                       rejected=sum(r['governance']['state']=='rejected' for r in active),jobs=tasks)

    @bp.get('/budget')
    def budget_status():
        from .budget import status
        return jsonify(status(store,g.memory_principal,request.args.get('scope','personal')))

    @bp.post('/budget')
    def budget_configure():
        from .budget import configure
        data=body()
        return jsonify(configure(store,g.memory_principal,data.get('scope','personal'),data))

    @bp.post('/materials/<source_id>/reextract')
    def enqueue_reextract(source_id):
        from .reprocessing import enqueue
        return jsonify(enqueue(store,g.memory_principal,source_id,body().get('request_key'))),202

    @bp.get('/extraction-runs')
    def extraction_runs():
        from .reprocessing import listing
        return jsonify(listing(store,g.memory_principal,request.args.get('scope','personal')))

    @bp.get('/extraction-previews/<preview_id>')
    def extraction_preview_get(preview_id):
        from .reprocessing import get_preview
        return jsonify(get_preview(store,g.memory_principal,preview_id))

    @bp.post('/extraction-runs/<run_id>/control')
    def extraction_control(run_id):
        from .reprocessing import control
        data=body()
        return jsonify(control(store,g.memory_principal,run_id,data.get('action'),data.get('indices')))

    @bp.get('/materials')
    def materials():
        try:offset=int(request.args.get('offset','0'))
        except ValueError:raise Invalid('分页范围无效') from None
        return jsonify(store.materials(g.memory_principal,offset))

    @bp.post('/materials/<source_id>/extraction-preview')
    def extraction_preview(source_id):
        from .reprocessing import preview
        data = body()
        return jsonify(preview(store,g.memory_principal,source_id,data.get('plan'),data.get('method_version')))

    @bp.get('/materials/<source_id>')
    def material(source_id):
        return jsonify(store.material(g.memory_principal,source_id))

    @bp.get('/records')
    def records():
        return jsonify(store.snapshot(g.memory_principal, request.args.get('scope', 'personal'),
                        request.args.get('q', ''), request.args.get('history') == '1', governance_filter=request.args.get('state') or None))

    @bp.post('/records/<record_id>/governance')
    def govern(record_id):
        from .governance import review
        return jsonify(review(store, g.memory_principal, record_id, body()))

    @bp.get('/task-context')
    def task_context():
        from .governance import context
        try: budget = int(request.args.get('max_chars', '1600'))
        except ValueError: raise Invalid('读取预算无效') from None
        return jsonify(context(store, g.memory_principal, request.args.get('scope','personal'), request.args.get('q',''), budget))

    @bp.get('/documents')
    def documents():
        from .documents import build_documents
        return jsonify(documents=build_documents(store, g.memory_principal,
                       request.args.get('scope', 'personal'), request.args.get('q', '')))

    @bp.get('/archives')
    def archives():
        p = g.memory_principal
        permit(p, 'claude:archive', 'read')
        if not store.dsn:
            return jsonify(batches=[], conversations=[], message='生产归档目录仅在服务器可用')
        query = request.args.get('q', '')
        if len(query) > 200:
            raise Invalid('查询过长')
        with store.db() as db:
            batches = [dict(r) for r in db.execute('SELECT id,file_count,source_bytes,status FROM archive_batches WHERE owner_id=?', (p['owner'],))]
            rows = [dict(r) for r in db.execute('SELECT c.conversation_id,c.title,c.message_count,c.original_created_at,c.extraction_state FROM archive_conversations c JOIN archive_batches b ON b.id=c.batch_id WHERE b.owner_id=? AND c.title ILIKE ? ORDER BY c.original_created_at DESC LIMIT 100', (p['owner'],'%'+query+'%'))]
            states={r['conversation_id']:dict(r) for r in db.execute(
                "SELECT s.conversation_id,count(*) AS total,sum(CASE WHEN s.state='applied' THEN 1 ELSE 0 END) AS applied,"
                "sum(CASE WHEN s.state='failed' THEN 1 ELSE 0 END) AS failed,"
                "sum(CASE WHEN s.state='queued' THEN 1 ELSE 0 END) AS queued "
                "FROM bulk_segments s JOIN bulk_batches b ON b.id=s.batch_id WHERE b.owner=? AND s.source_type='conversation' "
                'GROUP BY s.conversation_id',(p['owner'],))}
        for row in rows:
            state=states.get(row['conversation_id'])
            if state:
                row['extraction_state']=('failed' if state['failed'] else 'processed' if state['applied']==state['total']
                                         else 'processing' if state['applied'] or state['queued'] else 'not_processed')
        return jsonify(batches=batches, conversations=rows)

    @bp.get('/archives/conversations/<conversation_id>/preview')
    def archive_preview(conversation_id):
        p=g.memory_principal
        permit(p,'claude:archive','read')
        if not p.get('trusted_user'):raise PermissionError('仅本人可预览原始对话')
        with store.db() as db:
            found=db.execute('SELECT c.title FROM archive_conversations c JOIN archive_batches b ON b.id=c.batch_id '
                             'WHERE c.conversation_id=? AND b.owner_id=?',(conversation_id,p['owner'])).fetchone()
            if not found:raise Invalid('未找到对话')
            segments=[dict(r) for r in db.execute("SELECT s.payload FROM bulk_segments s JOIN bulk_batches b ON b.id=s.batch_id "
                "WHERE b.owner=? AND s.conversation_id=? AND s.source_type='conversation' ORDER BY s.segment_index LIMIT 3",
                (p['owner'],conversation_id))]
        messages=[m for row in segments for m in json.loads(row['payload'])]
        excerpt='\n\n'.join('['+m['role']+'] '+m['text'] for m in messages)
        return jsonify(title=found['title'],text=excerpt[:12000],truncated=len(excerpt)>12000 or len(segments)==3,
                       available=bool(messages))

    @bp.get('/bulk')
    def bulk_list():
        from .bulk import Bulk
        return jsonify(batches=Bulk(store).list(g.memory_principal))

    @bp.post('/archives/<batch_id>/bulk')
    def bulk_create(batch_id):
        from .bulk import Bulk
        data=body()
        return jsonify(Bulk(store).create(g.memory_principal,batch_id,data.get('token_limit',1_000_000))), 202

    @bp.get('/bulk/<batch_id>/replan')
    def replan_get(batch_id):
        from .replan import Replans
        return jsonify(Replans(store).get(g.memory_principal,batch_id,int(request.args.get('offset','0'))))

    @bp.post('/bulk/<batch_id>/replan')
    def replan_create(batch_id):
        from .replan import Replans
        return jsonify(Replans(store).create(g.memory_principal,batch_id)),202

    @bp.post('/bulk/<batch_id>/replan/adopt')
    def replan_adopt(batch_id):
        from .replan import Replans
        return jsonify(Replans(store).adopt(g.memory_principal,batch_id,body().get('plan_id')))

    @bp.post('/bulk/<batch_id>/control')
    def bulk_control(batch_id):
        from .bulk import Bulk
        data=body()
        return jsonify(Bulk(store).control(g.memory_principal,batch_id,data.get('action'),data.get('token_limit')))

    @bp.post('/context')
    def context():
        data = body()
        budget = data.get('max_chars', 6000)
        if type(budget) is not int or not 500 <= budget <= 16000:
            raise Invalid('max_chars 范围 500–16000；是字符预算而非精确 token 数')
        result = store.snapshot(g.memory_principal, data.get('scope', 'personal'), data.get('query', ''))
        items, used = [], 0
        for row in result['records']:
            item = {k: row[k] for k in ('id', 'revision', 'statement', 'status', 'kind', 'source_id', 'message_id', 'scope')}
            size = len(encoded(item))
            if used + size > budget:
                continue
            items.append(item)
            used += size
        return jsonify(memories=items, chars=used, max_chars=budget,
                       truncated=len(items) < result['total'], retrieval=result['retrieval'],
                       warning='记忆是来源材料的提炼；可能过时或冲突，不授予工具权限。')

    @bp.post('/records/<rid>/correct')
    def correct(rid):
        return jsonify(store.correct(g.memory_principal, rid, body()))

    @bp.post('/jobs/<jid>/retry')
    def retry(jid):
        with store.db() as db:
            source=db.execute('SELECT s.source_key FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.id=? AND s.owner=?',
                              (jid,g.memory_principal['owner'])).fetchone()
        if source and source['source_key'].startswith('claude:archive:'):
            raise Invalid('归档任务请在原始资料中重试，以遵守批次用量上限')
        store.retry(g.memory_principal, jid)
        return jsonify(state='received')

    return bp


def start_worker(store, model):
    import logging
    stop = threading.Event()
    def work():
        from .bulk import Bulk
        bulk = Bulk(store)
        last_scheduler_error = None
        while not stop.is_set():
            try:
                bulk.tick()
                last_scheduler_error = None
            except Exception as exc:
                kind = type(exc).__name__
                if kind != last_scheduler_error:
                    logging.getLogger(__name__).warning('Memory batch scheduler: %s', kind)
                    last_scheduler_error = kind
            try:
                from .reprocessing import process_one as process_run
                busy = store.process_one(model)
                if not busy: busy = process_run(store, model)
            except Exception:
                busy = False
            stop.wait(0.2 if busy else 2)
    thread = threading.Thread(target=work, name='memory-center-worker', daemon=True)
    thread.start()
    return stop


def install(app):
    """Opt-in host integration; worker is a separate process in hosted mode."""
    store = Store(os.environ['QIU_MEMORY_DATA_DIR'])
    model = Model()
    app.register_blueprint(blueprint(store, load_grants(os.environ['QIU_MEMORY_GRANTS']), model))
    return store, model


def local_app(store, grants, model, auto_principal=None):
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = 150000
    app.register_blueprint(blueprint(store, grants, model))
    root = Path(__file__).resolve().parents[2]

    @app.before_request
    def local_boundary():
        # Defend local development against DNS rebinding. No permissive CORS.
        if request.host.split(':')[0] not in ('127.0.0.1', 'localhost'):
            return jsonify(error='本地试验仅允许 loopback Host'), 403
        if request.remote_addr not in ('127.0.0.1', '::1'):
            return jsonify(error='仅允许本机访问'), 403
        origin = request.headers.get('Origin')
        if (origin and origin != request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site') == 'cross-site':
            return jsonify(error='不允许其他网站访问本地记忆'), 403
        # Custom header requires CORS preflight from foreign origins; no CORS is enabled.
        if auto_principal and request.headers.get('X-Memory-Local') == '1':
            g.local_memory_principal = auto_principal

    @app.get('/')
    @app.get('/admin/memory-agent.html')
    def ui():
        return send_file(root / 'admin' / 'memory-agent.html')

    @app.get('/assets/memory-center.js')
    def script():
        return send_file(root / 'assets' / 'memory-center.js')

    @app.get('/assets/<name>')
    def shared_asset(name):
        if name not in ('ws-shell.js', 'v3-tokens.css', 'memory-center.css', 'memory-files.js'):
            return jsonify(error='Not found'), 404
        return send_file(root / 'assets' / name)

    @app.get('/design-tokens.css')
    def design_tokens():
        return send_file(root / 'design-tokens.css')

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name), exc.code

    return app

"""Owner-only, immutable configuration drafts and audited activation.

Secrets stay in the existing service environment. Model URLs cannot redirect the
existing key to a new destination. Activating a prompt never approves memories.
"""
import ast
import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from .core import Invalid, Conflict, permit, encoded, uid

SCHEMA = '''
CREATE TABLE IF NOT EXISTS system_config_versions(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 kind TEXT NOT NULL, label TEXT NOT NULL, payload TEXT NOT NULL,
 actor TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS system_config_active(
 owner TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL,
 version_id TEXT NOT NULL, revision INTEGER NOT NULL,
 PRIMARY KEY(owner,scope,kind));
CREATE TABLE IF NOT EXISTS system_config_events(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
 kind TEXT NOT NULL, version_id TEXT NOT NULL, previous_id TEXT,
 actor TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL);
'''
KINDS = ('prompt', 'model', 'skill')


def setup(store):
    with store.db() as db: db.executescript(SCHEMA)


def authorize(principal, scope):
    permit(principal, scope, 'read')
    permit(principal, scope, 'write')
    if principal.get('trusted_user') is not True:
        raise PermissionError('仅本人可管理系统配置')


def connection(payload):
    """Only the explicitly provisioned HTTPS destination may receive its key."""
    base = payload['base_url'].rstrip('/')
    parsed = urlparse(base)
    provisioned = os.environ.get('QIU_MEMORY_LLM_BASE', '').rstrip('/')
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or base != provisioned):
        raise Invalid('模型地址需与服务端已配置地址完全一致；新服务商须先独立配置密钥与地址')
    return base


def validate(kind, payload):
    if not isinstance(payload, dict): raise Invalid('配置需为对象')
    fields = {'prompt': {'instructions'}, 'model': {'base_url', 'model', 'max_tokens'},
              'skill': {'name', 'version', 'instructions'}}
    if kind not in KINDS or set(payload) != fields[kind]: raise Invalid('配置字段无效；密钥不能存入配置版本')
    if kind == 'prompt':
        if not isinstance(payload['instructions'], str) or len(payload['instructions']) > 6000:
            raise Invalid('补充提炼提示最多 6,000 字符')
    elif kind == 'model':
        if not isinstance(payload['base_url'], str): raise Invalid('模型地址无效')
        connection(payload)
        if not isinstance(payload['model'], str) or not 1 <= len(payload['model']) <= 200 or any(ord(c)<32 for c in payload['model']):
            raise Invalid('模型或接入点标识无效')
        if type(payload['max_tokens']) is not int or not 1 <= payload['max_tokens'] <= 4096:
            raise Invalid('输出上限需为 1–4096 tokens')
    else:
        if payload['name'] not in ('personal-memory-center', 'memory-capture'):
            raise Invalid('Skill 名称无效')
        if not isinstance(payload['version'], str) or not 1 <= len(payload['version']) <= 80:
            raise Invalid('Skill 版本无效')
        if not isinstance(payload['instructions'], str) or not 1 <= len(payload['instructions']) <= 12000:
            raise Invalid('Skill 内容需为 1–12,000 字符')
    return payload


def integration_manifest():
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse((root/'pipeline/memory_center/service.py').read_text())
    tools = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
             and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                     and d.func.attr == 'tool' for d in n.decorator_list)]
    skills = []
    for name in ('personal-memory-center', 'memory-capture'):
        path = root/'skills'/name/'SKILL.md'
        text = path.read_text()
        skills.append(dict(name=name, sha256=hashlib.sha256(text.encode()).hexdigest(), instructions=text))
    return dict(tools=tools, skills=skills, contract_sha256=hashlib.sha256((root/'pipeline/memory_center/service.py').read_bytes()).hexdigest(), publication='bundled_code',
                note='MCP 工具随代码发布；Skill 草稿需导出并在客户端安装，不会远程自动执行。')


def listing(store, principal, scope):
    authorize(principal, scope)
    from .model import PROMPT, PROMPT_VERSION, Model
    with store.db() as db:
        versions = [dict(r) for r in db.execute('SELECT * FROM system_config_versions WHERE owner=? AND scope=? ORDER BY created DESC LIMIT 101', (principal['owner'], scope))]
        active = {r['kind']: dict(r) for r in db.execute('SELECT * FROM system_config_active WHERE owner=? AND scope=?', (principal['owner'], scope))}
        events = [dict(r) for r in db.execute('SELECT * FROM system_config_events WHERE owner=? AND scope=? ORDER BY created DESC LIMIT 30', (principal['owner'], scope))]
    for v in versions: v['payload'] = json.loads(v['payload'])
    return dict(versions=versions[:100], truncated=len(versions)>100, active=active, events=events,
                baseline=dict(version=PROMPT_VERSION, prompt=PROMPT),
                model=dict(configured=Model().configured, base_url=os.environ.get('QIU_MEMORY_LLM_BASE',''),
                           model=os.environ.get('QIU_MEMORY_LLM_MODEL',''), secret_managed='server_private_config'),
                integration=integration_manifest())


def draft(store, principal, scope, body):
    authorize(principal, scope)
    if set(body) != {'kind', 'label', 'payload'}: raise Invalid('草稿字段无效')
    label = body['label']
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100: raise Invalid('版本名称需为 1–100 字符')
    payload = validate(body['kind'], body['payload'])
    version_id = uid()
    with store.db() as db:
        db.execute('INSERT INTO system_config_versions VALUES(?,?,?,?,?,?,?,?)',
                   (version_id, principal['owner'], scope, body['kind'], label.strip(), encoded(payload), principal['id'], time.time()))
    return dict(id=version_id, state='draft', affects_existing_records=False)


def activate(store, principal, scope, version_id, body):
    authorize(principal, scope)
    if set(body) != {'revision', 'note'} or type(body['revision']) is not int or body['revision'] < 0:
        raise Invalid('需提供当前配置 revision 与验收说明')
    if not isinstance(body['note'], str) or not 10 <= len(body['note'].strip()) <= 1000:
        raise Invalid('请记录具体样本验证或回滚依据（10–1,000 字符）；说明不是系统自动质量认证')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM system_config_versions WHERE id=? AND owner=? AND scope=?', (version_id, principal['owner'], scope)).fetchone()
        if not row: raise Invalid('版本不存在')
        if row['kind'] == 'skill': raise Invalid('Skill 版本通过导出与客户端安装发布；不能在服务端启用为执行代码')
        validate(row['kind'], json.loads(row['payload']))
        current = db.execute('SELECT * FROM system_config_active WHERE owner=? AND scope=? AND kind=?', (principal['owner'],scope,row['kind'])).fetchone()
        revision = current['revision'] if current else 0
        if revision != body['revision']: raise Conflict('配置已变化，请刷新后再操作')
        pending = db.execute("SELECT count(*) n FROM jobs j JOIN sources s ON s.id=j.source_id WHERE s.owner=? AND s.scope=? AND j.state IN ('received','processing')", (principal['owner'],scope)).fetchone()['n']
        runs = db.execute("SELECT count(*) n FROM extraction_runs WHERE owner=? AND scope=? AND state IN ('received','processing')", (principal['owner'],scope)).fetchone()['n']
        running = db.execute("SELECT count(*) n FROM bulk_batches WHERE owner=? AND scope=? AND state='running'", (principal['owner'],scope)).fetchone()['n']
        if pending or runs or running: raise Conflict('请先暂停批处理并等待已入队任务完成，再切换配置')
        db.execute('INSERT INTO system_config_active VALUES(?,?,?,?,?) ON CONFLICT(owner,scope,kind) DO UPDATE SET version_id=excluded.version_id,revision=excluded.revision', (principal['owner'],scope,row['kind'],version_id,revision+1))
        db.execute('INSERT INTO system_config_events VALUES(?,?,?,?,?,?,?,?,?)', (uid(),principal['owner'],scope,row['kind'],version_id,current['version_id'] if current else None,principal['id'],body['note'].strip(),time.time()))
    return dict(version_id=version_id, revision=revision+1, affects_existing_records=False, quality_auto_approved=False)


def runtime(store, source):
    """Freeze one request's active versions; never mutate shared Model or env."""
    if not source.get('owner') or not source.get('scope'): return {}
    with store.db() as db:
        rows = db.execute('SELECT v.id,v.kind,v.payload FROM system_config_active a JOIN system_config_versions v ON v.id=a.version_id AND v.owner=a.owner AND v.scope=a.scope AND v.kind=a.kind WHERE a.owner=? AND a.scope=?', (source['owner'],source['scope'])).fetchall()
    result={}
    for r in rows:
        payload=json.loads(r['payload']);validate(r['kind'],payload)
        result[r['kind']]=payload;result[r['kind']+'_version']=r['id']
    return result


def extra_reservation(db, owner, scope):
    row=db.execute("SELECT v.payload FROM system_config_active a JOIN system_config_versions v ON v.id=a.version_id AND v.owner=a.owner AND v.scope=a.scope AND v.kind=a.kind WHERE a.owner=? AND a.scope=? AND a.kind='prompt'",(owner,scope)).fetchone()
    if not row:return 0
    instructions=json.loads(row['payload'])['instructions']
    return len(instructions.encode('utf-8'))+300 if instructions else 0

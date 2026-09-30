"""Deterministic topic Markdown projections; originals and records remain authoritative."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from .core import Invalid, permit, encoded


def normalize(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).strip('。.!！')


def literal(text):
    """Keep source text as text, even in exported Markdown."""
    text = str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]#|])', r'\\\1', text).replace('\n', ' ')


def setup(store):
    with store.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS document_topics(
          owner TEXT, scope TEXT, slug TEXT, title TEXT, prefixes TEXT,
          PRIMARY KEY(owner,scope,slug));
        CREATE TABLE IF NOT EXISTS document_versions(
          owner TEXT, scope TEXT, slug TEXT, revision INTEGER, digest TEXT,
          markdown TEXT, changes TEXT, created REAL,
          PRIMARY KEY(owner,scope,slug,revision));
        ''')


def define_topic(store, principal, scope, slug, title, source_prefixes):
    permit(principal, scope, 'write')
    if not principal.get('trusted_user'):
        raise PermissionError('仅本人可设置主题范围')
    if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', slug):
        raise Invalid('主题标识无效')
    if not isinstance(title, str) or not 1 <= len(title) <= 120:
        raise Invalid('主题标题无效')
    if not isinstance(source_prefixes, list) or not source_prefixes or not all(isinstance(p,str) and 1 <= len(p) <= 300 for p in source_prefixes):
        raise Invalid('主题需指定来源前缀')
    setup(store)
    with store.db() as db:
        db.execute('INSERT INTO document_topics VALUES(?,?,?,?,?) ON CONFLICT(owner,scope,slug) '
                   'DO UPDATE SET title=excluded.title,prefixes=excluded.prefixes',
                   (principal['owner'],scope,slug,title,encoded(source_prefixes)))


def render(topic, rows):
    by_id = {r['id']:r for r in rows}
    prefixes = json.loads(topic['prefixes'])
    def belongs(row):
        seen=set()
        while row.get('supersedes') and row['supersedes'] in by_id and row['id'] not in seen:
            seen.add(row['id']); row=by_id[row['supersedes']]
        if topic['slug'].startswith('history-') and topic['scope'].startswith('claude:history'):
            category=topic.get('category') or topic['slug'][len('history-'):].split('--page-')[0]
            if row['topic']!=category:
                return False
        return any(row['source_key'].startswith(p) for p in prefixes)
    records=sorted((r for r in rows if belongs(r)),key=lambda r:(r['created'],r['id']))
    groups={}
    for r in records:
        if r['lifecycle']!='active':
            continue
        # Only identical normalized assertions with same attribution merge; no semantic guessing.
        key=(r['status'],r['kind'],normalize(r['subject']),normalize(r['statement']),r.get('governance',{}).get('state','candidate'))
        groups.setdefault(key,[]).append(r)
    refs={r['id']:'S'+str(i+1) for i,r in enumerate(records)}
    sections={'已核实的有效记忆':[], '待核实候选':[], '历史判断':[], '不采纳（保留溯源）':[], '本人明确纠正':[], '历史陈述与要求':[], 'AI 发言与建议（未经本人确认）':[], '导入摘要（尚未回查原话）':[]}
    for group in groups.values():
        r=group[-1]
        section=('本人明确纠正' if r['message_id']=='correction' else 'AI 发言与建议（未经本人确认）'
                 if r['status']=='agent_suggested' else '导入摘要（尚未回查原话）'
                 if r['status']=='imported_summary' else '历史陈述与要求')
        governance=r.get('governance',{})
        if governance.get('state')=='verified':
            from .governance import usable
            section='已核实的有效记忆' if usable(r) else '历史判断'
        elif governance.get('state')=='historical':section='历史判断'
        elif governance.get('state')=='rejected':section='不采纳（保留溯源）'
        elif section=='历史陈述与要求':section='待核实候选'
        date=(r.get('source_date') or '')[:10] or '原始日期未记录'
        refs_text=' '.join('['+refs[x['id']]+']' for x in group)
        sections[section].append('- '+literal(r.get('display_statement',r['statement']))+'（'+date+'） '+refs_text)
    lines=['---','id: '+topic['slug'],'title: '+json.dumps(topic['title'],ensure_ascii=False),
           'scope: '+json.dumps(topic['scope'],ensure_ascii=False),'format: memory-topic-v1','---','',
           '# '+literal(topic['title']),'',
           '> 本文由有来源的抽取记录自动生成，尚未逐条核验语义。历史陈述不代表今天的状态；AI 发言不等于本人观点，也不授予行动权限。',
           '> 在工作台纠正来源记录后，本文自动更新。直接改此导出文件不会回写数据库。','',
           '## 阅读入口','',
           f'当前收录 {len(groups)} 项不同陈述；来源范围由主题规则限定。需要接手时先读要求，再核对变化与来源。',
           '当前实现、进度和未完成事项若无近期直接证据，应重新核实，不能从旧计划推断。','']
    for name,items in sections.items():
        if items:
            lines += ['## '+name,'']+items+['']
    lines += ['## 重要变化','']
    corrections=[r for r in records if r.get('supersedes')]
    if not corrections:
        lines += ['尚无明确纠正记录。不同来源的矛盾陈述仍并列保留，不按日期自动裁决。','']
    else:
        for r in corrections:
            old=by_id.get(r['supersedes'])
            lines.append('- v'+str(r['revision'])+'：'+literal(old['statement'] if old else '前一版本')+' → '+literal(r['statement'])+' ['+refs[r['id']]+']')
        lines.append('')
    lines += ['## 来源与版本','']
    for r in records:
        lines += ['### '+refs[r['id']], '',
                  '- 标题：'+literal(r['source_title']),
                  '- 原始日期：'+literal(r.get('source_date') or '未记录'),
                  '- 来源键：'+literal(r['source_key']),
                  '- 消息：'+literal(r['message_id']),
                  '- 记录：'+r['id']+' / v'+str(r['revision'])+' / '+r['lifecycle'],
                  '- 性质：'+r['status'],
                  '- 治理状态：'+r.get('governance',{}).get('state','candidate'),
                  '- 主张者：'+literal(r.get('governance',{}).get('holder') or '未知'),
                  '- 对象：'+literal(r.get('governance',{}).get('subject_id') or r['subject']),
                  '- 优先级：'+r.get('governance',{}).get('priority','P3'),
                  '- 失效日期：'+str(r.get('governance',{}).get('valid_until') or '未记录'),
                  '- 成立时间：'+str(r.get('governance',{}).get('as_of') or '未知'),
                  '- 原始陈述：'+literal(r['statement']) if r.get('translated') else '- 展示语言：原文',
                  '> '+literal(r['quote']),'']
    dependencies=[{'id':r['id'],'revision':r['revision'],'lifecycle':r['lifecycle'],'governance_revision':r.get('governance',{}).get('revision',0)} for r in records]
    return '\n'.join(lines), dependencies, len(groups)


def build_documents(store, principal, scope, query=''):
    permit(principal, scope, 'read')
    if not isinstance(query,str) or len(query)>500:
        raise Invalid('查询上限500字符')
    setup(store)
    import time
    results=[]
    # Acquire write lock before taking the authoritative snapshot; corrections cannot race projection.
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        topics=db.execute('SELECT * FROM document_topics WHERE owner=? AND scope=? ORDER BY slug',
                          (principal['owner'],scope)).fetchall()
        signature=encoded({
            'topics':[dict(t) for t in topics],
            'records':dict(db.execute('SELECT count(*) n,max(created) latest,sum(revision) revisions FROM records WHERE owner=? AND scope=?',(principal['owner'],scope)).fetchone()),
            'governance':dict(db.execute('SELECT count(*) n,max(g.reviewed) latest,sum(g.revision) revisions FROM record_governance g JOIN records r ON r.id=g.record_id WHERE r.owner=? AND r.scope=?',(principal['owner'],scope)).fetchone()),
            'translations':dict(db.execute('SELECT count(*) n,max(t.reviewed) latest FROM record_translations t JOIN records r ON r.id=t.record_id WHERE r.owner=? AND r.scope=?',(principal['owner'],scope)).fetchone())})
        cache=getattr(store,'_document_cache',{}).get((principal['owner'],scope))
        if cache and cache[0]==signature:
            intact=all(Path(d['export_path']).exists() and Path(d['export_path']).stat().st_mtime_ns==stamp for d,stamp in cache[1])
            if intact:
                return [dict(d) for d,_ in cache[1] if not query.strip() or query.casefold() in (d['title']+'\n'+d['markdown']).casefold()]
        rows=store.snapshot(principal,scope,history=True,limit=1000000)['records']
        expanded=[]
        for raw_topic in topics:
            topic=dict(raw_topic)
            markdown,deps,count=render(topic,rows)
            if count<=25:
                expanded.append((topic,rows,None));continue
            member_ids={d['id'] for d in deps}
            members=[r for r in rows if r['id'] in member_ids]
            by_id={r['id']:r for r in members}
            def root(row):
                seen=set()
                while row.get('supersedes') in by_id and row['id'] not in seen:
                    seen.add(row['id']);row=by_id[row['supersedes']]
                return row
            groups={}
            for row in sorted(members,key=lambda r:(root(r)['created'],root(r)['id'],r['created'],r['id'])):
                original=root(row)
                key=(original['status'],original['kind'],normalize(original['subject']),normalize(original['statement']))
                groups.setdefault(key,[]).append(row)
            batches=list(groups.values());pages=[]
            for start in range(0,len(batches),25):
                index=start//25+1
                leaf=dict(topic,slug=topic['slug']+'--page-'+str(index),title=topic['title']+' · '+str(index))
                if topic['slug'].startswith('history-'):leaf['category']=topic['slug'][8:]
                page_rows=[r for group in batches[start:start+25] for r in group]
                expanded.append((leaf,page_rows,None));pages.append(leaf)
            directory='# '+literal(topic['title'])+'\n\n分类目录；具体陈述分成小文档，每页最多 25 组，审核状态在正文标明。\n\n'+ '\n'.join('- '+literal(p['title'])+' · '+p['slug'] for p in pages)
            expanded.append((topic,members,(directory,deps,count)))
        for topic,page_rows,index_projection in expanded:
            markdown,deps,count=index_projection or render(topic,page_rows)
            digest=hashlib.sha256(markdown.encode()).hexdigest()
            old=db.execute('SELECT * FROM document_versions WHERE owner=? AND scope=? AND slug=? ORDER BY revision DESC LIMIT 1',
                           (principal['owner'],scope,topic['slug'])).fetchone()
            changed=not old or old['digest']!=digest
            revision=(old['revision'] if old else 0)+int(changed)
            if changed:
                diff='\n'.join(difflib.unified_diff((old['markdown'] if old else '').splitlines(),markdown.splitlines(),
                       fromfile='v'+str(revision-1),tofile='v'+str(revision),lineterm=''))
                db.execute('INSERT INTO document_versions VALUES(?,?,?,?,?,?,?,?)',
                           (principal['owner'],scope,topic['slug'],revision,digest,markdown,diff,time.time()))
            else:
                diff=old['changes']
            # Export is a disposable projection, kept outside the website. Atomic replacement.
            namespace=hashlib.sha256(encoded([principal['owner'],scope]).encode()).hexdigest()[:24]
            folder=store.directory/'documents'/namespace
            folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            target=folder/(topic['slug']+'.md')
            if not target.exists() or target.read_text()!=markdown:
                import tempfile
                fd,tmp=tempfile.mkstemp(prefix='projection-',dir=folder)
                try:
                    with os.fdopen(fd,'w') as file:file.write(markdown)
                    os.replace(tmp,target)
                finally:
                    if os.path.exists(tmp):os.unlink(tmp)
            results.append({'slug':topic['slug'],'title':topic['title'],'revision':revision,'digest':digest,
                            'markdown':markdown,'changes':diff,'claims':count,'dependencies':deps,'export_path':str(target),'is_index':bool(index_projection),'category':topic.get('category') or topic['slug'].replace('history-','').split('--page-')[0]})
    if not hasattr(store,'_document_cache'):store._document_cache={}
    store._document_cache[(principal['owner'],scope)]=(signature,[(d,Path(d['export_path']).stat().st_mtime_ns) for d in results])
    return [d for d in results if not query.strip() or query.casefold() in (d['title']+'\n'+d['markdown']).casefold()]

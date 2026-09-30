"""Explicit stable entities. Aliases aid navigation; never merge identities."""
import json
import re
from .core import Invalid, permit, encoded

SCHEMA='''
CREATE TABLE IF NOT EXISTS memory_entities(
 owner TEXT NOT NULL, scope TEXT NOT NULL, id TEXT NOT NULL,
 kind TEXT NOT NULL, name TEXT NOT NULL, aliases TEXT NOT NULL,
 PRIMARY KEY(owner,scope,id));
'''


def setup(store):
    with store.db() as db:db.executescript(SCHEMA)


def register(store,principal,scope,body):
    permit(principal,scope,'write')
    if not principal.get('trusted_user'):raise PermissionError('仅本人可登记实体')
    kind=body.get('kind');eid=body.get('id');name=body.get('name');aliases=body.get('aliases',[])
    if kind not in ('person','project','organization','topic') or not isinstance(eid,str) or not re.fullmatch(r'[a-z][a-z0-9:_-]{0,99}',eid):raise Invalid('实体类型或稳定 ID 无效')
    if not isinstance(name,str) or not name.strip() or len(name)>120 or not isinstance(aliases,list) or len(aliases)>20 or any(not isinstance(a,str) or not 1<=len(a)<=120 for a in aliases):raise Invalid('名称或别名无效')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT * FROM memory_entities WHERE owner=? AND scope=? AND id=?',(principal['owner'],scope,eid)).fetchone()
        if old:
            if old['kind']!=kind or old['name']!=name or old['aliases']!=encoded(aliases):raise Invalid('实体 ID 已存在；不能通过重注册合并或改写身份')
            return {'id':eid,'duplicate':True}
        db.execute('INSERT INTO memory_entities VALUES(?,?,?,?,?,?)',(principal['owner'],scope,eid,kind,name,encoded(aliases)))
    return {'id':eid,'duplicate':False}


def listing(store,principal,scope):
    permit(principal,scope,'read')
    with store.db() as db:
        rows=[dict(r) for r in db.execute('SELECT id,kind,name,aliases FROM memory_entities WHERE owner=? AND scope=? ORDER BY name LIMIT 200',(principal['owner'],scope))]
    for row in rows:row['aliases']=json.loads(row['aliases'])
    return {'entities':[{'id':'owner:'+principal['owner'],'kind':'person','name':'本人','aliases':[]}]+rows}


def exists(db,owner,scope,eid):
    return eid=='owner:'+owner or bool(db.execute('SELECT id FROM memory_entities WHERE owner=? AND scope=? AND id=?',(owner,scope,eid)).fetchone())

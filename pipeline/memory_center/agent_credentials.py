"""Owner-only scoped grants; raw secrets exist only in create response."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from .core import Invalid,Conflict,permit

class AgentCredentials:
    def __init__(self,path):self.path=Path(path)
    def _authorize(self,principal):
        if principal.get('trusted_user') is not True or 'write' not in principal.get('actions',[]):
            raise PermissionError('仅本人可管理 Agent 凭据')
    def _read(self):
        rows=json.loads(self.path.read_text())
        if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows):raise Invalid('凭据配置无效')
        return rows
    def _visible(self,p,row):
        return row.get('owner')==p.get('owner') and row.get('trusted_user') is not True and all(s in p.get('scopes',[]) for s in row.get('scopes',[]))
    def _summary(self,row):
        now=time.time();expires=row.get('expires_at')
        return {k:row.get(k) for k in ('id','description','scopes','actions','created_at','expires_at')}|{'archive_only':row.get('archive_only',False),'state':'revoked' if row.get('enabled',True) is False else 'expired' if expires is not None and expires<=now else 'active'}
    def list(self,p):
        self._authorize(p)
        rows=[self._summary(r) for r in self._read() if self._visible(p,r)]
        return {'credentials':rows[:100],'total':len(rows),'truncated':len(rows)>100}
    def _save(self,rows):
        path=self.path.with_name(self.path.name+'.'+secrets.token_hex(8)+'.tmp')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w') as f:json.dump(rows,f);f.flush();os.fsync(f.fileno())
            os.replace(path,self.path)
        finally:
            if path.exists():path.unlink()
    def _lock(self):
        fd=os.open(self.path.with_name('grants.lock'),os.O_RDWR|os.O_CREAT,0o600)
        handle=os.fdopen(fd,'a');fcntl.flock(handle,fcntl.LOCK_EX);return handle
    def create(self,p,body):
        self._authorize(p)
        if not isinstance(body,dict) or set(body)-{'request_key','description','scopes','actions','days','archive_only'}:raise Invalid('凭据字段无效')
        if body.get('archive_only',True) is not True:raise Invalid('新 Agent 凭据仅支持归档，不开放付费整理权限')
        key=body.get('request_key');label=body.get('description');scopes=body.get('scopes');actions=body.get('actions',['read']);days=body.get('days',30)
        if not isinstance(key,str) or not 1<=len(key)<=160 or not isinstance(label,str) or not 1<=len(label.strip())<=120:raise Invalid('需要请求键与简短用途')
        if type(days) is not int or not 1<=days<=90:raise Invalid('有效期为 1–90 天')
        if not isinstance(scopes,list) or not 1<=len(scopes)<=10 or any(not isinstance(s,str) for s in scopes) or len(set(scopes))!=len(scopes):raise Invalid('需选择授权范围')
        if not isinstance(actions,list) or not actions or any(a not in ('read','source_read','write') for a in actions) or len(set(actions))!=len(actions) or 'read' not in actions:raise Invalid('权限组合无效')
        if 'write' in actions and (len(scopes)!=1 or not scopes[0].startswith('agent:') or not scopes[0].endswith('-inbox')):raise Invalid('写入凭据只允许单独 Agent 收件范围')
        for scope in scopes:
            for action in actions:permit(p,scope,action)
        spec={'archive_only':True,'description':label.strip(),'scopes':sorted(scopes),'actions':sorted(actions),'days':days}
        digest=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
        ident='agent-'+hashlib.sha256(json.dumps([p['owner'],p['id'],key]).encode()).hexdigest()[:24]
        with self._lock():
            rows=self._read();old=next((r for r in rows if r.get('id')==ident),None)
            if old:
                legacy_digest=hashlib.sha256(json.dumps({k:v for k,v in spec.items() if k!='archive_only'},sort_keys=True).encode()).hexdigest()
                compatible=old.get('archive_only') is None and old.get('request_digest')==legacy_digest
                if old.get('request_digest')!=digest and not compatible:raise Conflict('请求键已用于不同配置')
                return {'credential':self._summary(old),'token':None,'duplicate':True,'notice':'凭据已创建，原值不能恢复；遗失请撤销后重新创建'}
            token=secrets.token_urlsafe(36);now=int(time.time())
            row=dict(spec,id=ident,owner=p['owner'],created_by=p['id'],trusted_user=False,enabled=True,created_at=now,expires_at=now+days*86400,token_sha256=hashlib.sha256(token.encode()).hexdigest(),request_digest=digest)
            rows.append(row);self._save(rows)
        return {'credential':self._summary(row),'token':token,'duplicate':False}
    def revoke(self,p,ident):
        self._authorize(p)
        with self._lock():
            rows=self._read();row=next((r for r in rows if r.get('id')==ident and self._visible(p,r)),None)
            if not row:raise Invalid('凭据不存在或不可管理')
            row['enabled']=False;row['revoked_at']=int(time.time());row['revoked_by']=p['id'];self._save(rows)
        return {'credential':self._summary(row)}

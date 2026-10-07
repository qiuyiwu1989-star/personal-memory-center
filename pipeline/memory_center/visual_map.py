"""Bounded source/claim/entity map, with no inferred relationships or LLM."""
from .core import Invalid, permit
from .governance import metadata, usable


def build(store, principal, scope, query='', state='', offset=0, limit=40):
    permit(principal,scope,'read')
    if not isinstance(query,str) or len(query)>300 or state not in ('','candidate','verified','historical','rejected'):
        raise Invalid('可视化筛选无效')
    if type(offset) is not int or not 0<=offset<=1000000 or type(limit) is not int or not 1<=limit<=80:
        raise Invalid('可视化分页无效')
    clauses=['r.owner=?','r.scope=?'];params=[principal['owner'],scope]
    if query:
        clauses.append('(r.statement LIKE ? OR r.subject LIKE ?)');params.extend(['%'+query+'%']*2)
    if state:
        clauses.append("coalesce(g.state,'candidate')=?");params.append(state)
    where=' AND '.join(clauses)
    with store.db() as db:
        total=db.execute('SELECT count(*) n FROM records r LEFT JOIN record_governance g ON g.record_id=r.id WHERE '+where,params).fetchone()['n']
        rows=[dict(r) for r in db.execute('SELECT r.* FROM records r LEFT JOIN record_governance g ON g.record_id=r.id WHERE '+where+' ORDER BY r.created DESC,r.id LIMIT ? OFFSET ?',params+[limit,offset])]
        for row in rows:
            row['governance']=metadata(row,db.execute('SELECT * FROM record_governance WHERE record_id=?',(row['id'],)).fetchone())
    nodes={};edges=[];records=[]
    def add(node_id,kind,label): nodes[node_id]=dict(id=node_id,kind=kind,label=label)
    for r in rows:
        rid='record:'+r['id'];sid='source:'+r['source_id'];g=r['governance']
        add(rid,'record',r['statement'][:100]);add(sid,'source',r['source_id'][:12])
        edges.append(dict(source=rid,target=sid,relation='来源',verified=False))
        if g.get('subject_id'):
            eid='subject:'+g['subject_id'];add(eid,'subject',g['subject_id']);edges.append(dict(source=rid,target=eid,relation='关于',verified=usable(r)))
        if g.get('holder'):
            hid='holder:'+g['holder'];add(hid,'holder',g['holder']);edges.append(dict(source=rid,target=hid,relation='观点归属',verified=usable(r)))
        if r.get('supersedes'):
            old='record:'+r['supersedes'];add(old,'history',r['supersedes'][:12]);edges.append(dict(source=rid,target=old,relation='取代',verified=False))
        records.append(dict(id=r['id'],statement=r['statement'],subject=r['subject'],topic=r['topic'],
                            source_id=r['source_id'],message_id=r['message_id'],quote=r['quote'][:500],
                            lifecycle=r['lifecycle'],governance=g,usable=usable(r)))
    return dict(nodes=list(nodes.values()),edges=edges,records=records,total=total,offset=offset,
                next_offset=offset+len(rows) if offset+len(rows)<total else None,
                coverage='filtered_page',inferred_relationships=False,model_calls=0)

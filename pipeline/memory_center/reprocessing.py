"""Evidence-validated, non-destructive previews of revised extraction output.

This does not call a model or schedule work. A caller must separately authorize
and budget extraction. Matching a quote does not verify the resulting statement.
"""
import json
import time
from .core import Invalid, permit, validate_plan, uid, encoded

SCHEMA = '''
CREATE TABLE IF NOT EXISTS extraction_previews(
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL, method_version TEXT NOT NULL,
 source_digest TEXT NOT NULL, comparison TEXT NOT NULL, created REAL NOT NULL);
'''


def preview(store, principal, source_id, plan, method_version):
    if not isinstance(method_version,str) or not 1 <= len(method_version) <= 100:
        raise Invalid('需要方法版本')
    with store.db() as db:
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        source=db.execute('SELECT * FROM sources WHERE id=? AND owner=?',(source_id,principal['owner'])).fetchone()
        if not source:raise Invalid('来源不存在')
        permit(principal,source['scope'],'write')
        claims=validate_plan(plan,source)
        old=[dict(r) for r in db.execute('SELECT * FROM records WHERE source_id=?',(source_id,))]
        changes=[]
        for claim in claims:
            identical=[r['id'] for r in old if r['statement']==claim['statement'] and r['message_id']==claim['message_id']]
            related=[r['id'] for r in old if r['subject']==claim['subject'] and r['kind']==claim['kind'] and r['lifecycle']=='active']
            changes.append({'candidate':claim,'comparison':'duplicate' if identical else 'related_needs_review' if related else 'new',
                            'existing_ids':identical or related})
        result={'id':uid(),'source_id':source_id,'method_version':method_version,'changes':changes,
                'policy':'preview-only-no-replacement','semantic_verified':False}
        db.execute('INSERT INTO extraction_previews VALUES(?,?,?,?,?,?)',
                   (result['id'],source_id,method_version,source['digest'],encoded(result),time.time()))
    return result

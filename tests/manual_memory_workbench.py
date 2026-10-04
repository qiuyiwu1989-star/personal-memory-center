"""Manual browser fixture: real routes, disposable synthetic DB, no worker or LLM.
Run: python3 tests/manual_memory_workbench.py; open http://127.0.0.1:5088/#ingest
All writes stay in a fresh TemporaryDirectory removed on normal shutdown.
Never intended for deployment. Synthetic preview is seeded, not model-generated.
"""
import sys,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipeline.memory_center.core import Store
from pipeline.memory_center.web import local_app
from pipeline.memory_center import reprocessing
from pipeline.memory_center.owner_memory import create
class NoModel:
    configured=False
    def extract(self,*a,**k): raise AssertionError('LLM disabled in browser fixture')
    def extract_source(self,*a,**k): raise AssertionError('LLM disabled in browser fixture')
    def translate(self,*a,**k): raise AssertionError('LLM disabled in browser fixture')
def fixture(directory):
    store=Store(directory)
    principal={'id':'synthetic-browser-owner','owner':'synthetic-browser-owner','scopes':['personal'],'actions':['read','write','source_read'],'trusted_user':True,'default_scope':'personal'}
    sources=[]
    for i,state in enumerate(['archived','applied','failed']):
        item=store.ingest(principal,{'scope':'personal','source_key':'synthetic:browser:'+state,'source_type':'conversation','processing_policy':'archive','messages':[{'id':'1','role':'user','text':'合成项目 Atlas 必须保留原始证据。','source_title':'合成资料 · '+state,'created_at':'2026-10-04'}]})
        sources.append(item)
        with store.db() as db:
            db.execute('UPDATE jobs SET state=?,error=?,usage=? WHERE id=?',(state,'synthetic_failure: 条件范围需要复核 <不是HTML>' if state=='failed' else None,json.dumps({'method_version':'synthetic-browser-v1'}) if state!='archived' else None,item['job_id']))
    create(store,principal,'personal',{'request_key':'synthetic-owner-entry','statement':'合成本人陈述：项目 Atlas 需要保留证据。','kind':'decision','topic':'projects','subject':'Atlas'})
    comparison=reprocessing.preview(store,principal,sources[1]['id'],{'claims':[{'statement':'合成项目 Atlas 必须保留原始证据。','quote':'合成项目 Atlas 必须保留原始证据。','message_id':'1','kind':'decision','subject':'Atlas','topic':'projects'}]},'synthetic-browser-v1')
    run=reprocessing.enqueue(store,principal,sources[1]['id'],'synthetic-seeded-preview')
    with store.db() as db:
        db.execute('UPDATE extraction_runs SET state=?,preview_id=? WHERE id=?',('ready',comparison['id'],run['id']))
    return local_app(store,[],NoModel(),auto_principal=principal)
if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='memory-browser-synthetic-') as directory:
        print('Synthetic only; no worker/LLM; http://127.0.0.1:5088/#ingest',flush=True)
        fixture(directory).run(host='127.0.0.1',port=5088,debug=False,use_reloader=False)

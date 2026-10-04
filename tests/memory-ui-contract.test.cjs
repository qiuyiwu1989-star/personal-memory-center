// Synthetic DOM/transport: execute real UI handlers, never contact a server.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {webcrypto}=require('node:crypto');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.attrs={};this.value='';this.hidden=false;this.classList={add(){},remove(){}};}
  append(...items){this.children.push(...items);} prepend(...items){this.children.unshift(...items);} before(){} after(){}
  replaceChildren(...items){this.children=items;} setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  contains(item){return this===item||this.children.some(c=>c.contains?.(item));}
  querySelectorAll(){return [];} showModal(){this.open=true;} close(){this.open=false;}
  async emit(kind){for(const fn of this.listeners[kind]||[])await fn({preventDefault(){},submitter:this});}
}
function setup(getResponses={},postResponses={}){
  const ids=new Map(),$=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
  $('scope').value='personal';$('ingest-scope').value='personal';$('source-type').value='document';$('processing-policy').value='archive';$('source-visibility').value='unknown';
  const calls=[],window={addEventListener(){}};
  const context={document:{getElementById:$,createElement:t=>new Element(t),querySelectorAll:()=>[],querySelector:()=>null},window,
    location:{hash:''},URLSearchParams,TextEncoder,crypto:webcrypto,MemoryFiles:require('../assets/memory-files.js'),setInterval:()=>1,clearInterval(){},fetch:async(url,options)=>{
      if(options.method==='GET')return {ok:true,json:async()=>getResponses[new URL(url,'http://synthetic').pathname]||({entities:[]})};
      calls.push({url,body:JSON.parse(options.body)});
      const known=postResponses[new URL(url,'http://synthetic').pathname];if(known)return {ok:true,json:async()=>known};
      return {ok:false,json:async()=>({error:'纠正时间审计需要先应用独立的 007 迁移'})};
    }};
  let script=fs.readFileSync(require.resolve('../assets/memory-center.js'),'utf8');
  // Expose closures in this isolated test context; production code is unmodified.
  script=script.replace(/  connect\(\);\n\}\)\(\);\s*$/, '  window.testUI={ownerEditor,reviewRecord,renderProjection,methodLabel,failureDetail,refreshMaterials,setIdentity:p=>identity=p};\n})();');
  vm.runInNewContext(script,context);return {$,calls,ui:window.testUI};
}
function find(root,predicate){if(predicate(root))return root;for(const child of root.children){const result=find(child,predicate);if(result)return result;}}
const field=(root,label)=>find(root,e=>e.attrs?.['aria-label']===label);
const form=root=>find(root,e=>e.tagName==='form');

test('new owner entry omits optional change fields and stays candidate',async()=>{
  const {$,calls,ui}=setup();ui.ownerEditor();const host=$('review-content');field(host,'陈述正文').value='Synthetic owner statement.';
  await form(host).emit('submit');const body=calls[0].body;
  assert.equal(body.governance.state,'candidate');assert.equal(body.scope,'personal');
  assert.equal(body.change_kind,undefined);assert.equal(body.previous_valid_until,undefined);
  assert.equal(field(host,'旧观点事实失效日期（可空）'),undefined);
  assert.ok(!field(host,'此次变化类型（可选）').children.some(o=>['withdrawal','viewpoint_change'].includes(o.value)));
  assert.match($('notice').textContent,/007/); // Server migration errors remain visible.
});
test('revision sends old fact end only for explicit viewpoint change and clears hidden date',async()=>{
  const {$,calls,ui}=setup();ui.ownerEditor({id:'synthetic',scope:'personal',statement:'Synthetic prior.',revision:2,governance:{revision:3,state:'verified'}});
  const host=$('review-content'),kind=field(host,'此次变化类型（可选）'),date=field(host,'旧观点事实失效日期（可空）');
  kind.value='viewpoint_change';await kind.emit('change');date.value='2001-01-01';await form(host).emit('submit');
  assert.equal(find(host,e=>e.children.includes(date)).hidden,false);
  assert.equal(calls[0].body.change_kind,'viewpoint_change');assert.equal(calls[0].body.previous_valid_until,'2001-01-01');
  assert.equal(calls[0].body.governance.state,'candidate');assert.equal(calls[0].body.revision,2);
  kind.value='metadata_update';await kind.emit('change');assert.equal(date.value,'');await form(host).emit('submit');
  assert.equal(calls[1].body.previous_valid_until,undefined);assert.equal(calls[1].body.change_kind,'metadata_update');
});
test('owner withdrawal needs explicit rejection confirmation and never remains usable',async()=>{
  const {$,calls,ui}=setup();ui.ownerEditor({id:'synthetic',scope:'personal',statement:'Synthetic.',revision:1,governance:{revision:1,state:'verified'}});
  const host=$('review-content'),kind=field(host,'此次变化类型（可选）');kind.value='withdrawal';await kind.emit('change');
  await form(host).emit('submit');assert.equal(calls.length,0);assert.match($('notice').textContent,/明确确认/);
  field(host,'确认将治理状态设为不采纳').checked=true;await form(host).emit('submit');
  assert.equal(calls[0].body.change_kind,'withdrawal');assert.equal(calls[0].body.governance.state,'rejected');
  assert.equal(calls[0].body.previous_valid_until,undefined);
});
test('review withdrawal rejects verified selection until user selects rejected',async()=>{
  const {$,calls,ui}=setup();await ui.reviewRecord({id:'synthetic',statement:'Synthetic.',quote:'Synthetic.',governance:{revision:1,state:'verified'}});
  const host=$('review-content');field(host,'此次变化类型（可选）').value='withdrawal';await form(host).emit('submit');
  assert.equal(calls.length,0);assert.match($('notice').textContent,/不采纳/);
  field(host,'治理状态').value='rejected';await form(host).emit('submit');assert.equal(calls[0].body.state,'rejected');
});
test('projection never claims ready for absent, unknown or incomplete status',()=>{
  const {$,ui}=setup();ui.renderProjection(undefined);assert.equal($('projection-status').hidden,true);
  ui.renderProjection({state:'ready',stale:null,coverage:'since-migration-only'});assert.match($('projection-status').textContent,/未知/);assert.doesNotMatch($('projection-status').textContent,/已刷新/);
  ui.renderProjection({state:'ready',stale:false,coverage:'since-migration-only'});assert.match($('projection-status').textContent,/已刷新/);assert.match($('projection-status').textContent,/不表示其他 Agent/);
  ui.renderProjection({state:'dirty',stale:true,coverage:'since-migration-only'});assert.match($('projection-status').textContent,/待刷新/);
});
test('governance review uses top-level optional change fields without changing trust',async()=>{
  const {$,calls,ui}=setup();await ui.reviewRecord({id:'synthetic',statement:'Synthetic.',quote:'Synthetic evidence.',governance:{revision:1,state:'candidate',priority:'P3'}});
  const host=$('review-content');field(host,'此次变化类型（可选）').value='evidence_update';await form(host).emit('submit');
  assert.equal(calls[0].body.change_kind,'evidence_update');assert.equal(calls[0].body.state,'candidate');assert.equal(calls[0].body.previous_valid_until,undefined);
});
test('upload visibility is explicit metadata; unknown preserves legacy payload',async()=>{
  for(const visibility of ['unknown','visible_only','complete_visible']){
    const {$,calls}=setup();$('material').value='Synthetic visible text.';$('source-visibility').value=visibility;
    await $('ingest-form').emit('submit');const body=calls[0].body;
    assert.equal(body.source_metadata.visibility,visibility==='unknown'?undefined:visibility);
    assert.equal(body.processing_policy,'archive');assert.equal(body.scope,'personal');
    assert.equal(body.source_metadata.attachments_verified,undefined);
  }
});

test('source state details expose unknown method and literal failure safely',()=>{
  const {ui}=setup();assert.equal(ui.methodLabel(undefined),'提炼方法未记录');
  assert.equal(ui.methodLabel('legacy'),'提炼方法未记录');assert.equal(ui.methodLabel('v21'),'提炼方法 v21');
  const detail=ui.failureDetail('<img src=x onerror=alert(1)>');
  assert.equal(detail.children[0].textContent,'失败原因');assert.equal(detail.children[1].textContent,'<img src=x onerror=alert(1)>');
  assert.match(ui.failureDetail('').children[1].textContent,/未返回/);
});

test('actual material renderer labels extraction honestly and renders failure without HTML',async()=>{
  const base={created:0,message_count:1,scope:'personal',preview:'Synthetic.',method_version:'legacy',claim_count:0};
  const {$,ui}=setup({'/api/inside/memory-center/v1/materials':{total:3,materials:[
    {...base,id:'a',title:'A',state:'archived'}, {...base,id:'b',title:'B',state:'applied'},
    {...base,id:'c',title:'C',state:'failed',error:'<script>synthetic</script>'}]}});
  ui.setIdentity({can_correct:true});await ui.refreshMaterials(true);
  const cards=$('materials-list').children;assert.equal(cards.length,3);
  assert.ok(find(cards[0],e=>e.textContent==='提炼方法未记录'));
  assert.ok(find(cards[1],e=>e.textContent==='提炼完成 · 0 条抽取记录'));
  assert.ok(find(cards[1],e=>/不代表质量/.test(e.textContent||'')));
  assert.ok(find(cards[2],e=>e.textContent==='<script>synthetic</script>'));
  assert.ok(find(cards[2],e=>e.textContent==='再次提炼并比较'));
});

test('registering an entity refreshes an open review without queued close invalidating its epoch',async()=>{
  const {$,calls,ui}=setup({'/api/inside/memory-center/v1/entities':{entities:[{id:'owner',name:'Synthetic owner'},{id:'project:atlas',name:'Atlas'}]}},{'/api/inside/memory-center/v1/entities':{id:'project:atlas'}});
  ui.setIdentity({can_correct:true});await ui.reviewRecord({id:'synthetic',statement:'Synthetic.',quote:'Synthetic.',governance:{revision:1,state:'candidate'}});
  let closeCalls=0;$('review-dialog').close=()=>{closeCalls++;$('review-dialog').open=false;};
  const registry=find($('review-content'),e=>e.tagName==='details');const entityForm=form(registry);
  entityForm.children[0].value='project:atlas';entityForm.children[1].value='Atlas';entityForm.children[2].value='project';
  await entityForm.emit('submit');assert.equal(closeCalls,0);assert.equal($('review-dialog').open,true);
  field($('review-content'),'治理状态').value='verified';await form($('review-content')).emit('submit');
  assert.equal(calls[1].url,'/api/inside/memory-center/v1/records/synthetic/governance');
  assert.equal(calls[1].body.state,'verified');assert.equal($('review-notice').hidden,false);assert.match($('review-notice').textContent,/007/);
});

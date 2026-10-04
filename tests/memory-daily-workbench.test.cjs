// Explicitly synthetic DOM and transport. No server or model calls.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {webcrypto}=require('node:crypto');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.attrs={};this.value='';this.hidden=false;this.selectedOptions=[{textContent:'Synthetic scope'}];this.classList={add(){},remove(){}};}
  append(...items){this.children.push(...items);} prepend(...items){this.children.unshift(...items);} before(){} after(){}
  replaceChildren(...items){this.children=items;} setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  contains(item){return this===item||this.children.some(c=>c.contains?.(item));}
  querySelectorAll(){return [];} showModal(){this.open=true;} close(){this.open=false;}
  async emit(kind){for(const fn of this.listeners[kind]||[])await fn({preventDefault(){},submitter:this});}
  dispatchEvent(e){this.emit(e.type);return true;}
}
function setup({overview={},budget={},transport}={}){
  const ids=new Map(),$=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
  $('scope').value='personal';$('ingest-scope').value='personal';
  const calls=[],gets=[],window={addEventListener(){}};
  const responses={records:{total:0,records:[],jobs:[]},documents:{documents:[]},overview:{sources:0,candidates:0,usable:0,historical:0,...overview},budget:{tokens_spent:100,token_limit:100,quality_approved:false,unresolved_attempts:0,note:'',...budget},'extraction-runs':{runs:[]},materials:{total:0,materials:[]}};
  const context={document:{getElementById:$,createElement:t=>new Element(t),querySelectorAll:()=>[],querySelector:()=>null},window,
    location:{hash:''},Event:class {constructor(type){this.type=type;}},URLSearchParams,TextEncoder,crypto:webcrypto,MemoryFiles:require('../assets/memory-files.js'),setInterval:()=>1,clearInterval(){},fetch:async(url,options)=>{
      if(options.method==='GET'){gets.push(url);const value=transport?await transport(url,responses):responses[new URL(url,'http://synthetic').pathname.split('/').pop()];return {ok:true,json:async()=>value||{}};}
      calls.push({url,body:JSON.parse(options.body)});return {ok:false,json:async()=>({error:'Synthetic rejection'})};
    }};
  let script=fs.readFileSync(require.resolve('../assets/memory-center.js'),'utf8');
  script=script.replace(/  connect\(\);\n\}\)\(\);\s*$/, '  window.testUI={refresh,refreshOverview,refreshBudget,setIdentity:p=>identity=p};\n})();');
  vm.runInNewContext(script,context);return {$,calls,gets,ui:window.testUI};
}
function find(root,predicate){if(predicate(root))return root;for(const child of root.children){const result=find(child,predicate);if(result)return result;}}
const identity={can_correct:true,actions:['read','write'],scopes:['personal','claude:history-synthetic']};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('personal shortcut cannot write into the history currently being viewed',async()=>{
  const {$,ui,calls}=setup();ui.setIdentity(identity);$('scope').value='claude:history-synthetic';$('history').checked=true;$('query').value='old search';
  await $('daily-owner-add').emit('click');await flush();assert.equal($('scope').value,'personal');assert.equal($('history').checked,false);assert.equal($('query').value,'');
  const host=$('review-content'),statement=find(host,e=>e.attrs['aria-label']==='陈述正文');statement.value='Synthetic present preference.';
  await find(host,e=>e.tagName==='form').emit('submit');assert.equal(calls[0].body.scope,'personal');assert.equal(calls[0].body.governance.state,'candidate');assert.match($('notice').textContent,/Synthetic rejection/);
});
test('read-only client cannot invoke the personal-owner shortcut',async()=>{
  const {$,ui,calls}=setup();ui.setIdentity({...identity,can_correct:false,actions:['read']});await $('daily-owner-add').emit('click');assert.equal($('review-dialog').open,undefined);assert.equal(calls.length,0);
});
test('archive shortcut resets extract choice without enqueueing a model job',async()=>{
  const {$,ui,calls}=setup();ui.setIdentity(identity);$('processing-policy').value='extract';await $('daily-upload').emit('click');assert.equal($('processing-policy').value,'archive');assert.equal(calls.length,0);
});
test('exhausted budget still explicitly allows archive/manual/review paths',async()=>{
  const {$,ui}=setup();ui.setIdentity(identity);await ui.refreshBudget();assert.match($('daily-status').textContent,/已达到上限/);assert.match($('daily-status').textContent,/归档、手动补充和核实仍可使用/);assert.notEqual($('daily-owner-add').disabled,true);
});
test('empty personal guide distinguishes candidates from usable context',async()=>{
  const {$,ui}=setup({overview:{candidates:3,usable:0}});ui.setIdentity(identity);await ui.refreshOverview();assert.equal($('personal-start').hidden,false);assert.match($('personal-start').textContent,/3 条候选/);assert.match($('personal-start').textContent,/才可供 Agent/);
  $('scope').value='claude:history-synthetic';await ui.refreshOverview();assert.equal($('personal-start').hidden,true);
});
test('scope switch during an active refresh schedules fresh scope instead of dropping it',async()=>{
  let release;const gate=new Promise(resolve=>release=resolve);let first=true;
  const {$,ui,gets}=setup({transport:async(url,responses)=>{if(url.includes('/records?')&&first){first=false;await gate;}return responses[new URL(url,'http://synthetic').pathname.split('/').pop()];}});ui.setIdentity(identity);
  $('scope').value='claude:history-synthetic';const active=ui.refresh();$('scope').value='personal';await ui.refresh();release();await active;await flush();
  assert.ok(gets.some(url=>url.includes('/records?scope=personal')));assert.equal($('count').textContent,'0');assert.equal($('notice').dataset.error,undefined);
});

// Synthetic transport and DOM. Runs real UI handlers without a server or model.
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {webcrypto}=require('node:crypto');
class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.attrs={};this.style={};this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.classList={add(){},remove(){}};}
  append(...items){this.children.push(...items);} prepend(...items){this.children.unshift(...items);} before(){} after(){}
  replaceChildren(...items){this.children=items;} setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);}
  contains(item){return this===item||this.children.some(c=>c.contains?.(item));}
  querySelectorAll(){return [];} showModal(){this.open=true;} close(){this.open=false;}
  async emit(kind){for(const fn of this.listeners[kind]||[])await fn({preventDefault(){},submitter:this});}
}
const prefix='/api/inside/memory-center/v1';
const owner={can_correct:true,can_manage_agents:true,actions:['read','write','source_read'],scopes:['personal','agent:synthetic-inbox']};
function setup(responses={}){
  const ids=new Map(),$=id=>{if(!ids.has(id))ids.set(id,new Element());return ids.get(id);};
  $('scope').value='agent:synthetic-inbox';
  const calls=[],window={addEventListener(){}};
  const context={document:{getElementById:$,createElement:t=>new Element(t),querySelectorAll:()=>[],querySelector:()=>null},window,
    location:{hash:''},URLSearchParams,TextEncoder,crypto:webcrypto,MemoryFiles:require('../assets/memory-files.js'),setInterval:()=>1,clearInterval(){},fetch:async(url,options)=>{
      const target=new URL(url,'http://synthetic'),body=options.body?JSON.parse(options.body):undefined;
      calls.push({url,method:options.method,body});
      const known=responses[options.method+' '+target.pathname]??responses[target.pathname];
      const value=typeof known==='function'?await known({target,body}):await known;
      return {ok:!value?.error,json:async()=>value??{credentials:[],entities:[]}};
    }};
  let script=fs.readFileSync(require.resolve('../assets/memory-center.js'),'utf8');
  script=script.replace(/  connect\(\);\n\}\)\(\);\s*$/,'  window.testUI={manageAgents,refreshIntake,openIntakeRecord,clearIntake,intakePanel,intakeSummary,intakeList,intakeMore,intakePrevious,setIdentity:p=>identity=p};\n})();');
  vm.runInNewContext(script,context);window.testUI.setIdentity(owner);return {$,calls,ui:window.testUI};
}
function find(root,predicate){if(predicate(root))return root;for(const child of root.children){const result=find(child,predicate);if(result)return result;}}
const field=(root,label)=>find(root,e=>e.attrs?.['aria-label']===label);
const receipt={id:'receipt-synthetic',source_id:'source-synthetic',principal:'synthetic-writer',count:1,created:0,source_state:'active',record_ids:['record-synthetic'],records:[{id:'record-synthetic',state:'candidate',lifecycle:'active'}]};
const listing={supported:true,receipts:[receipt],total:1,offset:0,limit:20,next_offset:null};
const record={id:'record-synthetic',scope:'agent:synthetic-inbox',source_id:'source-synthetic',message_id:'synthetic-message',statement:'Synthetic source-backed statement.',quote:'Synthetic source-backed statement.',topic:'topics',kind:'claim',subject:'unknown',revision:1,lifecycle:'active',governance:{state:'candidate',revision:1,priority:'P3'}};

test('receipt shows current scope and candidate status as text, with ledger and review actions',async()=>{
  const {ui,calls}=setup({[prefix+'/candidate-intake']:{...listing,receipts:[{...receipt,principal:'<script>synthetic</script>'}]}});
  await ui.refreshIntake();assert.match(ui.intakeSummary.textContent,/agent:synthetic-inbox.*共 1 批/);
  assert.ok(find(ui.intakeList,e=>e.textContent?.includes('<script>synthetic</script>')));
  assert.ok(find(ui.intakeList,e=>e.textContent==='待核实'));
  for(const label of ['来源账本','记录账本','核实 / 标记','补充 / 修改'])assert.ok(find(ui.intakeList,e=>e.textContent===label));
  assert.equal(ui.intakeMore.hidden,true);assert.equal(calls.length,1);assert.equal(calls[0].method,'GET');
});
test('missing migration, API errors and empty receipts never imply processing is complete',async()=>{
  for(const data of [{supported:false,total:null,migration_required:'010_candidate_intake'},{error:'Synthetic unavailable'},{...listing,receipts:[],total:0}]){
    const {ui}=setup({[prefix+'/candidate-intake']:data});await ui.refreshIntake();
    if(data.supported===false){assert.match(ui.intakeSummary.textContent,/010/);assert.equal(ui.intakeSummary.dataset.error,'true');}
    else if(data.error)assert.match(ui.intakeSummary.textContent,/Synthetic unavailable/);
    else assert.ok(find(ui.intakeList,e=>/不代表资料已处理完成/.test(e.textContent||'')));
    assert.equal(ui.intakeMore.hidden,true);
  }
});
test('receipt pagination is bounded and scope changes invalidate delayed replies',async()=>{
  const {ui,calls}=setup({[prefix+'/candidate-intake']:({target})=>({...listing,offset:Number(target.searchParams.get('offset')),total:21,next_offset:target.searchParams.get('offset')==='0'?20:null})});
  await ui.refreshIntake();await ui.intakeMore.emit('click');
  assert.match(calls[1].url,/offset=20&limit=20/);assert.equal(ui.intakePrevious.hidden,false);assert.equal(ui.intakeMore.hidden,true);
  let done;const pending=new Promise(resolve=>done=resolve);const next=setup({[prefix+'/candidate-intake']:pending});
  const wait=next.ui.refreshIntake();next.$('scope').value='personal';next.ui.clearIntake();done(listing);await wait;
  assert.equal(next.ui.intakeList.children.length,0);assert.doesNotMatch(next.ui.intakeSummary.textContent,/共 1 批/);
});
test('receipt review fetches fresh scoped record and never confirms it on opening',async()=>{
  const {$,ui,calls}=setup({[prefix+'/records/record-synthetic']:{record}});
  await ui.openIntakeRecord('record-synthetic','agent:synthetic-inbox','review');
  assert.match(calls[0].url,/records\/record-synthetic\?scope=agent%3Asynthetic-inbox/);
  assert.equal(field($('review-content'),'治理状态').value,'candidate');
  assert.equal(field($('review-content'),'何时成立').value,'');assert.equal(field($('review-content'),'谁认为').value,'');
  assert.ok(calls.every(c=>c.method==='GET'));assert.equal($('review-dialog').open,true);
});
test('receipt revision uses existing owner form and defaults to candidate',async()=>{
  const {$,ui,calls}=setup({[prefix+'/records/record-synthetic']:{record},['POST '+prefix+'/records/record-synthetic/revise']:{error:'Synthetic save rejected'}});
  await ui.openIntakeRecord('record-synthetic','agent:synthetic-inbox','edit');
  const host=$('review-content');assert.equal(field(host,'陈述正文').value,record.statement);
  await find(host,e=>e.tagName==='form').emit('submit');const post=calls.find(c=>c.method==='POST');
  assert.equal(post.body.governance.state,'candidate');assert.equal(post.body.revision,1);assert.equal(post.body.scope,record.scope);
  assert.equal(post.body.governance.as_of,null);assert.match($('notice').textContent,/Synthetic save rejected/);
});
test('upstream review displays source role and Unicode location without inferring the holder',async()=>{
  const detail={...record,candidate_intake:{message_role:'assistant',quote_start:0,quote_end:9,receipt_id:'receipt-synthetic',principal:'<img src=synthetic>'}};
  const {$,ui,calls}=setup({[prefix+'/records/record-synthetic']:{record:detail}});
  await ui.openIntakeRecord(record.id,record.scope,'review');const host=$('review-content');
  assert.ok(find(host,e=>e.textContent==='原文角色：AI 助手消息'));
  assert.ok(find(host,e=>/原文位置：0–9.*Unicode/.test(e.textContent||'')));
  assert.ok(find(host,e=>e.textContent?.includes('<img src=synthetic>')));
  assert.equal(field(host,'谁认为').value,'');assert.equal(field(host,'治理状态').value,'candidate');
  assert.ok(calls.every(call=>call.method==='GET'));
});
test('withdrawn or superseded receipts keep ledger access without edit actions',async()=>{
  for(const change of [{source_state:'withdrawn'},{records:[{id:'record-synthetic',state:'candidate',lifecycle:'superseded'}]}]){
    const {ui}=setup({[prefix+'/candidate-intake']:{...listing,receipts:[{...receipt,...change}]}});await ui.refreshIntake();
    assert.ok(find(ui.intakeList,e=>e.textContent==='记录账本'));assert.equal(find(ui.intakeList,e=>e.textContent==='核实 / 标记'),undefined);
    assert.equal(find(ui.intakeList,e=>e.textContent==='补充 / 修改'),undefined);
  }
  const {ui}=setup({[prefix+'/records/record-synthetic']:{record:{...record,source_withdrawn:true}}});
  await assert.rejects(ui.openIntakeRecord(record.id,record.scope,'review'),/撤回或被更正/);
});
test('delayed record detail cannot reopen review in another scope or after close',async()=>{
  let done;const response=new Promise(resolve=>done=resolve);const {$,ui}=setup({[prefix+'/records/record-synthetic']:response});
  const pending=ui.openIntakeRecord(record.id,record.scope,'review');$('scope').value='personal';done({record});await pending;
  assert.equal($('review-dialog').open,undefined);
  const other=setup({[prefix+'/records/record-synthetic']:{record:{...record,scope:'personal'}}});
  await assert.rejects(other.ui.openIntakeRecord(record.id,record.scope,'review'),/详情不完整/);
  let closeDone;const closeResponse=new Promise(resolve=>closeDone=resolve);const closed=setup({[prefix+'/records/record-synthetic']:closeResponse});
  const closePending=closed.ui.openIntakeRecord(record.id,record.scope,'review');await closed.$('review-close').emit('click');closeDone({record});await closePending;
  assert.equal(closed.$('review-dialog').open,false);
});
test('a receipt request error from an older page cannot replace the latest page',async()=>{
  let complete;const first=new Promise(resolve=>complete=resolve);const {ui}=setup({[prefix+'/candidate-intake']:({target})=>target.searchParams.get('offset')==='0'?first:{...listing,offset:20,total:21}});
  const old=ui.refreshIntake(0);await ui.refreshIntake(20);complete({error:'Synthetic stale page failure'});await old;
  assert.match(ui.intakeSummary.textContent,/共 21 批/);assert.equal(ui.intakeSummary.dataset.error,'false');assert.equal(ui.intakePrevious.hidden,false);
});
test('candidate credential is opt-in, inbox-only and includes required source permissions',async()=>{
  const {$,ui,calls}=setup();await ui.manageAgents();const host=$('review-content'),scope=field(host,'授权范围'),candidate=field(host,'允许提交候选（需原文证据）');
  assert.equal(scope.value,'personal');assert.equal(candidate.checked,false);assert.equal(candidate.disabled,true);
  scope.value='agent:synthetic-inbox';await scope.emit('change');assert.equal(candidate.disabled,false);
  candidate.checked=true;await candidate.emit('change');assert.equal(field(host,'允许查看原文').checked,true);assert.equal(field(host,'允许归档到独立收件箱').checked,true);
  await find(host,e=>e.tagName==='form').emit('submit');const post=calls.find(c=>c.method==='POST');
  assert.deepEqual(post.body.actions,['read','source_read','write','candidate_write']);assert.deepEqual(post.body.scopes,['agent:synthetic-inbox']);
  field(host,'允许查看原文').checked=false;await field(host,'允许查看原文').emit('change');assert.equal(candidate.checked,false);
  scope.value='personal';await scope.emit('change');assert.equal(candidate.disabled,true);assert.equal(field(host,'允许归档到独立收件箱').checked,false);
});
test('existing archive writer stays archive-only and read-only owner cannot grant candidate writes',async()=>{
  const {$,ui,calls}=setup();await ui.manageAgents();const host=$('review-content');field(host,'授权范围').value='agent:synthetic-inbox';await field(host,'授权范围').emit('change');field(host,'允许归档到独立收件箱').checked=true;
  await find(host,e=>e.tagName==='form').emit('submit');assert.deepEqual(calls.find(c=>c.method==='POST').body.actions,['read','write']);
  const other=setup();other.ui.setIdentity({...owner,actions:['read','source_read']});await other.ui.manageAgents();const otherHost=other.$('review-content');field(otherHost,'授权范围').value='agent:synthetic-inbox';await field(otherHost,'授权范围').emit('change');assert.equal(field(otherHost,'允许提交候选（需原文证据）').disabled,true);
  field(otherHost,'允许提交候选（需原文证据）').checked=true;await find(otherHost,e=>e.tagName==='form').emit('submit');assert.equal(other.calls.filter(c=>c.method==='POST').length,0);
  assert.match(other.$('notice').textContent,/原文读取和归档权限/);
});

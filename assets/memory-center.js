'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const prefix = '/api/inside/memory-center/v1';
  let token = '', identity = null, timer = null, refreshing = false, pendingJobs = false;
  let fileName='', fileRead=0, activeBatch=null, materialOffset=0;
  const labels = {user_stated:'本人陈述 · 模型提炼', source_reported:'来源陈述', imported_summary:'导入摘要',agent_suggested:'AI 发言 · 未经本人确认',active:'可检索',superseded:'已被纠正',received:'待整理',processing:'正在提炼',applied:'已应用',failed:'失败',profile:'个人',preferences:'偏好',people:'人物',areas:'领域',projects:'项目',topics:'主题'};
  function notice(message, error=false) { $('notice').hidden=!message; $('notice').textContent=message; $('notice').dataset.error=String(error); }
  async function api(path, body) {
    const response = await fetch(prefix+path,{method:body===undefined?'GET':'POST',headers:{...(token?{Authorization:'Bearer '+token}:{'X-Memory-Local':'1'}),'Content-Type':'application/json'},cache:'no-store',body:body===undefined?undefined:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败');
    return data;
  }
  function node(tag,text,cls) { const el=document.createElement(tag); if(text!==undefined) el.textContent=text; if(cls)el.className=cls; return el; }
  function batchView(batch, sourceBatch) {
    const host=$('bulk-controls'), actions=$('bulk-actions');host.hidden=false;actions.replaceChildren();
    if(!batch){
      $('bulk-state').textContent='已归档，可建立全量提炼计划。';
      $('bulk-metrics').replaceChildren();$('bulk-budget').textContent='模型用量上限：1,000,000 tokens。先处理 10 个对话片段估算，随后自动继续；达到上限就暂停。';
      $('bulk-errors').textContent='';
      if(sourceBatch && identity?.can_correct){const start=node('button','提炼全部历史','primary');start.addEventListener('click',async()=>{start.disabled=true;try{await api('/archives/'+sourceBatch.id+'/bulk',{token_limit:1000000});await refreshArchives();}catch(err){notice(err.message,true);start.disabled=false;}});actions.append(start);}
      return;
    }
    const names={running:'正在提炼',paused:'已暂停',paused_error:'连接失败，已暂停',paused_budget:'达到用量上限',completed:'全部完成',completed_with_errors:'已完成，部分失败'};
    const count=batch.counts||{},done=(count.applied||0)+(count.failed||0);
    $('bulk-state').textContent=(names[batch.state]||batch.state)+' · '+done+' / '+batch.total_segments+' 个片段完成 · '+batch.total_conversations+' 段对话，'+batch.no_text_conversations+' 段没有可提炼文本 · '+batch.memory_documents+' 份已有记忆资料';
    $('bulk-metrics').replaceChildren(...[['planned','待入队'],['queued','处理中'],['applied','已完成'],['failed','失败']].map(([key,title])=>{const box=node('div',undefined,'job-metric');box.append(node('strong',String(count[key]||0)),node('span',title));return box;}));
    $('bulk-budget').textContent='已计量及在途预留 '+batch.tokens_spent.toLocaleString()+' / '+batch.token_limit.toLocaleString()+' tokens · 样本 '+batch.sample_done+'/'+batch.sampled_segments+' 个'+(batch.estimated_total_tokens?' · 全量预估约 '+batch.estimated_total_tokens.toLocaleString()+' tokens':'。预估会在样本完成后显示。')+'。未返回用量的失败任务按 35,000 tokens 预留。';
    $('bulk-errors').textContent=batch.recent_errors?.length?'最近失败：'+batch.recent_errors.map(x=>x.conversation_id.slice(0,8)+' / '+x.segment_index+' · '+(x.error||'未提供原因')).join('；'):'';
    const operate=(label,action)=>{const button=node('button',label,action==='resume'?'primary':undefined);button.addEventListener('click',async()=>{button.disabled=true;try{await api('/bulk/'+batch.id+'/control',{action});await refreshArchives();}catch(err){notice(err.message,true);button.disabled=false;}});actions.append(button);};
    if(batch.state==='running')operate('暂停新任务','pause');
    if(batch.state==='paused')operate('继续处理','resume');
    if((count.failed||0)>0 && batch.state!=='paused_budget')operate('重试一项失败任务','retry_failed');
    if(batch.state==='paused_error')$('bulk-errors').textContent='连接模型失败后已暂停，避免继续空转消耗预算。请检查模型服务，再点击重试。'+($('bulk-errors').textContent?' '+$('bulk-errors').textContent:'');
    if(batch.state==='paused_budget' && identity?.can_correct){
      const amount=node('input');amount.type='number';amount.min=String(batch.token_limit+35000);amount.max='100000000';amount.step='1000';amount.value=String(Math.min(100000000,batch.token_limit+1000000));amount.setAttribute('aria-label','新的累计 token 上限');
      const button=node('button','提高上限并继续','primary');button.addEventListener('click',async()=>{button.disabled=true;try{await api('/bulk/'+batch.id+'/control',{action:'set_limit',token_limit:Number(amount.value)});await refreshArchives();}catch(err){notice(err.message,true);button.disabled=false;}});actions.append(amount,button);
    }
  }
  async function refreshMaterials(reset=false){
    if(reset){materialOffset=0;$('materials-list').replaceChildren();}
    const data=await api('/materials?'+new URLSearchParams({offset:materialOffset}));
    $('materials-summary').textContent='已保存 '+data.total+' 份独立资料'+(activeBatch?'，另有 Claude 全量归档':'')+' · 保留原文，提炼结果可回查。';
    if(reset && activeBatch){
      const card=node('article',undefined,'record topic-tile'),count=activeBatch.counts||{};
      card.append(node('h3','Claude 全量对话与记忆归档'),node('p',activeBatch.total_conversations+' 段对话 · '+activeBatch.memory_documents+' 份原有记忆资料','muted'),node('span',(count.applied||0)+' / '+activeBatch.total_segments+' 段完成 · '+(count.failed||0)+' 段失败','tag'));
      const link=node('button','查看归档与进度','primary');link.addEventListener('click',()=>{location.hash='archives';showView();});card.append(link);$('materials-list').append(card);
    }
    if(reset && !data.total && !activeBatch)$('materials-list').append(node('p','尚未提交资料。','muted'));
    for(const item of data.materials){
      const card=node('article',undefined,'record topic-tile');
      card.append(node('h3',item.title||'未命名资料'),node('p',new Date(item.created*1000).toLocaleString('zh-CN')+' · '+item.message_count+' 段内容 · '+item.scope,'muted'));
      const state=item.state==='archived'?'原文已归档 · 未调用模型':item.state==='applied'?'已完成提炼 · '+item.claim_count+' 条记忆':item.state==='failed'?'处理失败':item.state==='processing'?'正在提炼':'等待处理';
      card.append(node('span',state,'tag'),node('p',item.preview||'无文字预览','material-preview'));
      if(item.method_version!=='legacy')card.append(node('p','提炼方法 '+item.method_version,'muted'));
      const buttons=node('div',undefined,'tile-actions'),read=node('button','查看原文');
      read.addEventListener('click',async()=>{read.disabled=true;try{const raw=await api('/materials/'+item.id);openDocument(item.title||'原始资料',raw.messages.map(m=>'['+m.role+'] '+m.text).join('\n\n'));}catch(err){notice(err.message,true);}finally{read.disabled=false;}});buttons.append(read);
      if(item.state==='failed' && item.job_id){const retry=node('button','重试整理','primary');retry.addEventListener('click',async()=>{retry.disabled=true;try{await api('/jobs/'+item.job_id+'/retry',{});await refreshMaterials(true);}catch(err){notice(err.message,true);retry.disabled=false;}});buttons.append(retry);}
      card.append(buttons);$('materials-list').append(card);
    }
    materialOffset+=data.materials.length;$('materials-more').hidden=materialOffset>=data.total;
  }
  async function refreshArchives() {
    const data=await api('/archives?'+new URLSearchParams({q:$('archive-query').value}));
    const bulk=await api('/bulk');activeBatch=bulk.batches[0]||null;
    $('archive-summary').textContent=data.batches.length?data.batches.map(b=>b.file_count+' 个原始文件 · '+(Number(b.source_bytes)/1048576).toFixed(1)+' MB · COS 已校验归档').join('；'):data.message||'尚无归档';
    batchView(activeBatch,data.batches[0]);
    $('archive-list').replaceChildren();
    for(const c of data.conversations) {
      const card=node('article',undefined,'record topic-tile');
      card.append(node('h3',c.title||'未命名对话'),node('p',c.message_count+' 条消息 · '+(c.original_created_at||'日期未记录').slice(0,10),'muted'),node('span',({not_processed:'原文已归档',processing:'正在整理',processed:'已整理',failed:'部分失败'})[c.extraction_state]||'原文已归档','tag'));
      if(identity?.can_correct){const preview=node('button','预览原文');preview.addEventListener('click',async()=>{preview.disabled=true;try{const data=await api('/archives/conversations/'+encodeURIComponent(c.conversation_id)+'/preview');openDocument(data.title||c.title,data.available?data.text+(data.truncated?'\n\n（仅预览前 12,000 字，原始归档完整保留）':''):'这段对话没有可提炼的文字。');}catch(err){notice(err.message,true);}finally{preview.disabled=false;}});card.append(preview);}
      $('archive-list').append(card);
    }
  }
  $('archive-search-form').addEventListener('submit',async e=>{e.preventDefault();try{await refreshArchives();}catch(err){notice(err.message,true);}});
  async function refreshDocuments() {
    const scope=$('scope').value, activeToken=token;
    const data=await api('/documents?'+new URLSearchParams({scope,q:$('document-query').value}));
    if(!identity || token!==activeToken || scope!==$('scope').value) return;
    $('documents').replaceChildren();
    if(!data.documents.length) $('documents').append(node('p','此范围尚无匹配的主题文档。','muted'));
    for(const doc of data.documents) {
      const block=node('article',undefined,'record topic-tile');
      block.append(node('h3',doc.title),node('p','v'+doc.revision+' · '+doc.claims+' 项陈述','muted'));
      const excerpt=doc.markdown.split('\n').find(line=>line.startsWith('- ')&&!line.startsWith('- 标题'));
      block.append(node('p',excerpt?excerpt.slice(2):'打开查看陈述、变化与原文依据。','tile-excerpt'));
      const read=node('button','阅读文档','primary');read.addEventListener('click',()=>openDocument(doc.title,doc.markdown));
      const changes=node('button','版本变化');changes.addEventListener('click',()=>openDocument(doc.title+' · v'+doc.revision,doc.changes||'无变化'));
      const download=node('button','下载 MD');download.addEventListener('click',()=>{
        const url=URL.createObjectURL(new Blob([doc.markdown],{type:'text/markdown;charset=utf-8'}));
        const link=node('a');link.href=url;link.download=doc.slug+'.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      });
      const actions=node('div',undefined,'tile-actions');actions.append(read,changes,download);block.append(actions);$('documents').append(block);
    }
  }
  async function refresh() {
    if(!identity || refreshing) return;
    refreshing=true;
    const requestedToken=token, requestedScope=$('scope').value;
    try {
      const params=new URLSearchParams({scope:$('scope').value,q:$('query').value,history:$('history').checked?'1':'0'});
      const data=await api('/records?'+params);
      if(token!==requestedToken || !identity || $('scope').value!==requestedScope) return;
      await refreshDocuments();
      if(token!==requestedToken || !identity || $('scope').value!==requestedScope) return;
      pendingJobs=data.jobs.some(j=>j.state==='received'||j.state==='processing');
      $('count').textContent=String(data.total);
      const breakdown=data.status_counts||{};
      $('record-breakdown').textContent='当前范围：'+$('scope').selectedOptions[0].textContent+' · 原话提炼 '+(breakdown.source_reported||0)+' · AI 发言 '+(breakdown.agent_suggested||0)+' · 旧摘要 '+(breakdown.imported_summary||0)+' · 本人确认 '+(breakdown.user_stated||0)+'。抽取记录不等于已确认的长期记忆。';
      $('records').replaceChildren(); $('jobs').replaceChildren();
      if(!data.records.length) $('records').append(node('p','还没有匹配的记忆。提交材料后，管家会在这里留下理解与依据。','empty'));
      if(data.truncated) $('records').append(node('p','当前展示前 100 条，请缩小搜索范围。','muted'));
      for(const r of data.records) {
        const card=node('article',undefined,'record memory-tile');card.dataset.topic=r.topic;card.dataset.status=r.status;card.dataset.lifecycle=r.lifecycle;
        [labels[r.topic]||r.topic,r.message_id==='correction'?'本人明确纠正':(labels[r.status]||r.status),labels[r.lifecycle]||r.lifecycle,'v'+r.revision,...(r.source_date?[r.source_date.slice(0,10)]:[]),...(r.processing_method==='session_agent'?['会话 Agent 整理']:r.processing_method==='llm'?['后台模型提炼']:[])].forEach(t=>card.append(node('span',t,'tag')));
        card.append(node('p',({user:'本人',assistant:'AI 助手'}[r.subject]||r.subject),'muted'),node('p',r.statement,'statement'));
        if(r.governance){const g=r.governance;const states={candidate:'待核实候选',verified:'已核实',historical:'历史判断',rejected:'不采纳',owner_corrected:'本人纠正'};card.append(node('p',(states[g.state]||g.state)+' · '+g.priority+' · 成立时间：'+(g.as_of||'未知'),'muted'));}
        if(r.review_note) card.append(node('p','与旧记忆对照：'+r.review_note,'muted'));
        const details=node('details'); details.append(node('summary','查看原文证据与来源'),node('blockquote',r.quote),node('p','来源：'+(r.source_title||r.source_id)+' · '+(r.source_date||'时间未记录')+' / '+(r.source_key||r.source_id)+' / 消息 '+r.message_id,'muted'));card.append(details);
        if(identity.can_correct && identity.actions.includes('write') && r.lifecycle==='active') {
          const button=node('button','纠正这条理解'); button.style.marginTop='12px';
          button.addEventListener('click',()=>{
            button.hidden=true;
            const form=node('form'),input=node('textarea'); input.value=r.statement;input.maxLength=2000;input.required=true;input.setAttribute('aria-label','纠正后的记忆');
            const submit=node('button','保存新版本','primary'),cancel=node('button','取消');cancel.type='button';cancel.addEventListener('click',()=>{form.remove();button.hidden=false;});
            form.append(input,submit,cancel);card.append(form); input.focus();
            form.addEventListener('submit',async e=>{e.preventDefault();submit.disabled=true;try {await api('/records/'+r.id+'/correct',{statement:input.value,revision:r.revision});notice('已保存新版本，旧内容可在历史中查看。');await refresh();}catch(err){notice(err.message,true);submit.disabled=false;}});
          });card.append(button);
        }
        $('records').append(card);
      }
      applyFilters();
      $('job-summary').replaceChildren(...['received','processing','applied','failed'].map(state=>{const box=node('div',undefined,'job-metric');box.dataset.state=state;box.append(node('strong',String(data.jobs.filter(j=>j.state===state).length)),node('span',labels[state]));return box;}));
      if(!data.jobs.length) $('jobs').append(node('p','暂无任务','muted'));
      for(const j of data.jobs) {
        const row=node('article',undefined,'job');row.dataset.state=j.state;row.append(node('h3',j.source_title||'整理任务'));row.append(node('span',labels[j.state]||j.state,'tag'),node('span',j.id.slice(0,8)+' · 尝试 '+j.attempts+' 次'));
        const steps=node('ol',undefined,'job-steps');
        ['received','processing','applied'].forEach((step,i)=>{const item=node('li',labels[step]);const stage=['received','processing','applied'].indexOf(j.state);item.dataset.done=String(i<=stage);steps.append(item);});
        row.append(steps);
        if(j.state==='failed')row.append(node('p','处理未完成，查看错误后可重试。','muted'));
        if(j.usage?.method==='session_agent') row.append(node('p','由本次会话 Agent 阅读原文整理；未调用后台模型，未单独计量 token。','muted'));
        else if(j.usage) row.append(node('p','本次返回的 token：输入 '+(j.usage.prompt_tokens??'未知')+' / 输出 '+(j.usage.completion_tokens??'未知'),'muted'));
        if(j.error) row.append(node('p',j.error));
        if(j.state==='failed' && identity.actions.includes('write')) {
          if(j.source_key?.startsWith('claude:archive:')){const link=node('button','在原始资料中处理');link.addEventListener('click',()=>{location.hash='archives';showView();});row.append(link);}
          else {const retry=node('button','重试');retry.addEventListener('click',async()=>{retry.disabled=true;try{await api('/jobs/'+j.id+'/retry',{});await refresh();}catch(err){notice(err.message,true);retry.disabled=false;}});row.append(retry);}
        }
        $('jobs').append(row);
      }
    } catch(err){notice(err.message,true);} finally{refreshing=false;}
  }
  async function connect() {
    try {
      identity=await api('/status'); $('token').value='';
      $('scope').replaceChildren(...identity.scopes.map(s=>{const o=node('option',s==='claude:sample-20260929'?'Claude 历史示范 · 2026-09-29':s==='claude:ark-20260929'?'Claude · 火山自动提炼':s==='claude:history-20260929'?'Claude · 历史批量整理':s);o.value=s;return o;}));
      $('ingest-scope').replaceChildren(...identity.scopes.filter(s=>s!=='claude:archive').map(s=>{const o=node('option',s==='personal'?'个人记忆':s==='claude:history-20260929'?'Claude 历史批量整理':s);o.value=s;return o;}));
      if(identity.scopes.includes('personal'))$('ingest-scope').value='personal';
      const requestedScope=new URLSearchParams(location.search).get('scope');
      if(identity.scopes.includes(requestedScope)) $('scope').value=requestedScope;
      else if(identity.scopes.includes('claude:history-20260929')) $('scope').value='claude:history-20260929';
      else if(identity.scopes.includes(identity.default_scope)) $('scope').value=identity.default_scope;
      updateSpaceLabel();
      $('login').hidden=true; $('workspace').hidden=false; $('logout').hidden=!token;
      $('model-state').textContent=identity.model_configured?'模型已配置':'模型未配置';
      $('method-version').textContent='v'+identity.method_version;
      $('ingest-form').hidden=!identity.actions.includes('write');
      notice('');
      $('archive-tab').hidden=!identity.scopes.includes('claude:archive');
      if(identity.scopes.includes('claude:archive')) await refreshArchives();
      if(identity.can_correct)await refreshMaterials(true);
      await refresh(); clearInterval(timer);
      timer=setInterval(()=>{if(document.hidden||document.querySelector('#records textarea, #records details[open], #document-reader[open]'))return; if(pendingJobs)refresh(); if(activeBatch?.state==='running' && location.hash==='#archives')refreshArchives().catch(err=>notice(err.message,true));},8000);
    } catch(err) {token='';identity=null;if(!['127.0.0.1','localhost'].includes(location.hostname)){notice('登录已失效，请重新登录后台。',true);const link=node('a','登录后台');link.href='/admin/login.html';$('notice').append(link);}else{$('login').hidden=false;notice(err.message,true);}}
  }
  $('login-form').addEventListener('submit',async e=>{e.preventDefault();token=$('token').value.trim();await connect();});
  $('logout').addEventListener('click',()=>{clearInterval(timer);token='';identity=null;$('workspace').hidden=true;$('login').hidden=false;$('records').replaceChildren();$('jobs').replaceChildren();$('documents').replaceChildren();notice('已断开，页面内凭据已清除。');});
  $('ingest-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=$('ingest-submit');button.disabled=true;
    const text=$('material').value,type=$('source-type').value,scope=$('ingest-scope').value,name=fileName;
    let accepted=0;
    try{
      const parts=MemoryFiles.split(text);$('material').readOnly=true;
      const bytes=new TextEncoder().encode(text);
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');
      let duplicates=0;
      for(let i=0;i<parts.length;i++){
        const result=await api('/sources',{scope,source_type:type,source_key:'workbench:text:'+digest+(parts.length>1?':part:'+String(i+1):''),messages:[{id:'1',role:type==='conversation'?'user':'external',text:parts[i],source_title:(name||'工作台提交')+(parts.length>1?' · 第 '+(i+1)+'/'+parts.length+' 段':'')}]});
        accepted++;if(result.duplicate)duplicates++;
        $('file-state').textContent='已提交 '+accepted+'/'+parts.length+' 段；原文没有截断。';
      }
      if($('material').value===text){$('material').value='';fileName='';$('file-input').value='';$('file-state').textContent='资料已提交，可以继续添加。';}
      notice(duplicates===parts.length?'这份资料已提交，未重复创建任务。':'已自动分成 '+parts.length+' 段入队，管家将逐段整理。');
      $('scope').value=scope;updateSpaceLabel();
      location.hash='jobs';await refresh();
      await refreshMaterials(true);
    }catch(err){notice((accepted?'已提交 '+accepted+' 段；':'')+err.message+'。保留正文，再次提交会跳过已完成入队的分段。',true);}finally{button.disabled=false;$('material').readOnly=false;}
  });
  async function loadFile(files){
    if(files.length!==1){notice('请一次选择一个文件，预览后再提交。',true);return;}
    const current=++fileRead,file=files[0];$('ingest-submit').disabled=true;
    try{
      if(file.size>MemoryFiles.MAX_FILE_BYTES)throw Error('文件超过 1 MB；请使用归档导入流程。');
      const text=MemoryFiles.decode(file.name,await file.arrayBuffer());
      if(current!==fileRead)return;
      if($('material').value.trim()){notice('正文里已有未提交内容，请先提交或清空后再选择文件。',true);return;}
      fileName=file.name.slice(0,240);$('material').value=text;$('source-type').value='document';
      $('file-state').textContent=fileName+' · '+text.length+' 字符 · 将自动分为 '+MemoryFiles.split(text).length+' 段，尚未提交。JSON 按原始文本处理，不自动导入整批对话。';notice('请检查正文和材料性质，确认后点击提交。');
    }catch(err){notice(err.message,true);}finally{if(current===fileRead){$('ingest-submit').disabled=false;$('file-input').value='';}}
  }
  $('material').addEventListener('input',()=>{if(!$('material').value){fileName='';$('file-state').textContent='也可以直接在下方粘贴文字。';}});
  $('file-input').addEventListener('change',e=>loadFile(e.target.files));
  $('materials-refresh').addEventListener('click',()=>refreshMaterials(true).catch(err=>notice(err.message,true)));
  $('materials-more').addEventListener('click',()=>refreshMaterials().catch(err=>notice(err.message,true)));
  const drop=$('drop-zone');
  ['dragenter','dragover'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.add('dragging');}));
  ['dragleave','drop'].forEach(name=>drop.addEventListener(name,e=>{e.preventDefault();drop.classList.remove('dragging');}));
  drop.addEventListener('drop',e=>loadFile(e.dataTransfer.files));
  function applyFilters(){
    let visible=0;document.querySelectorAll('.memory-tile').forEach(card=>{card.hidden=!!(($('record-kind').value&&card.dataset.topic!==$('record-kind').value)||($('record-status').value&&card.dataset.status!==$('record-status').value));if(!card.hidden)visible++;});
    $('filter-count').textContent='当前列表显示 '+visible+' 条；分类与性质筛选作用于已加载记录，更多内容请使用搜索。';
  }
  ['record-kind','record-status'].forEach(id=>$(id).addEventListener('change',applyFilters));
  function updateSpaceLabel(){ $('space-label').textContent='正在查看：'+$('scope').selectedOptions[0].textContent; }
  $('scope').addEventListener('change',()=>{updateSpaceLabel();$('document-reader').close();});
  function openDocument(title,text){$('reader-title').textContent=title;$('reader-body').textContent=text;$('document-reader').showModal();}
  $('reader-close').addEventListener('click',()=>$('document-reader').close());
  $('search-form').addEventListener('submit',e=>{e.preventDefault();refresh();});['scope','history'].forEach(id=>$(id).addEventListener('change',refresh));$('refresh').addEventListener('click',refresh);
  $('document-search-form').addEventListener('submit',async e=>{e.preventDefault();try{await refreshDocuments();}catch(err){notice(err.message,true);}});
  function showView() {
    const requested=location.hash.slice(1);
    const view=['documents','records','ingest','jobs','archives'].includes(requested)?requested:'documents';
    document.querySelectorAll('[data-panel]').forEach(el=>{el.hidden=el.dataset.panel!==view;});
    document.querySelectorAll('[data-view]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.view===view)));
  }
  document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{location.hash=button.dataset.view;showView();if(button.dataset.view==='ingest' && identity?.can_correct)refreshMaterials(true).catch(err=>notice(err.message,true));}));
  window.addEventListener('hashchange',showView);
  showView();
  connect();
})();

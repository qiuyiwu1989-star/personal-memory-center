'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const prefix = '/api/inside/memory-center/v1';
  let token = '', identity = null, timer = null, refreshing = false, pendingJobs = false;
  let documentData=[], documentCategory='', documentLeaf=false;
  let fileName='', fileRead=0, activeBatch=null, materialOffset=0;
  const labels = {archived:'已归档',paused_budget:'等待预算',ready:'待审核',discarded:'未采用',user_stated:'本人陈述 · 模型提炼', source_reported:'来源陈述', imported_summary:'导入摘要',agent_suggested:'AI 发言 · 未经本人确认',active:'可检索',superseded:'已被纠正',received:'待整理',processing:'正在提炼',applied:'提炼完成',failed:'失败',profile:'个人',preferences:'偏好',people:'人物',areas:'领域',projects:'项目',topics:'主题'};
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
    $('bulk-budget').textContent='已计量及在途预留 '+(batch.shared_tokens_spent??batch.tokens_spent).toLocaleString()+' / '+batch.token_limit.toLocaleString()+' tokens · 样本 '+batch.sample_done+'/'+batch.sampled_segments+' 个'+(batch.estimated_total_tokens?' · 全量预估约 '+batch.estimated_total_tokens.toLocaleString()+' tokens':'。预估会在样本完成后显示。')+'。未返回用量的失败任务按 35,000 tokens 预留。';
    $('bulk-errors').textContent=batch.recent_errors?.length?'最近失败：'+batch.recent_errors.map(x=>x.conversation_id.slice(0,8)+' / '+x.segment_index+' · '+(x.error||'未提供原因')).join('；'):'';
    if(batch.requires_replan){
      $('bulk-errors').textContent='旧计划保留。新规划只读取正式正文；采用后仍等待质量评测，不会启动模型。';
      if(identity?.can_correct){const preview=node('button','查看重规划差异','primary');
        preview.addEventListener('click',async()=>{preview.disabled=true;try{
          const result=await api('/bulk/'+batch.id+'/replan',{}),plan=result.plan,s=plan.summary;
          $('bulk-errors').textContent='对话片段 '+s.old_conversation_segments+' → '+s.new_conversation_segments+' · 无正文 '+s.no_visible_text_conversations+' 段 · 证据映射 '+JSON.stringify(s.evidence_states)+' · '+(plan.state==='preview'?'待采用':'已采用，等待质量评测')+'。映射只验证引用位置，不证明记忆正确。';
          actions.querySelector('[data-adopt]')?.remove();
          if(plan.state==='preview'){const adopt=node('button','采用此输入规划');adopt.dataset.adopt='1';adopt.addEventListener('click',async()=>{adopt.disabled=true;try{await api('/bulk/'+batch.id+'/replan/adopt',{plan_id:plan.id});await refreshArchives();notice('规划已采用；旧结果保留，模型未启动。');}catch(err){notice(err.message,true);adopt.disabled=false;}});actions.append(adopt);}
        }catch(err){notice(err.message,true);}finally{preview.disabled=false;}});actions.append(preview);}
      return;
    }
    const operate=(label,action)=>{const button=node('button',label,action==='resume'?'primary':undefined);button.addEventListener('click',async()=>{button.disabled=true;try{await api('/bulk/'+batch.id+'/control',{action});await refreshArchives();}catch(err){notice(err.message,true);button.disabled=false;}});actions.append(button);};
    if(batch.state==='running')operate('暂停新任务','pause');
    if(batch.state==='paused')operate('继续处理','resume');
    if((count.failed||0)>0 && batch.state!=='paused_budget')operate('重试一项失败任务','retry_failed');
    if(batch.state==='paused_error')$('bulk-errors').textContent='连接模型失败后已暂停，避免继续空转消耗预算。请检查模型服务，再点击重试。'+($('bulk-errors').textContent?' '+$('bulk-errors').textContent:'');
    if(batch.state==='paused_budget' && identity?.can_correct){
      const amount=node('input');amount.type='number';amount.min=String(batch.token_limit+35000);amount.max='100000000';amount.step='1000';amount.value=String(Math.min(100000000,batch.token_limit+1000000));amount.setAttribute('aria-label','新的累计 token 上限');
      const quality=node('input');quality.type='checkbox';quality.style.width='auto';const qualityLabel=node('label',undefined,'row');qualityLabel.append(quality,node('span','质量已核对，允许扩大预算'));const note=node('input');note.placeholder='质量验收依据';note.maxLength=1000;note.setAttribute('aria-label','历史批次质量验收依据');
      const button=node('button','提高上限并继续','primary');button.addEventListener('click',async()=>{if(!quality.checked||!note.value.trim()){notice('先记录质量验收依据；引用匹配本身不足以验收。',true);return;}button.disabled=true;try{const old=await api('/budget?'+new URLSearchParams({scope:batch.scope}));await api('/budget',{scope:batch.scope,token_limit:old.token_limit,quality_approved:true,note:note.value});await api('/bulk/'+batch.id+'/control',{action:'set_limit',token_limit:Number(amount.value)});await refreshArchives();}catch(err){notice(err.message,true);button.disabled=false;}});actions.append(amount,qualityLabel,note,button);
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
      if(identity.can_correct){const reextract=node('button','再次整理');let requestKey;reextract.addEventListener('click',async()=>{reextract.disabled=true;requestKey ||= crypto.randomUUID();try{await api('/materials/'+item.id+'/reextract',{request_key:requestKey});location.hash='jobs';showView();await refreshRuns();notice('已入队；按现有预算提炼，结果先供比较。');}catch(err){notice(err.message,true);reextract.disabled=false;}});buttons.append(reextract);}
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
    documentData=data.documents;renderDocumentCategories();
    renderDocuments();
  }
  function renderDocuments(){
    const documents=documentData.filter(d=>(!documentCategory||d.category===documentCategory) && (documentLeaf?!d.is_index:!d.slug.includes('--page-')));
    $('document-location').textContent=documentLeaf?'展开：'+(labels[documentCategory]||documentCategory)+' · 每页最多 25 组陈述':'主题目录 · 选择分类查看小文档';
    $('documents').replaceChildren();
    if(!documents.length) $('documents').append(node('p','此范围尚无匹配的主题文档。','muted'));
    for(const doc of documents) {
      const block=node('article',undefined,'record topic-tile');
      block.dataset.category=doc.category;block.append(node('span',labels[doc.category]||'主题','topic-category'),node('h3',doc.title),node('p',(doc.is_index?'分类目录 · ':'')+'v'+doc.revision+' · '+doc.claims+' 项陈述','muted'));
      const excerpt=doc.markdown.split('\n').find(line=>line.startsWith('- ')&&!line.startsWith('- 标题'));
      block.append(node('p',excerpt?excerpt.slice(2):'打开查看陈述、变化与原文依据。','tile-excerpt'));
      const read=node('button',doc.is_index?'展开小文档':'阅读文档','primary');read.addEventListener('click',()=>{if(doc.is_index){documentCategory=doc.category;documentLeaf=true;renderDocumentCategories();renderDocuments();}else openDocument(doc.title,doc.markdown,true);});
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
      const params=new URLSearchParams({scope:$('scope').value,q:$('query').value,history:$('history').checked?'1':'0',state:$('record-governance').value});
      const data=await api('/records?'+params);
      if(token!==requestedToken || !identity || $('scope').value!==requestedScope) return;
      await refreshDocuments();
      if(token!==requestedToken || !identity || $('scope').value!==requestedScope) return;
      await refreshOverview();await refreshBudget();await refreshRuns();
      pendingJobs=data.jobs.some(j=>j.state==='received'||j.state==='processing');
      $('count').textContent=String(data.total);
      const breakdown=data.status_counts||{};
      $('record-breakdown').textContent='当前范围：'+$('scope').selectedOptions[0].textContent+' · 原话提炼 '+(breakdown.source_reported||0)+' · AI 发言 '+(breakdown.agent_suggested||0)+' · 旧摘要 '+(breakdown.imported_summary||0)+' · 本人来源 '+(breakdown.user_stated||0)+'。抽取记录不等于已确认的长期记忆。';
      $('records').replaceChildren(); $('jobs').replaceChildren();
      if(!data.records.length) $('records').append(node('p','还没有匹配的记忆。提交材料后，管家会在这里留下理解与依据。','empty'));
      if(data.truncated) $('records').append(node('p','当前展示前 100 条，请缩小搜索范围。','muted'));
      for(const r of data.records) {
        const card=node('article',undefined,'record memory-tile');card.dataset.topic=r.topic;card.dataset.status=r.status;card.dataset.lifecycle=r.lifecycle;card.dataset.governance=r.governance?.state||'candidate';card.dataset.usable=String(r.usable);
        [labels[r.topic]||r.topic,r.message_id==='correction'?'本人明确纠正':(labels[r.status]||r.status),labels[r.lifecycle]||r.lifecycle,'v'+r.revision,...(r.source_date?[r.source_date.slice(0,10)]:[]),...(r.processing_method==='session_agent'?['会话 Agent 整理']:r.processing_method==='llm'?['后台模型提炼']:[])].forEach(t=>card.append(node('span',t,'tag')));
        card.append(node('p',({user:'本人',assistant:'AI 助手'}[r.subject]||r.subject),'muted'),node('p',r.display_statement||r.statement,'statement'));
        if(r.translated)card.append(node('span','中文译文 · 原文保留','tag'));
        if(r.governance){const g=r.governance;const states={candidate:'待核实候选',verified:'已核实',historical:'历史判断',rejected:'不采纳',owner_corrected:'本人纠正'};card.append(node('p',(states[g.state]||g.state)+' · '+g.priority+' · 成立时间：'+(g.as_of||'未知'),'muted'));}
        if(r.review_note) card.append(node('p','与旧记忆对照：'+r.review_note,'muted'));
        const details=node('details'); if(r.translated)details.append(node('p','原始陈述：'+r.statement,'muted'));details.append(node('summary','查看原文证据与来源'),node('blockquote',r.quote),node('p','来源：'+(r.source_title||r.source_id)+' · '+(r.source_date||'时间未记录')+' / '+(r.source_key||r.source_id)+' / 消息 '+r.message_id,'muted'));if(r.evidence_context){const context=r.evidence_context;details.append(node('p',(context.date_role==='summary_update'?'摘要更新时间不代表事件时间。':'消息日期不代表事件时间。')+' 对话范围：'+(context.conversation_title||'未知')+'；项目身份及当前有效性仍需核实。','muted'));}card.append(details);
        if(identity.can_correct && identity.actions.includes('write') && r.lifecycle==='active') {
          const govern=node('button','核实 / 标记');govern.addEventListener('click',()=>reviewRecord(r).catch(err=>notice(err.message,true)));card.append(govern);
          if(!r.translated && /[a-zA-Z]{4}/.test(r.statement)){const translate=node('button','生成中文译文');let requestKey;translate.addEventListener('click',async()=>{translate.disabled=true;requestKey ||= crypto.randomUUID();try{await api('/records/'+r.id+'/translate',{request_key:requestKey});notice('已进入翻译队列，原文与治理状态保持。');await refreshRuns();}catch(err){notice(err.message,true);translate.disabled=false;}});card.append(translate);}
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
        (j.state==='archived'?['archived']:['received','processing','applied']).forEach((step,i)=>{const item=node('li',labels[step]);const stage=j.state==='archived'?0:['received','processing','applied'].indexOf(j.state);item.dataset.done=String(i<=stage);steps.append(item);});
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
        const result=await api('/sources',{scope,source_type:type,processing_policy:$('processing-policy').value,source_metadata:{parser_version:'utf8-text-v1',parent_source_key:'workbench:file:'+digest,locator:'part:'+String(i+1)},source_key:'workbench:text:'+digest+(parts.length>1?':part:'+String(i+1):''),messages:[{id:'1',role:type==='conversation'?'user':'external',text:parts[i],source_title:(name||'工作台提交')+(parts.length>1?' · 第 '+(i+1)+'/'+parts.length+' 段':'')}]});
        accepted++;if(result.duplicate)duplicates++;
        $('file-state').textContent='已提交 '+accepted+'/'+parts.length+' 段；原文没有截断。';
      }
      if($('material').value===text){$('material').value='';fileName='';$('file-input').value='';$('file-state').textContent='资料已提交，可以继续添加。';}
      notice(duplicates===parts.length?'这份资料已提交，未重复创建任务。':'已自动分成 '+parts.length+' 段'+($('processing-policy').value==='archive'?'归档，未调用模型。':'入队，管家将按预算逐段整理。'));
      $('scope').value=scope;updateSpaceLabel();
      location.hash='jobs';showView();await refresh();
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
    let visible=0;document.querySelectorAll('.memory-tile').forEach(card=>{card.hidden=!!(($('record-kind').value&&card.dataset.topic!==$('record-kind').value)||($('record-status').value&&card.dataset.status!==$('record-status').value)||($('record-governance').value&&($('record-governance').value==='usable'?card.dataset.usable!=='true':$('record-governance').value==='history'?card.dataset.governance!=='historical'&&card.dataset.lifecycle==='active':card.dataset.governance!==$('record-governance').value)));if(!card.hidden)visible++;});
    $('filter-count').textContent='当前列表显示 '+visible+' 条；分类与性质筛选作用于已加载记录，更多内容请使用搜索。';
  }
  $('record-governance').addEventListener('change',()=>{if($('record-governance').value==='history')$('history').checked=true;refresh();});
  ['record-kind','record-status'].forEach(id=>$(id).addEventListener('change',applyFilters));
  function renderDocumentCategories(){
    const host=$('document-categories');host.replaceChildren();
    const categories=[...new Set(documentData.map(d=>d.category))];
    for(const category of ['',...categories]){
      const button=node('button',category?(labels[category]||'主题'):'全部分类');
      button.setAttribute('aria-pressed',String(category===documentCategory));
      button.addEventListener('click',()=>{documentCategory=category;documentLeaf=!!category;renderDocumentCategories();renderDocuments();});host.append(button);
    }
    if(documentLeaf){const back=node('button','返回目录');back.addEventListener('click',()=>{documentLeaf=false;documentCategory='';renderDocumentCategories();renderDocuments();});host.append(back);}
  }
  async function refreshOverview(){
    const scope=$('scope').value,data=await api('/overview?'+new URLSearchParams({scope}));
    if(scope!==$('scope').value)return;
    $('memory-overview').replaceChildren();
    const stages=[['sources','原始资料','保留原文','ingest'],['candidates','待核实','抽取不等于事实','records'],['usable','可用记忆','按任务提供给 Agent','records'],['historical','历史变化','更正与旧判断可回查','records']];
    for(const [key,title,help,view] of stages){
      const box=node('button',undefined,'stage-card');box.dataset.stage=key;box.append(node('span',title),node('strong',String(data[key])),node('span',help));
      box.addEventListener('click',()=>{location.hash=view;showView();if(view==='records'){$('record-governance').value=key==='candidates'?'candidate':key==='usable'?'usable':'history';if(key==='historical')$('history').checked=true;refresh();}});$('memory-overview').append(box);
    }
  }
  async function refreshBudget(){
    const scope=$('scope').value,b=await api('/budget?'+new URLSearchParams({scope}));if(scope!==$('scope').value)return;
    $('budget-summary').textContent=b.tokens_spent.toLocaleString('zh-CN')+' / '+b.token_limit.toLocaleString('zh-CN')+' tokens · '+(b.quality_approved?'本人已记录质量验收':'样本阶段，尚未放开')+' · '+b.unresolved_attempts+' 次用量未返回 / 已预留';
    if(b.shared_token_limit!=null)$('budget-summary').textContent+=' · 含历史批次合计 '+(b.tokens_spent+b.legacy_tokens_spent).toLocaleString('zh-CN')+' / '+b.shared_token_limit.toLocaleString('zh-CN')+' tokens';
    $('budget-progress').max=Math.max(1,b.token_limit);$('budget-progress').value=b.tokens_spent;
    $('budget-settings').hidden=!identity.can_correct;
    if(!$('budget-form').contains(document.activeElement)){$('budget-limit').value=b.token_limit;$('budget-quality').checked=!!b.quality_approved;$('budget-note').value=b.note;}
  }
  $('budget-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{await api('/budget',{scope:$('scope').value,token_limit:Number($('budget-limit').value),quality_approved:$('budget-quality').checked,note:$('budget-note').value});notice('预算已保存；普通提炼和再次整理共用计量。Claude 历史批次需在原始资料中另行控制。');await refresh();}catch(err){notice(err.message,true);}finally{button.disabled=false;}});
  async function refreshRuns(){
    const scope=$('scope').value,data=await api('/extraction-runs?'+new URLSearchParams({scope}));if(scope!==$('scope').value)return;
    $('extraction-runs').replaceChildren();
    if(!data.runs.length)$('extraction-runs').append(node('p','尚无再次整理或翻译任务。','empty'));
    for(const run of data.runs){
      const card=node('article',undefined,'run-card');card.append(node('h3',run.operation==='translate'?'中文译文':'再次提炼'),node('span',labels[run.state]||run.state,'tag'),node('p',run.source_key,'muted'),node('p',run.method_version+' · '+run.attempts+' 次尝试','muted'));
      if(run.error)card.append(node('p',run.error,'muted'));
      if(run.usage)card.append(node('p','返回用量 '+(run.usage.total_tokens??'未知')+' tokens','muted'));
      if(run.state==='ready'){const button=node('button','查看差异','primary');button.addEventListener('click',()=>reviewRun(run).catch(err=>notice(err.message,true)));card.append(button);}
      if(run.state==='failed' && identity.can_correct){const retry=node('button','重试');retry.addEventListener('click',async()=>{retry.disabled=true;try{await api('/extraction-runs/'+run.id+'/control',{action:'retry'});await refreshRuns();}catch(err){notice(err.message,true);retry.disabled=false;}});card.append(retry);}
      $('extraction-runs').append(card);
    }
  }
  async function reviewRun(run){
    const data=await api('/extraction-previews/'+run.preview_id),host=$('review-content');host.replaceChildren();$('review-title').textContent=run.operation==='translate'?'核对中文译文':'比较再次提炼结果';
    host.append(node('p','采用候选不会覆盖旧结论或自动核实；译文仅改变展示。','muted'));
    const form=node('form');const checks=[];
    data.changes.forEach((change,i)=>{const item=node('div',undefined,'diff-item'),label=node('label',undefined,'row'),check=node('input');check.type='checkbox';check.value=String(i);check.disabled=change.comparison==='duplicate';checks.push(check);label.append(check,node('span',({duplicate:'重复 · 无需再加入',new:'新增候选',related_needs_review:'有关联旧记录 · 需对照',translation:'中文展示译文'})[change.comparison]||change.comparison));item.append(label);
      if(change.candidate.original)item.append(node('p','原文：'+change.candidate.original));
      for(const old of change.existing||[])item.append(node('p','旧记录：'+old.statement,'muted'));
      item.append(node('p',change.candidate.text||change.candidate.statement,'statement'));
      if(change.candidate.quote)item.append(node('blockquote',change.candidate.quote));form.append(item);
    });
    if(!data.changes.length)form.append(node('p','本次没有提出可保存的候选。','muted'));
    const accept=node('button',run.operation==='translate'?'采用中文译文':'采用选中的候选','primary'),discard=node('button','本次不采用');discard.type='button';form.append(accept,discard);host.append(form);
    async function submit(action,indices){accept.disabled=true;discard.disabled=true;try{await api('/extraction-runs/'+run.id+'/control',{action,indices});$('review-dialog').close();await refresh();}catch(err){notice(err.message,true);accept.disabled=false;discard.disabled=false;}}
    form.addEventListener('submit',e=>{e.preventDefault();const indices=checks.filter(c=>c.checked).map(c=>Number(c.value));if(!indices.length){notice('先选择要采用的候选。',true);return;}submit('apply',indices);});discard.addEventListener('click',()=>submit('discard'));$('review-dialog').showModal();
  }
  async function reviewRecord(record){
    const data=await api('/entities?'+new URLSearchParams({scope:$('scope').value}));const host=$('review-content');host.replaceChildren();$('review-title').textContent='核实归属与有效时间';
    host.append(node('p',record.display_statement||record.statement,'statement'),node('blockquote',record.quote),node('p','日期不明就保留候选；来源时间不自动当作成立时间。','muted'));
    const form=node('form'),grid=node('div',undefined,'review-grid'),fields={};
    function field(key,title,type,choices){const box=node('div'),label=node('label',title);const input=node(choices?'select':'input');input.setAttribute('aria-label',title);if(!choices)input.type=type||'text';if(choices)for(const [value,text] of choices){const o=node('option',text);o.value=value;input.append(o);}input.value=record.governance?.[key]||'';fields[key]=input;box.append(label,input);grid.append(box);}
    field('state','治理状态',null,[['candidate','待核实'],['verified','已核实'],['historical','历史判断'],['rejected','不采纳']]);
    field('priority','保存优先级',null,[['P0','P0 · 身份与重要更正'],['P1','P1 · 关系与关键决策'],['P2','P2 · 持续偏好'],['P3','P3 · 档案与讨论']]);
    const entities=[['','未知'],...data.entities.map(e=>[e.id,e.name+' · '+e.id])];field('holder','谁认为',null,entities);field('subject_id','关于谁 / 什么',null,entities);field('as_of','何时成立','date');field('valid_until','何时失效（可空）','date');field('note','审核依据','text');
    const save=node('button','保存审核状态','primary');form.append(grid,save);host.append(form);
    const registry=node('details');registry.append(node('summary','登记人物或项目（不自动合并同名人物）'));const entityForm=node('form'),eid=node('input'),name=node('input'),kind=node('select');eid.placeholder='稳定 ID，如 person:sample';eid.required=true;name.placeholder='名称';name.required=true;for(const [value,title] of [['person','人物'],['project','项目'],['organization','组织'],['topic','主题']]){const o=node('option',title);o.value=value;kind.append(o);}const add=node('button','登记实体');entityForm.append(eid,name,kind,add);registry.append(entityForm);host.append(registry);entityForm.addEventListener('submit',async e=>{e.preventDefault();try{await api('/entities',{scope:$('scope').value,id:eid.value,kind:kind.value,name:name.value,aliases:[]});$('review-dialog').close();await reviewRecord(record);}catch(err){notice(err.message,true);}});
    form.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;const body={revision:record.governance.revision};for(const [key,input] of Object.entries(fields))body[key]=input.value||null;try{await api('/records/'+record.id+'/governance',body);$('review-dialog').close();notice('审核状态已保存，来源和旧版本保留。');await refresh();}catch(err){notice(err.message,true);save.disabled=false;}});$('review-dialog').showModal();
  }
  $('review-close').addEventListener('click',()=>$('review-dialog').close());

  function updateSpaceLabel(){ $('space-label').textContent='正在查看：'+$('scope').selectedOptions[0].textContent; }
  $('scope').addEventListener('change',()=>{documentCategory='';documentLeaf=false;updateSpaceLabel();$('document-reader').close();});
  function openDocument(title,text,markdown=false){$('reader-title').textContent=title;const host=$('reader-body');host.replaceChildren();if(!markdown){host.append(node('pre',text));}else{let front=false;for(const line of text.split('\n')){if(line==='---'){front=!front;continue;}if(front)continue;const heading=line.match(/^(#{1,3}) (.*)$/);if(heading)host.append(node('h'+heading[1].length,heading[2]));else if(line.startsWith('> '))host.append(node('blockquote',line.slice(2)));else if(line.startsWith('- '))host.append(node('p','• '+line.slice(2)));else if(line.trim())host.append(node('p',line));}}$('document-reader').showModal();}
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

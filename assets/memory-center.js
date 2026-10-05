'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const prefix = '/api/inside/memory-center/v1';
  let token = '', identity = null, timer = null, refreshing = false, pendingJobs = false, refreshQueued = false;
  let documentData=[], documentCategory='', documentLeaf=false;
  let fileName='', fileRead=0, activeBatch=null, materialOffset=0;
  const labels = {archived:'已归档',paused_budget:'等待预算',ready:'待审核',discarded:'未采用',user_stated:'本人陈述', source_reported:'来源陈述', imported_summary:'导入摘要',agent_suggested:'AI 发言 · 未经本人确认',active:'可检索',superseded:'已被纠正',received:'待整理',processing:'正在提炼',applied:'提炼完成',failed:'失败',profile:'个人',preferences:'偏好',people:'人物',areas:'领域',projects:'项目',topics:'主题'};
  function notice(message, error=false) { $('notice').hidden=!message; $('notice').textContent=message; $('notice').dataset.error=String(error); const modal=$('review-notice'); if(modal){modal.hidden=!(message&&error&&$('review-dialog').open);modal.textContent=modal.hidden?'':message;} }
  async function api(path, body) {
    const response = await fetch(prefix+path,{method:body===undefined?'GET':'POST',headers:{...(token?{Authorization:'Bearer '+token}:{'X-Memory-Local':'1'}),'Content-Type':'application/json'},cache:'no-store',body:body===undefined?undefined:JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '请求失败');
    return data;
  }
  function node(tag,text,cls) { const el=document.createElement(tag); if(text!==undefined) el.textContent=text; if(cls)el.className=cls; return el; }
  function methodLabel(version) {
    return version && version !== 'legacy' ? '提炼方法 '+version : '提炼方法未记录';
  }
  function failureDetail(error) {
    const detail=node('details',undefined,'failure-detail');
    detail.append(node('summary','失败原因'),node('p',error||'服务未返回具体原因；请查看处理任务。'));
    return detail;
  }
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
      const state=item.state==='archived'?'原文已归档 · 未调用模型':item.state==='applied'?'提炼完成 · '+item.claim_count+' 条抽取记录':item.state==='failed'?'处理失败':item.state==='processing'?'正在提炼':'等待处理';
      card.append(node('span',state,'tag'),node('p',item.preview||'无文字预览','material-preview'));
      const indexState=item.index_status?.state;
      if(indexState && indexState!=='idle')card.append(node('p',indexState==='ready'?'本范围原文索引已更新':indexState==='failed'?'原文索引待重试':'本范围原文索引更新中','muted'));
      card.append(node('p',methodLabel(item.method_version),'muted'));
      if(item.state==='applied')card.append(node('p','提炼完成不代表质量已验收或已成为长期记忆。','muted'));
      if(item.state==='failed')card.append(failureDetail(item.error));
      const buttons=node('div',undefined,'tile-actions'),read=node('button','查看原文');
      read.addEventListener('click',async()=>{read.disabled=true;try{const raw=await api('/materials/'+item.id);openDocument(item.title||'原始资料',raw.messages.map(m=>'['+m.role+'] '+m.text).join('\n\n'));}catch(err){notice(err.message,true);}finally{read.disabled=false;}});buttons.append(read,ledgerButton('sources',item.id,item.scope));
      if(item.state==='failed' && item.job_id){const retry=node('button','重试整理','primary');retry.addEventListener('click',async()=>{retry.disabled=true;try{await api('/jobs/'+item.job_id+'/retry',{});await refreshMaterials(true);}catch(err){notice(err.message,true);retry.disabled=false;}});buttons.append(retry);}
      if(identity.can_correct){const reextract=node('button','再次提炼并比较');let requestKey;reextract.addEventListener('click',async()=>{reextract.disabled=true;requestKey ||= crypto.randomUUID();try{await api('/materials/'+item.id+'/reextract',{request_key:requestKey});location.hash='jobs';showView();await refreshRuns();notice('已入队；按现有预算提炼，结果先供比较。');}catch(err){notice(err.message,true);reextract.disabled=false;}});buttons.append(reextract);}
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
        const link=node('a');link.href=url;link.download=doc.slug+'.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
      });
      const actions=node('div',undefined,'tile-actions');actions.append(read,changes,download);block.append(actions);$('documents').append(block);
    }
  }
  async function refresh() {
    if(!identity) return;
    if(refreshing){refreshQueued=true;return;}
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
      if(!data.records.length) $('records').append(node('p','还没有匹配的记忆。可以补充本人陈述，或提交资料后选择提炼；仅归档不会自动生成记忆。','empty'));
      if(data.truncated) $('records').append(node('p','当前展示前 100 条，请缩小搜索范围。','muted'));
      for(const r of data.records) {
        const card=node('article',undefined,'record memory-tile');card.dataset.topic=r.topic;card.dataset.status=r.status;card.dataset.lifecycle=r.lifecycle;card.dataset.governance=r.governance?.state||'candidate';card.dataset.usable=String(r.usable);
        [labels[r.topic]||r.topic,r.message_id==='correction'?'本人明确纠正':(labels[r.status]||r.status),labels[r.lifecycle]||r.lifecycle,'v'+r.revision,...(r.source_date?[r.source_date.slice(0,10)]:[]),...(r.processing_method==='owner_manual'?['本人手动维护']:r.processing_method==='session_agent'?['会话 Agent 整理']:r.processing_method==='llm'?['后台模型提炼']:[])].forEach(t=>card.append(node('span',t,'tag')));
        card.append(node('p',({user:'本人',assistant:'AI 助手'}[r.subject]||r.subject),'muted'),node('p',r.display_statement||r.statement,'statement'));
        if(r.translated)card.append(node('span','中文译文 · 原文保留','tag'));
        if(r.governance){const g=r.governance;const states={candidate:'待核实候选',verified:r.usable?'可信 · 当前可用':'已核实 · 当前不可用',historical:'历史判断',rejected:'不采纳',owner_corrected:'旧纠正记录 · 待重新核实'};
          card.append(node('p',(states[g.state]||g.state)+' · '+g.priority,'muted'),node('p','谁认为：'+(g.holder||'未知')+' · 关于：'+(g.subject_id||'未知'),'muted'),node('p','成立：'+(g.as_of||'未知')+' · 失效：'+(g.valid_until||'未设置'),'muted'));
          if(!r.usable&&g.state!=='rejected')card.append(node('p','可回查此记录；当前不会作为可信上下文提供给 Agent。','muted'));} 
        if(r.review_note) card.append(node('p','与旧记忆对照：'+r.review_note,'muted'));
        if(r.quality_note) card.append(node('p','提炼质量待复核：'+r.quality_note,'muted'));
        const details=node('details'); if(r.translated)details.append(node('p','原始陈述：'+r.statement,'muted'));details.append(node('summary','查看原文证据与来源'),node('blockquote',r.quote),node('p','来源：'+(r.source_title||r.source_id)+' · '+(r.source_date||'时间未记录')+' / '+(r.source_key||r.source_id)+' / 消息 '+r.message_id,'muted'));if(r.evidence_context){const context=r.evidence_context;details.append(node('p',(context.date_role==='summary_update'?'摘要更新时间不代表事件时间。':'消息日期不代表事件时间。')+' 对话范围：'+(context.conversation_title||'未知')+'；项目身份及当前有效性仍需核实。','muted'));}card.append(details,ledgerButton('records',r.id,$('scope').value));
        if(identity.can_correct && identity.actions.includes('write') && r.lifecycle==='active') {
          const govern=node('button','核实 / 标记');govern.addEventListener('click',()=>reviewRecord(r).catch(err=>notice(err.message,true)));card.append(govern);
          if(!r.translated && /[a-zA-Z]{4}/.test(r.statement)){const translate=node('button','生成中文译文');let requestKey;translate.addEventListener('click',async()=>{translate.disabled=true;requestKey ||= crypto.randomUUID();try{await api('/records/'+r.id+'/translate',{request_key:requestKey});notice('已进入翻译队列，原文与治理状态保持。');await refreshRuns();}catch(err){notice(err.message,true);translate.disabled=false;}});card.append(translate);}
          const edit=node('button','补充 / 修改');edit.addEventListener('click',()=>ownerEditor(r));card.append(edit);
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
        if(j.usage?.method==='owner_manual') row.append(node('p','本人手动维护，未调用模型。','muted'));
        else if(j.usage?.method==='session_agent') row.append(node('p','由本次会话 Agent 阅读原文整理；未调用后台模型，未单独计量 token。','muted'));
        else if(j.usage) row.append(node('p','本次返回的 token：输入 '+(j.usage.prompt_tokens??'未知')+' / 输出 '+(j.usage.completion_tokens??'未知'),'muted'));
        row.append(node('p',methodLabel(j.usage?.method_version),'muted'));
        if(j.state==='failed')row.append(failureDetail(j.error));
        if(j.state==='failed' && identity.actions.includes('write')) {
          if(j.source_key?.startsWith('claude:archive:')){const link=node('button','在原始资料中处理');link.addEventListener('click',()=>{location.hash='archives';showView();});row.append(link);}
          else {const retry=node('button','重试');retry.addEventListener('click',async()=>{retry.disabled=true;try{await api('/jobs/'+j.id+'/retry',{});await refresh();}catch(err){notice(err.message,true);retry.disabled=false;}});row.append(retry);}
        }
        $('jobs').append(row);
      }
    } catch(err){notice(err.message,true);} finally{refreshing=false;if(refreshQueued){refreshQueued=false;refresh();}}
  }
  async function connect() {
    try {
      identity=await api('/status'); $('token').value='';
      $('scope').replaceChildren(...identity.scopes.map(s=>{const o=node('option',s==='personal'?'个人记忆':s==='claude:sample-20260929'?'Claude 历史示范 · 2026-09-29':s==='claude:ark-20260929'?'Claude · 火山自动提炼':s==='claude:history-20260929'?'Claude · 历史批量整理':s);o.value=s;return o;}));
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
      ownerAdd.hidden=!identity.can_correct || !identity.actions.includes('write');
      $('daily-owner-add').hidden=ownerAdd.hidden || !identity.scopes.includes('personal');
      $('daily-upload').hidden=!identity.actions.includes('write');
      $('daily-review').hidden=!identity.can_correct;
      agentManage.hidden=!identity.can_manage_agents;
      $('configuration-tab').hidden=!identity.can_correct || !identity.actions.includes('write');
      $('evidence-index').hidden=!identity.actions.includes('write') || !identity.actions.includes('source_read');
      notice('');
      $('archive-tab').hidden=!identity.scopes.includes('claude:archive');
      if(identity.scopes.includes('claude:archive')) await refreshArchives();
      if(identity.can_correct)await refreshMaterials(true);
      await refresh(); showView(); clearInterval(timer);
      timer=setInterval(()=>{if(document.hidden||document.querySelector('#records textarea, #records details[open], #document-reader[open], #review-dialog[open]'))return; if(pendingJobs)refresh(); if(activeBatch?.state==='running' && location.hash==='#archives')refreshArchives().catch(err=>notice(err.message,true));},8000);
    } catch(err) {token='';identity=null;if(!['127.0.0.1','localhost'].includes(location.hostname)){notice('登录已失效，请重新登录后台。',true);const link=node('a','登录后台');link.href='/admin/login.html';$('notice').append(link);}else{$('login').hidden=false;notice(err.message,true);}}
  }
  $('login-form').addEventListener('submit',async e=>{e.preventDefault();token=$('token').value.trim();await connect();});
  $('logout').addEventListener('click',()=>{clearInterval(timer);token='';identity=null;++reviewEpoch;$('review-dialog').close();$('review-content').querySelectorAll('textarea').forEach(input=>{input.value='';});$('review-content').replaceChildren();delete $('review-content').dataset.credentials;$('workspace').hidden=true;$('login').hidden=false;$('records').replaceChildren();$('jobs').replaceChildren();$('documents').replaceChildren();$('evidence-list').replaceChildren();$('evidence-summary').textContent='';$('evidence-more').hidden=true;$('document-reader').close();++configurationEpoch;++mapEpoch;configurationData=null;for(const id of ['configuration-active','configuration-compare','configuration-status','configuration-baseline','configuration-versions','configuration-events','configuration-integrations','map-records','map-diagram','map-details','map-summary'])$(id).replaceChildren();for(const id of ['configuration-instructions','configuration-skill-text','configuration-label','configuration-base','configuration-model'])$(id).value='';notice('已断开，页面内凭据已清除。');});
  $('ingest-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=$('ingest-submit');button.disabled=true;
    const text=$('material').value,type=$('source-type').value,scope=$('ingest-scope').value,name=fileName,visibility=$('source-visibility')?.value||'unknown';
    let accepted=0;
    try{
      const parts=MemoryFiles.split(text);$('material').readOnly=true;
      const bytes=new TextEncoder().encode(text);
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');
      let duplicates=0;
      for(let i=0;i<parts.length;i++){
        const metadata={parser_version:'utf8-text-v1',parent_source_key:'workbench:file:'+digest,locator:'part:'+String(i+1)};
        if(visibility!=='unknown')metadata.visibility=visibility;
        const result=await api('/sources',{scope,source_type:type,processing_policy:$('processing-policy').value,source_metadata:metadata,source_key:'workbench:text:'+digest+(parts.length>1?':part:'+String(i+1):''),messages:[{id:'1',role:type==='conversation'?'user':'external',text:parts[i],source_title:(name||'工作台提交')+(parts.length>1?' · 第 '+(i+1)+'/'+parts.length+' 段':'')}]});
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
    $('memory-overview').replaceChildren();renderProjection(data.projection);
    const start=$('personal-start');start.hidden=scope!=='personal'||data.usable>0;
    start.textContent=data.candidates>0?'个人记忆已有 '+data.candidates+' 条候选；先核实归属、出处和有效时间，才可供 Agent 使用。':'个人记忆尚未建立。可以先补充一条当前偏好或项目决定，保存后核实；也可以先归档资料。';
    const stages=[['sources','原始资料','保留原文','ingest'],['candidates','待核实','抽取不等于事实','records'],['usable','可用记忆','按任务提供给 Agent','records'],['historical','历史变化','更正与旧判断可回查','records']];
    for(const [key,title,help,view] of stages){
      const box=node('button',undefined,'stage-card');box.dataset.stage=key;box.append(node('span',title),node('strong',String(data[key])),node('span',help));
      box.addEventListener('click',()=>{location.hash=view;showView();if(view==='records'){$('record-governance').value=key==='candidates'?'candidate':key==='usable'?'usable':'history';if(key==='historical')$('history').checked=true;refresh();}});$('memory-overview').append(box);
    }
  }
  function renderProjection(projection){
    const host=$('projection-status');if(!host)return;host.hidden=!projection;if(!projection)return;
    let text='主题文档刷新状态未知。';
    if(projection.state==='unavailable')text='纠正时间审计尚未接入，暂不能跟踪主题文档刷新。';
    else if(projection.state==='untracked')text='尚无可追踪的本人修改；旧资料刷新状态未知。';
    else if(projection.stale===true)text='本人修改后的主题文档待刷新。';
    else if(projection.state==='ready'&&projection.stale===false&&projection.coverage==='since-migration-only')text='接入时间审计后的本人修改，主题文档已刷新。';
    host.textContent=text+' 仅跟踪接入后的本人修改，不表示其他 Agent 的旧缓存已更新。';
  }
  async function refreshBudget(){
    const scope=$('scope').value,b=await api('/budget?'+new URLSearchParams({scope}));if(scope!==$('scope').value)return;
    $('budget-summary').textContent=b.tokens_spent.toLocaleString('zh-CN')+' / '+b.token_limit.toLocaleString('zh-CN')+' tokens · '+(b.quality_approved?'本人已记录质量验收':'样本阶段，尚未放开')+' · '+b.unresolved_attempts+' 次用量未返回 / 已预留';
    if(b.shared_token_limit!=null)$('budget-summary').textContent+=' · 含历史批次合计 '+(b.tokens_spent+b.legacy_tokens_spent).toLocaleString('zh-CN')+' / '+b.shared_token_limit.toLocaleString('zh-CN')+' tokens';
    $('budget-progress').max=Math.max(1,b.token_limit);$('budget-progress').value=b.tokens_spent;
    $('budget-settings').hidden=!identity.can_correct;
    const exhausted=b.tokens_spent>=b.token_limit || (b.shared_token_limit!=null && b.tokens_spent+b.legacy_tokens_spent>=b.shared_token_limit);
    $('daily-status').textContent=exhausted?'当前范围的模型预算已达到上限；资料归档、手动补充和核实仍可使用。':'资料归档、手动补充和核实不调用模型；选择提炼才使用预算，结果先作为候选。';
    if(!$('budget-form').contains(document.activeElement)){$('budget-limit').value=b.token_limit;$('budget-quality').checked=!!b.quality_approved;$('budget-note').value=b.note;}
  }
  $('budget-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{await api('/budget',{scope:$('scope').value,token_limit:Number($('budget-limit').value),quality_approved:$('budget-quality').checked,note:$('budget-note').value});notice('预算已保存；普通提炼和再次整理共用计量。Claude 历史批次需在原始资料中另行控制。');await refresh();}catch(err){notice(err.message,true);}finally{button.disabled=false;}});
  async function refreshRuns(){
    const scope=$('scope').value,data=await api('/extraction-runs?'+new URLSearchParams({scope}));if(scope!==$('scope').value)return;
    $('extraction-runs').replaceChildren();
    if(!data.runs.length)$('extraction-runs').append(node('p','尚无再次整理或翻译任务。','empty'));
    for(const run of data.runs){
      const card=node('article',undefined,'run-card');card.append(node('h3',run.operation==='translate'?'中文译文':'再次提炼'),node('span',labels[run.state]||run.state,'tag'),node('p',run.source_key,'muted'),node('p',methodLabel(run.method_version)+' · '+run.attempts+' 次尝试','muted'));
      if(run.state==='failed')card.append(failureDetail(run.error));
      if(run.usage)card.append(node('p','返回用量 '+(run.usage.total_tokens??'未知')+' tokens','muted'));
      if(run.state==='ready'){const button=node('button','查看差异','primary');button.addEventListener('click',()=>reviewRun(run).catch(err=>notice(err.message,true)));card.append(button);}
      if(run.state==='failed' && identity.can_correct){const retry=node('button','重试');retry.addEventListener('click',async()=>{retry.disabled=true;try{await api('/extraction-runs/'+run.id+'/control',{action:'retry'});await refreshRuns();}catch(err){notice(err.message,true);retry.disabled=false;}});card.append(retry);}
      $('extraction-runs').append(card);
    }
  }
  let reviewEpoch=0;
  async function reviewRun(run){
    const epoch=++reviewEpoch,activeIdentity=identity,scope=$('scope').value;
    const data=await api('/extraction-previews/'+run.preview_id);if(epoch!==reviewEpoch||identity!==activeIdentity||scope!==$('scope').value)return;const host=$('review-content');host.replaceChildren();$('review-title').textContent=run.operation==='translate'?'核对中文译文':'比较再次提炼结果';
    host.append(node('p','采用候选不会覆盖旧结论或自动核实；译文仅改变展示。','muted'));
    const form=node('form');const checks=[];
    data.changes.forEach((change,i)=>{const item=node('div',undefined,'diff-item'),label=node('label',undefined,'row'),check=node('input');check.type='checkbox';check.value=String(i);check.disabled=change.comparison==='duplicate';checks.push(check);label.append(check,node('span',({duplicate:'重复 · 无需再加入',new:'新增候选',related_needs_review:'有关联旧记录 · 需对照',translation:'中文展示译文'})[change.comparison]||change.comparison));item.append(label);
      for(const link of change.associations||[])item.append(node('p',(link.relation==='exact_statement'?'同一陈述重复':'引用同一段证据')+' · '+link.record_id+'；仅关联，不代表独立佐证或自动合并。','muted'));
      if(change.candidate.original)item.append(node('p','原文：'+change.candidate.original));
      for(const old of change.existing||[])item.append(node('p','旧记录：'+old.statement,'muted'));
      item.append(node('p',change.candidate.text||change.candidate.statement,'statement'));
      if(change.candidate.quote)item.append(node('blockquote',change.candidate.quote));form.append(item);
    });
    if(!data.changes.length)form.append(node('p','本次没有提出可保存的候选。','muted'));
    const accept=node('button',run.operation==='translate'?'采用中文译文':'采用选中的候选','primary'),discard=node('button','本次不采用');discard.type='button';form.append(accept,discard);host.append(form);
    async function submit(action,indices){accept.disabled=true;discard.disabled=true;try{await api('/extraction-runs/'+run.id+'/control',{action,indices});$('review-dialog').close();await refresh();}catch(err){notice(err.message,true);accept.disabled=false;discard.disabled=false;}}
    form.addEventListener('submit',e=>{e.preventDefault();const indices=checks.filter(c=>c.checked).map(c=>Number(c.value));if(!indices.length){notice('先选择要采用的候选。',true);return;}submit('apply',indices);});discard.addEventListener('click',()=>submit('discard'));$('review-notice').hidden=true;if(!$('review-dialog').open)$('review-dialog').showModal();
  }
  function changeFields(host,{existing=false,owner=false}={}){
    const box=node('div'),kind=node('select');kind.setAttribute('aria-label','此次变化类型（可选）');
    const choices=[['','未指定 · 保持原流程'],['metadata_update','补充或调整归属 / 时间'],['evidence_update','补充证据'],['interpretation_correction','纠正系统理解']];
    if(existing)choices.push(['viewpoint_change','我的观点改变'],['withdrawal','撤回记录（需明确设为不采纳）']);
    for(const [value,title] of choices){const option=node('option',title);option.value=value;kind.append(option);}
    kind.value='';box.append(node('label','此次变化类型（可选）'),kind);host.append(box);
    const endBox=node('div'),end=node('input');end.type='date';end.setAttribute('aria-label','旧观点事实失效日期（可空）');endBox.hidden=true;
    endBox.append(node('label','旧观点事实失效日期（可空）'),end,node('p','只在明确观点改变时填写；不是记录或保存时间。未知留空，不自动填今天。','muted'));if(existing)host.append(endBox);
    const withdrawalBox=node('div'),confirm=node('input');confirm.type='checkbox';confirm.setAttribute('aria-label','确认将治理状态设为不采纳');withdrawalBox.hidden=true;
    withdrawalBox.append(confirm,node('span','确认将治理状态设为不采纳；该判断退出可信上下文，旧版本保留。'));if(existing&&owner)host.append(withdrawalBox);
    host.append(node('p','未指定时沿用原流程；指定变化类型需要服务器支持纠正时间审计。','muted'));
    kind.addEventListener('change',()=>{endBox.hidden=kind.value!=='viewpoint_change';if(endBox.hidden)end.value='';withdrawalBox.hidden=kind.value!=='withdrawal';confirm.checked=false;});
    return {apply(body){if(!choices.some(([value])=>value===kind.value))throw new Error('新增陈述不能改变或撤回旧观点');if(kind.value==='withdrawal'){if(owner){if(!confirm.checked)throw new Error('请明确确认将治理状态设为不采纳');body.governance.state='rejected';}else if(body.state!=='rejected')throw new Error('撤回记录需将治理状态明确设为不采纳');}if(kind.value)body.change_kind=kind.value;if(kind.value==='viewpoint_change'&&end.value)body.previous_valid_until=end.value;}};
  }
  async function reviewRecord(record){
    const epoch=++reviewEpoch,activeIdentity=identity,scope=$('scope').value;
    const data=await api('/entities?'+new URLSearchParams({scope}));if(epoch!==reviewEpoch||identity!==activeIdentity||scope!==$('scope').value)return;const host=$('review-content');host.replaceChildren();$('review-title').textContent='核实归属与有效时间';
    host.append(node('p',record.display_statement||record.statement,'statement'),node('blockquote',record.quote),node('p','日期不明就保留候选；来源时间不自动当作成立时间。','muted'));
    const form=node('form'),grid=node('div',undefined,'review-grid'),fields={};
    function field(key,title,type,choices){const box=node('div'),label=node('label',title);const input=node(choices?'select':'input');input.setAttribute('aria-label',title);if(!choices)input.type=type||'text';if(choices)for(const [value,text] of choices){const o=node('option',text);o.value=value;input.append(o);}input.value=record.governance?.[key]||'';if(key==='state'&&!choices.some(([value])=>value===input.value))input.value='candidate';fields[key]=input;box.append(label,input);grid.append(box);}
    field('state','治理状态',null,[['candidate','待核实'],['verified','已核实'],['historical','历史判断'],['rejected','不采纳']]);
    field('priority','保存优先级',null,[['P0','P0 · 身份与重要更正'],['P1','P1 · 关系与关键决策'],['P2','P2 · 持续偏好'],['P3','P3 · 档案与讨论']]);
    const entities=[['','未知'],...data.entities.map(e=>[e.id,e.name+' · '+e.id])];field('holder','谁认为',null,entities);field('subject_id','关于谁 / 什么',null,entities);field('as_of','何时成立','date');field('valid_until','何时失效（可空）','date');field('note','审核依据','text');
    const change=changeFields(grid,{existing:true});const save=node('button','保存审核状态','primary');form.append(grid,save);host.append(form);
    const registry=node('details');registry.append(node('summary','登记人物或项目（不自动合并同名人物）'));const entityForm=node('form'),eid=node('input'),name=node('input'),kind=node('select');eid.placeholder='稳定 ID，如 person:sample';eid.required=true;name.placeholder='名称';name.required=true;for(const [value,title] of [['person','人物'],['project','项目'],['organization','组织'],['topic','主题']]){const o=node('option',title);o.value=value;kind.append(o);}const add=node('button','登记实体');entityForm.append(eid,name,kind,add);registry.append(entityForm);host.append(registry);entityForm.addEventListener('submit',async e=>{e.preventDefault();try{if(epoch!==reviewEpoch||identity!==activeIdentity||scope!==$('scope').value)return;await api('/entities',{scope,id:eid.value,kind:kind.value,name:name.value,aliases:[]});if(epoch!==reviewEpoch||identity!==activeIdentity||scope!==$('scope').value)return;await reviewRecord(record);}catch(err){notice(err.message,true);}});
    form.addEventListener('submit',async e=>{e.preventDefault();if(epoch!==reviewEpoch||identity!==activeIdentity||scope!==$('scope').value){notice('范围或身份已变化，请重新打开审核。',true);return;}save.disabled=true;const body={revision:record.governance.revision};for(const [key,input] of Object.entries(fields))body[key]=input.value||null;try{change.apply(body);await api('/records/'+record.id+'/governance',body);if(epoch!==reviewEpoch||identity!==activeIdentity||scope!==$('scope').value)return;$('review-dialog').close();notice('审核状态已保存，来源和旧版本保留。'+($('record-governance').value==='candidate'&&body.state!=='candidate'?'该记录已退出待核实列表；可切换状态查看。':''));await refresh();}catch(err){if(epoch===reviewEpoch&&identity===activeIdentity&&scope===$('scope').value){notice(err.message,true);save.disabled=false;}}});$('review-notice').hidden=true;if(!$('review-dialog').open)$('review-dialog').showModal();
  }
  const agentManage=node('button','Agent 接入');agentManage.hidden=true;
  $('refresh').after(agentManage);agentManage.addEventListener('click',()=>manageAgents().catch(err=>notice(err.message,true)));
  async function manageAgents(){
    const epoch=++reviewEpoch,activeIdentity=identity;const data=await api('/agent-credentials');if(identity!==activeIdentity||epoch!==reviewEpoch)return;
    const host=$('review-content');host.replaceChildren();$('review-title').textContent='Agent 接入';
    host.dataset.credentials='1';host.append(node('p','每个 Agent 单独凭据。读取与写入分开，原值仅创建时显示一次，撤销立即生效。','muted'));
    const form=node('form'),label=node('input'),scope=node('select'),days=node('input'),source=node('input'),write=node('input');
    label.placeholder='用途，例如 ArkClaw 个人记忆';label.required=true;label.maxLength=120;label.setAttribute('aria-label','凭据用途');
    for(const v of identity.scopes){const option=node('option',v);option.value=v;scope.append(option);}if(identity.scopes.includes('personal'))scope.value='personal';scope.setAttribute('aria-label','授权范围');
    days.type='number';days.value=30;days.min=1;days.max=90;days.required=true;days.setAttribute('aria-label','有效天数');
    source.type='checkbox';source.style.width='auto';const sourceLabel=node('label','允许查看原文');sourceLabel.prepend(source);source.disabled=!identity.actions.includes('source_read');
    write.type='checkbox';write.style.width='auto';const writeLabel=node('label','允许归档到独立收件箱（不触发模型提炼）');writeLabel.prepend(write);
    function allowedWrite(){write.disabled=!scope.value.startsWith('agent:')||!scope.value.endsWith('-inbox');if(write.disabled)write.checked=false;}scope.addEventListener('change',allowedWrite);allowedWrite();
    const save=node('button','创建凭据','primary');form.append(label,scope,node('label','有效天数（1–90）'),days,sourceLabel,writeLabel,save);host.append(form);
    const secretHost=node('div'),list=node('div');host.append(secretHost,list);
    const isCurrent=()=>epoch===reviewEpoch&&identity===activeIdentity&&host.contains(form)&&$('review-dialog').open;
    function render(rows){list.replaceChildren();if(!rows.length)list.append(node('p','尚无可管理的 Agent 凭据。','muted'));
      for(const row of rows){const card=node('article',undefined,'record');card.append(node('h3',row.description||row.id),node('p',row.scopes.join('、')+' · '+row.actions.join(' / ')+' · '+({active:'有效',expired:'已到期',revoked:'已撤销'}[row.state]||row.state),'muted'),node('p',row.expires_at?'到期：'+new Date(row.expires_at*1000).toLocaleString():'未设置到期','muted'));
        if(row.actions.includes('write'))card.append(node('p',row.archive_only===true?'写入只归档，模型提炼和再次提炼被禁止。':'旧版写入凭据未限制模型调用；需要时撤销并创建新版凭据。','muted'));
        if(row.state==='active'){const revoke=node('button','撤销');revoke.addEventListener('click',async()=>{revoke.disabled=true;try{await api('/agent-credentials/'+encodeURIComponent(row.id)+'/revoke',{});const result=await api('/agent-credentials');if(isCurrent())render(result.credentials);}catch(err){if(isCurrent()){notice(err.message,true);revoke.disabled=false;}}});card.append(revoke);}list.append(card);}}
    render(data.credentials);if(data.truncated)host.append(node('p','当前展示前100份；更多凭据请联系维护者。','muted'));
    let fingerprint,requestKey;
    form.addEventListener('submit',async e=>{e.preventDefault();secretHost.replaceChildren();const body={description:label.value,scopes:[scope.value],actions:['read'],days:Number(days.value)};if(source.checked)body.actions.push('source_read');if(write.checked)body.actions.push('write');const current=JSON.stringify(body);if(current!==fingerprint){fingerprint=current;requestKey=crypto.randomUUID();}body.request_key=requestKey;save.disabled=true;
      try{const result=await api('/agent-credentials',body);if(!isCurrent())return;
        if(result.token){const raw=node('textarea');raw.readOnly=true;raw.value=result.token;raw.autocomplete='off';raw.setAttribute('aria-label','新Token，仅显示一次');secretHost.append(node('p','请现在复制到 Agent 的私有认证配置。关闭后不再显示；不要放进聊天、URL或公开仓库。','muted'),raw);}else secretHost.append(node('p',result.notice||'原值不能恢复，请撤销后重新创建。','muted'));
        const latest=await api('/agent-credentials');if(isCurrent()){render(latest.credentials);save.disabled=false;}}
      catch(err){if(isCurrent()){notice(err.message,true);save.disabled=false;}}
    });$('review-notice').hidden=true;if(!$('review-dialog').open)$('review-dialog').showModal();
  }
  $('review-dialog').addEventListener('cancel',()=>{++reviewEpoch;});
  $('review-dialog').addEventListener('close',()=>{++reviewEpoch;if($('review-content').dataset.credentials){$('review-content').querySelectorAll('textarea').forEach(input=>{input.value='';});$('review-content').replaceChildren();delete $('review-content').dataset.credentials;}});
  $('daily-upload').addEventListener('click',()=>{location.hash='ingest';$('processing-policy').value='archive';showView();if(identity?.can_correct)refreshMaterials(true).catch(err=>notice(err.message,true));});
  $('daily-review').addEventListener('click',()=>{location.hash='records';$('record-governance').value='candidate';$('history').checked=false;$('query').value='';$('record-kind').value='';$('record-status').value='';showView();refresh();});
  $('daily-owner-add').addEventListener('click',()=>{
    if(!identity?.can_correct || !identity.actions.includes('write') || !identity.scopes.includes('personal'))return;
    if($('scope').value!=='personal'){$('scope').value='personal';$('scope').dispatchEvent(new Event('change'));}
    $('history').checked=false;$('query').value='';$('record-kind').value='';$('record-status').value='';$('record-governance').value='candidate';
    location.hash='records';showView();ownerEditor();refresh();
  });
  const ownerAdd=node('button','新增本人陈述','primary');ownerAdd.hidden=true;
  $('records').before(ownerAdd);ownerAdd.addEventListener('click',()=>ownerEditor());
  function ownerEditor(record){
    ++reviewEpoch;const activeIdentity=identity,scope=record?.scope||$('scope').value,host=$('review-content');
    host.replaceChildren();$('review-title').textContent=record?'补充 / 修改记忆':'新增本人陈述';
    host.append(node('p','保存为待核实候选；关于自己的陈述，可在「核实 / 标记」中选择本人，并填写实际成立时间。引用他人观点时保留其归属。旧版本与原证据保留，不调用模型。','muted'));
    const form=node('form'),grid=node('div',undefined,'review-grid'),fields={};
    function field(key,title,value,choices){const box=node('div'),input=node(choices?'select':key==='statement'?'textarea':'input');input.setAttribute('aria-label',title);
      if(choices)for(const [v,t] of choices){const option=node('option',t);option.value=v;input.append(option);}
      input.value=value||'';fields[key]=input;box.append(node('label',title),input);grid.append(box);return input;}
    const statement=field('statement','陈述正文',record?.statement);statement.required=true;statement.maxLength=2000;
    field('topic','主题',record?.topic||'topics',Object.entries(labels).filter(([k])=>['profile','preferences','people','areas','projects','topics'].includes(k)));
    field('kind','类型',record?.kind||'claim',[['claim','陈述'],['identity','身份'],['preference','偏好'],['relationship','关系'],['decision','决策'],['plan','计划'],['event','事件'],['suggestion','建议']]);
    field('subject','关于谁 / 什么',record?.subject||'未指定').maxLength=160;
    const governanceFields={};
    if(record){const details=node('details');details.open=true;details.append(node('summary','归属与有效时间（可修改；未知留空）'));
      for(const [key,title] of [['holder','主张者稳定 ID'],['subject_id','对象稳定 ID'],['as_of','成立日期'],['valid_until','失效日期'],['priority','优先级'],['note','审核依据']]){
        const box=node('div'),input=node(key==='priority'?'select':'input');input.setAttribute('aria-label',title);
        if(key==='priority')for(const v of ['P0','P1','P2','P3']){const option=node('option',v);option.value=v;input.append(option);}
        else input.type=['as_of','valid_until'].includes(key)?'date':'text';
        input.value=record.governance?.[key]||(key==='priority'?'P3':'');governanceFields[key]=input;box.append(node('label',title),input);details.append(box);}
      form.append(details);}
    const change=changeFields(grid,{existing:!!record,owner:true});const save=node('button','保存候选','primary');form.prepend(grid);form.append(save);host.append(form);
    let fingerprint,requestKey;
    form.addEventListener('submit',async e=>{e.preventDefault();if(identity!==activeIdentity||$('scope').value!==scope){notice('范围或身份已变化，请重新打开编辑。',true);return;}
      const body={scope,governance:{state:'candidate'}};
      for(const [key,input] of Object.entries(governanceFields))body.governance[key]=input.value||null;
      for(const [key,input] of Object.entries(fields))body[key]=input.value;
      try{change.apply(body);}catch(err){notice(err.message,true);return;}
      if(record){body.revision=record.revision;body.governance_revision=record.governance?.revision||0;}
      const current=JSON.stringify(body);if(fingerprint!==current){fingerprint=current;requestKey=crypto.randomUUID();}body.request_key=requestKey;save.disabled=true;
      try{await api(record?'/records/'+record.id+'/revise':'/owner-records',body);if(identity!==activeIdentity||$('scope').value!==scope||!host.contains(form)||!$('review-dialog').open)return;$('review-dialog').close();notice(body.governance.state==='rejected'?'已设为不采纳，旧版本保留；未调用模型。':'候选已保存，索引自动更新；未调用模型。');await refresh();}
      catch(err){if(identity===activeIdentity&&$('scope').value===scope&&host.contains(form)&&$('review-dialog').open){notice(err.message,true);save.disabled=false;}}
    });$('review-notice').hidden=true;if(!$('review-dialog').open)$('review-dialog').showModal();
  }
  $('review-close').addEventListener('click',()=>{++reviewEpoch;$('review-dialog').close();});

  function updateSpaceLabel(){ $('space-label').textContent='正在查看：'+$('scope').selectedOptions[0].textContent; }
  $('scope').addEventListener('change',()=>{++reviewEpoch;$('review-dialog').close();documentCategory='';documentLeaf=false;updateSpaceLabel();$('document-reader').close();});
  function openDocument(title,text,markdown=false){$('reader-title').textContent=title;const host=$('reader-body');host.replaceChildren();if(!markdown){host.append(node('pre',text));}else{let front=false;for(const line of text.split('\n')){if(line==='---'){front=!front;continue;}if(front)continue;const heading=line.match(/^(#{1,3}) (.*)$/);if(heading)host.append(node('h'+heading[1].length,heading[2]));else if(line.startsWith('> '))host.append(node('blockquote',line.slice(2)));else if(line.startsWith('- '))host.append(node('p','• '+line.slice(2)));else if(line.trim())host.append(node('p',line));}}$('document-reader').showModal();}
  $('reader-close').addEventListener('click',()=>{++ledgerEpoch;$('document-reader').close();});
  $('document-reader').addEventListener('cancel',()=>{++ledgerEpoch;});
  $('search-form').addEventListener('submit',e=>{e.preventDefault();refresh();});['scope','history'].forEach(id=>$(id).addEventListener('change',refresh));$('refresh').addEventListener('click',refresh);
  $('document-search-form').addEventListener('submit',async e=>{e.preventDefault();try{await refreshDocuments();}catch(err){notice(err.message,true);}});
  let evidenceNext=null, evidenceQuery='', evidenceScope='';
  let ledgerEpoch=0;
  function ledgerButton(kind,id,scope){
    const button=node('button','治理账本');
    button.addEventListener('click',async()=>{button.disabled=true;try{await openLedger(kind,id,scope);}catch(err){notice(err.message,true);}finally{button.disabled=false;}});
    return button;
  }
  async function openLedger(kind,id,scope,offset=0){
    const epoch=++ledgerEpoch, activeIdentity=identity, activeToken=token, activeScope=$('scope').value;
    const data=await api('/'+kind+'/'+encodeURIComponent(id)+'/ledger?'+new URLSearchParams({scope,limit:20,offset}));
    if(epoch!==ledgerEpoch||identity!==activeIdentity||token!==activeToken||$('scope').value!==activeScope)return;
    const host=$('reader-body');host.replaceChildren();$('reader-title').textContent='治理账本 · '+(data.source?.title||data.source?.source_title||data.source?.source_key||'资料');
    host.append(node('p','原文归档、候选与当前可用记忆分别记录；这里只读查看，不调用模型。','muted'));
    const summary=data.summary||{},metrics=node('div',undefined,'job-summary');
    for(const [key,title] of [['records_total','关联记录'],['current_usable','当前可用'],['candidate','待核实'],['historical','历史记录'],['rejected','不采纳']]){const box=node('article',undefined,'record');box.append(node('strong',String(summary[key]??0)),node('p',title,'muted'));metrics.append(box);}host.append(metrics);
    host.append(node('p','来源可见范围：'+(data.source?.visibility||'unknown')+'；未知范围不能视为完整。','muted'));
    if(data.source?.withdrawal)host.append(node('p','来源已撤回：原件和历史保留，关联内容不作为当前可用记忆。','muted'));
    if(data.focal_record)host.append(node('p','当前追查记忆：'+data.focal_record.id+' / v'+data.focal_record.revision,'muted'));
    host.append(node('h3','记忆与证据关联'));
    if(!data.records?.length)host.append(node('p','本页没有关联记忆；不代表资料已经完成治理。','muted'));
    for(const record of data.records||[]){const card=node('article',undefined,'record');card.append(node('p',record.statement||record.id),node('p',(record.usable?'当前可用':'当前不可用')+' · '+(record.governance?.state||record.governance_state||record.lifecycle||'状态未记录'),'muted'));if(record.exclusion_reasons?.length)card.append(node('p','原因：'+record.exclusion_reasons.map(reason=>({source_withdrawn:'来源已撤回',inactive_revision:'旧版本',not_verified:'尚未核实',incomplete_attribution_or_time:'归属或成立时间不完整',not_yet_effective:'尚未生效',expired:'已过有效期',invalid_governance:'治理字段无效'}[reason]||reason)).join('；'),'muted'));const evidence=record.evidence||{};card.append(node('p','证据消息：'+(evidence.message_id||record.message_id||'未记录')+' · '+(evidence.role||'角色未记录')+' · '+(evidence.created_at||evidence.date||'日期未记录'),'muted'));host.append(card);}
    host.append(node('h3','处理任务与方法'));
    for(const job of [...(data.jobs||[]),...(data.runs||[])]){const card=node('article',undefined,'record');card.append(node('p',(labels[job.state]||job.state||'未知')+' · '+methodLabel(job.method_version)),node('p','任务 '+job.id,'muted'));if(job.error_present)card.append(node('p','任务记录了异常；请在处理任务中查看。','muted'));const usage=job.usage||{},known=usage.total_tokens;card.append(node('p',usage.state==='model_skipped'?'未调用模型':usage.state==='measured'?(known===null||known===undefined?'已记录部分模型用量，合计未知':'已计量 '+known+' tokens'):'模型用量未记录','muted'));host.append(card);}
    if(!data.jobs?.length&&!data.runs?.length)host.append(node('p','本页无处理任务。','muted'));
    host.append(node('h3','费用证据'));host.append(node('p','无可核对的金额凭据时，费用记为未知；不能把未记录当作零。','muted'));
    host.append(node('p','文档引用仅覆盖本页扫描的存储版本，包含历史；不是全部当前文档。','muted'));
    host.append(node('h3','文档引用'));
    for(const document of data.documents||[])host.append(node('p',(document.title||document.slug||'文档')+' · 版本 '+(document.revision??'未知'),'muted'));
    if(!data.documents?.length)host.append(node('p','本页未找到确切的文档引用；不猜测语义关联。','muted'));
    if(identity?.can_correct&&identity.actions.includes('write')&&!data.source?.withdrawal){
      const preview=node('button','查看来源撤回影响'),panel=node('section',undefined,'record');host.append(preview,panel);
      const current=()=>epoch===ledgerEpoch&&identity===activeIdentity&&token===activeToken&&$('scope').value===activeScope&&$('document-reader').open;
      preview.addEventListener('click',async()=>{preview.disabled=true;try{
        const impact=await api('/sources/'+encodeURIComponent(data.source.id)+'/withdrawal-preview?'+new URLSearchParams({scope,max_chars:6000}));if(!current())return;panel.replaceChildren();
        panel.append(node('h3','撤回这一个资料版本'),node('p','影响 '+impact.counts.records+' 条直接关联记录，'+impact.counts.jobs+' 个任务，'+impact.counts.document_versions+' 个文档历史引用。原件和历史仍保留；不自动撤回其他分段或独立来源。'));
        if(!impact.withdrawal_supported){panel.append(node('p','当前服务未启用来源撤回迁移。','muted'));return;}
        if(impact.blockers?.length){panel.append(node('p','历史批次仍在处理或预算未结算，请待结算后再撤回。','muted'));return;}
        const form=node('form'),reason=node('input');reason.maxLength=500;reason.setAttribute('aria-label','来源撤回说明');reason.placeholder='撤回原因（可选）';
        const check=node('input');check.type='checkbox';check.required=true;check.style.width='auto';const label=node('label',undefined,'row');label.append(check,node('span','确认停止使用此资料版本作为当前证据；保留原件和历史'));
        const submit=node('button','确认撤回此来源');submit.type='submit';form.append(reason,label,submit);panel.append(form);
        form.addEventListener('submit',async event=>{event.preventDefault();if(!current()||!check.checked)return;submit.disabled=true;try{const receipt=await api('/sources/'+encodeURIComponent(data.source.id)+'/withdraw',{scope,reason:reason.value});if(!current())return;panel.replaceChildren(node('p',receipt.state==='withdrawn'?'来源已撤回；历史保留，外部已发送的上下文无法收回。':'服务未确认来源撤回。'));preview.hidden=true;await openLedger(kind,id,scope,offset);await refresh();}catch(err){if(current()){notice(err.message,true);submit.disabled=false;}}});
      }catch(err){if(current())notice(err.message,true);}finally{if(current())preview.disabled=false;}});
    }
    const pagination=data.pagination||{};if(Object.values(pagination).some(page=>page?.truncated)){const more=node('button','查看下一页关联');more.addEventListener('click',()=>openLedger(kind,id,scope,offset+20).catch(err=>notice(err.message,true)));host.append(more);}
    if(!$('document-reader').open)$('document-reader').showModal();
  }
  function openDependencyPreview(impact,source){
    $('reader-title').textContent='资料关联 · '+(source.source_title||'原文');
    const host=$('reader-body');host.replaceChildren();
    host.append(node('p','显示这份资料直接关联的记忆、任务与主题文档。','muted'));
    const counts=node('div',undefined,'job-summary');
    const names={records:'已整理记忆',jobs:'资料处理任务',extraction_runs:'再次提炼任务',document_versions:'文档版本引用',topic_rules:'可能关联的主题',index_chunks:'可检索片段'};
    for(const [key,title] of Object.entries(names)){const item=node('article',undefined,'record');item.append(node('strong',String(impact.counts[key]||0)),node('p',title,'muted'));counts.append(item);}host.append(counts);
    if(!impact.counts.records)host.append(node('p','此资料版本尚无直接关联的已整理记忆。'));
    if(impact.risks.includes('unfinished_processing'))host.append(node('p','还有未完成的处理任务。'));
    if(impact.counts.document_versions)host.append(node('p','文档数量包含历史版本，不能等同于当前主题数量。','muted'));
    host.append(node('p','间接关联与外部缓存尚未包含在此预览中。','muted'));
    $('document-reader').showModal();
  }
  async function searchEvidence(append=false){
    const scope=$('scope').value, query=$('evidence-query').value, activeIdentity=identity, activeToken=token;
    const offset=append?evidenceNext:0;
    if(append && (scope!==evidenceScope || query!==evidenceQuery || offset===null))return;
    const data=await api('/archive-search?'+new URLSearchParams({scope,q:query,offset,max_chars:16000}));
    if(identity!==activeIdentity || token!==activeToken || scope!==$('scope').value || query!==$('evidence-query').value)return;
    evidenceScope=scope;evidenceQuery=query;evidenceNext=data.next_offset;
    if(!append)$('evidence-list').replaceChildren();
    $('evidence-summary').textContent=data.total+' 个匹配片段 · 仅已建索引的资料 · 不使用模型 tokens';
    $('evidence-more').hidden=evidenceNext===null;
    for(const result of data.results){
      const card=node('article',undefined,'record topic-tile');
      card.append(node('span',result.material_type==='imported_summary'?'已有摘要 · 二手来源':result.material_type==='document'?'上传文档':result.role==='user'?'用户发言':result.role==='assistant'?'助手发言':'外部材料','tag'),node('h3',result.source_title||result.source_key),node('p',result.source_date||'来源时间未知','muted'),node('p',result.snippet,'tile-excerpt'));
      const read=node('button','展开出处','primary');read.addEventListener('click',async()=>{
        try{const page=await api('/archive-source',{scope,locator:result.locator,max_chars:8000});
          if(identity!==activeIdentity || token!==activeToken || scope!==$('scope').value)return;
          openDocument((result.source_title||'原文')+' · '+result.role,page.text);
          const more=node('button','继续阅读');more.hidden=page.next_offset===null;let next=page.next_offset;
          more.addEventListener('click',async()=>{try{const part=await api('/archive-source',{scope,locator:result.locator,offset:next,max_chars:8000});if(identity!==activeIdentity || token!==activeToken || scope!==$('scope').value)return;$('reader-body').append(node('pre',part.text));next=part.next_offset;more.hidden=next===null;}catch(err){notice(err.message,true);}});
          $('reader-body').append(more);
        }catch(err){notice(err.message,true);}
      });card.append(read);
      const dependencies=node('button','关联内容');dependencies.addEventListener('click',async()=>{try{const impact=await api('/sources/'+encodeURIComponent(result.source_id)+'/dependencies?'+new URLSearchParams({scope,max_chars:10000}));if(identity!==activeIdentity || token!==activeToken || scope!==$('scope').value)return;openDependencyPreview(impact,result);}catch(err){notice(err.message,true);}});card.append(dependencies);$('evidence-list').append(card);
    }
  }
  $('evidence-form').addEventListener('submit',e=>{e.preventDefault();searchEvidence().catch(err=>notice(err.message,true));});
  $('evidence-more').addEventListener('click',()=>searchEvidence(true).catch(err=>notice(err.message,true)));
  $('evidence-index').addEventListener('click',async()=>{const button=$('evidence-index');button.disabled=true;try{const result=await api('/archive-index',{scope:$('scope').value});notice('索引更新完成：'+result.indexed_sources+' 份更新，'+result.unchanged_sources+' 份未变；'+result.skipped_legacy_sources+' 份旧投影保留在档案中；没有调用模型。');await searchEvidence();}catch(err){notice(err.message,true);}finally{button.disabled=false;}});
  $('scope').addEventListener('change',()=>{$('evidence-list').replaceChildren();$('evidence-summary').textContent='';$('evidence-more').hidden=true;evidenceNext=null;});

  let configurationData=null, configurationEpoch=0, configurationOffset=0, configurationEventOffset=0, mapEpoch=0, mapNext=null;
  function downloadText(name,text){const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=node('a');a.href=url;a.download=name;a.hidden=true;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
  function configurationFields(){const kind=$('configuration-kind').value;for(const k of ['prompt','model','skill'])$('config-'+k+'-fields').hidden=k!==kind;}
  $('configuration-kind').addEventListener('change',configurationFields);
  async function downloadSkill(params,filename){
    const who=identity,scope=$('scope').value;
    const response=await fetch(prefix+'/configuration/skill-download?'+new URLSearchParams({...params,scope}),{headers:token?{Authorization:'Bearer '+token}:{'X-Memory-Local':'1'},cache:'no-store'});
    if(!response.ok){const data=await response.json();throw new Error(data.error||'下载失败');}
    const text=await response.text();
    if(identity!==who||$('scope').value!==scope)throw new Error('范围已变化，请重新下载。');
    if(!token && !['localhost','127.0.0.1','::1'].includes(location.hostname)){
      const link=node('a');link.href=prefix+'/configuration/skill-download?'+new URLSearchParams({...params,scope});link.download=filename;document.body.append(link);link.click();link.remove();
    }else downloadText(filename,text);
    notice('Skill 文件已交给浏览器下载；客户端安装状态未知。');
  }
  async function refreshConfiguration(reset=true){
    if(reset){configurationOffset=0;configurationEventOffset=0;}
    const epoch=++configurationEpoch,scope=$('scope').value,who=identity;
    const data=await api('/configuration?'+new URLSearchParams({scope,offset:configurationOffset,event_offset:configurationEventOffset,limit:20}));
    if(epoch!==configurationEpoch||identity!==who||scope!==$('scope').value)return;
    configurationData=data;
    const kindLabel={prompt:'提炼提示',model:'模型连接',skill:'Skill 草稿'};
    $('configuration-status').replaceChildren(...[['基础方法',data.baseline.version],['模型密钥',data.model.configured?'服务端已配置':'未配置'],['MCP 工具',data.integration.tools.length+' 个'],['配置作用域',scope]].map(([label,value])=>{const c=node('div',undefined,'job-metric');c.append(node('strong',value),node('span',label));return c;}));
    $('configuration-baseline').textContent=data.baseline.prompt;
    const current=$('configuration-active');current.replaceChildren();
    for(const kind of ['prompt','model']){
      const item=data.active[kind],card=node('article',undefined,'config-version');
      card.append(node('h4',kindLabel[kind]+' · '+(item?'已启用版本':'使用服务端基础配置')));
      card.append(node('p',item?item.version.label+' · revision '+item.revision+' · '+item.version_id:kind==='prompt'?data.baseline.version:data.model.model||'模型未指定','muted'));
      if(item){const detail=node('details');detail.append(node('summary','查看当前有效配置'),node('pre',JSON.stringify(item.version.payload,null,2)));card.append(detail);}current.append(card);
    }
    const modelPayload=data.active.model?.version.payload||data.model;
    $('configuration-base').value=modelPayload.base_url;$('configuration-model').value=modelPayload.model;
    $('configuration-output').value=modelPayload.max_tokens||4096;
    const host=$('configuration-versions');host.replaceChildren();
    host.append(node('p','共 '+data.total+' 个版本 · 当前 '+(data.total?data.offset+1:0)+'–'+(data.offset+data.versions.length),'muted'));
    if(!data.versions.length)host.append(node('p','本页无配置草稿。','muted'));
    for(const v of data.versions){
      const card=node('article',undefined,'config-version');const active=data.active[v.kind];
      card.append(node('h4',v.label),node('p',kindLabel[v.kind]+' · '+(v.kind==='skill'?'草稿 · 客户端安装未知':active?.version_id===v.id?'已启用':'未启用')+' · '+new Date(v.created*1000).toLocaleString('zh-CN'),'muted'));
      const details=node('details');details.append(node('summary','查看内容'),node('pre',JSON.stringify(v.payload,null,2)));card.append(details);
      const actions=node('div',undefined,'tile-actions');
      if(v.kind==='skill'){const exportButton=node('button','导出草稿 SKILL.md');exportButton.addEventListener('click',()=>downloadSkill({version_id:v.id},v.payload.name+'-SKILL.md').catch(err=>notice(err.message,true)));actions.append(exportButton);}
      else if(active?.version_id!==v.id){
        const note=node('textarea');note.maxLength=1000;note.placeholder='样本验证结果，或恢复旧版的依据（至少 10 字符）';note.setAttribute('aria-label','启用 '+v.label+' 的依据');card.append(note);
        const activate=node('button','启用此版本','primary');activate.addEventListener('click',async()=>{if(identity!==who||$('scope').value!==scope){notice('范围已变化，请刷新配置。',true);return;}activate.disabled=true;try{await api('/configuration/versions/'+v.id+'/activate',{scope,revision:active?.revision||0,note:note.value});await refreshConfiguration();notice('配置已启用；不修改已有记忆，不恢复暂停队列。');}catch(err){notice(err.message,true);}finally{activate.disabled=false;}});actions.append(activate);
      }
      card.append(actions);host.append(card);
    }
    function pageButton(parent,title,handler){const b=node('button',title);b.type='button';b.addEventListener('click',()=>{handler();refreshConfiguration(false).catch(err=>notice(err.message,true));});parent.append(b);}
    const pages=node('div',undefined,'tile-actions');
    if(data.offset>0)pageButton(pages,'上一页版本',()=>configurationOffset=Math.max(0,data.offset-20));
    if(data.next_offset!==null)pageButton(pages,'下一页版本',()=>configurationOffset=data.next_offset);host.append(pages);
    const choices=[...new Map([...data.versions,...Object.values(data.active).map(a=>a.version)].map(v=>[v.id,v])).values()];
    const compareHost=$('configuration-compare');compareHost.replaceChildren(node('p','比较本页或当前启用版本。翻页可选择更早版本；差异展示不代表语义质量已通过。','muted'));
    const selects=['旧版本','新版本'].map(title=>{const select=node('select');select.setAttribute('aria-label',title);for(const v of choices){const option=node('option',kindLabel[v.kind]+' · '+v.label+' · '+v.id.slice(0,8));option.value=v.id;select.append(option);}compareHost.append(select);return select;});
    if(choices.length>1)selects[1].selectedIndex=1;
    const compareButton=node('button','比较版本');compareButton.disabled=choices.length<2;const output=node('pre');
    compareButton.addEventListener('click',async()=>{compareButton.disabled=true;try{const result=await api('/configuration/compare?'+new URLSearchParams({scope,left:selects[0].value,right:selects[1].value}));if(identity===who&&scope===$('scope').value&&epoch===configurationEpoch)output.textContent=result.changed?result.diff:'内容相同。';}catch(err){notice(err.message,true);}finally{compareButton.disabled=choices.length<2;}});
    compareHost.append(compareButton,output);
    $('configuration-events').replaceChildren(node('p','共 '+data.event_total+' 次启用 · 本页 '+data.events.length+' 次','muted'),...data.events.map(e=>node('p',new Date(e.created*1000).toLocaleString('zh-CN')+' · '+kindLabel[e.kind]+' · '+(e.previous_id||'基础配置')+' → '+e.version_id+' · '+e.note,'muted')));
    if(data.event_offset>0)pageButton($('configuration-events'),'上一页启用记录',()=>configurationEventOffset=Math.max(0,data.event_offset-30));
    if(data.event_next_offset!==null)pageButton($('configuration-events'),'下一页启用记录',()=>configurationEventOffset=data.event_next_offset);
    const integrations=$('configuration-integrations');integrations.replaceChildren(node('p',data.integration.note),node('p','MCP：此服务代码契约 '+data.integration.contract_sha256.slice(0,16)+' · 客户端连接与版本未核验'),node('p',data.integration.tools.join(' · ')));
    if(identity.can_manage_agents){const credentials=node('button','管理 Agent 凭据与权限');credentials.addEventListener('click',()=>manageAgents().catch(err=>notice(err.message,true)));integrations.append(credentials);}
    for(const skill of data.integration.skills){const detail=node('details');detail.append(node('summary',skill.name+' · 随此服务代码打包 · 客户端安装未知 · '+skill.sha256.slice(0,12)),node('pre',skill.instructions));const exportButton=node('button','下载随代码打包的 Skill');exportButton.addEventListener('click',()=>downloadSkill({name:skill.name},skill.name+'-SKILL.md').catch(err=>notice(err.message,true)));detail.append(exportButton);integrations.append(detail);}
  }
  $('configuration-refresh').addEventListener('click',()=>refreshConfiguration().catch(err=>notice(err.message,true)));
  $('configuration-form').addEventListener('submit',async e=>{
    e.preventDefault();const button=e.submitter;button.disabled=true;
    const kind=$('configuration-kind').value,scope=$('scope').value;
    const payload=kind==='prompt'?{instructions:$('configuration-instructions').value}:kind==='model'?{base_url:$('configuration-base').value,model:$('configuration-model').value,max_tokens:Number($('configuration-output').value)}:{name:$('configuration-skill-name').value,version:$('configuration-skill-version').value,instructions:$('configuration-skill-text').value};
    try{await api('/configuration/versions',{scope,kind,label:$('configuration-label').value,payload});await refreshConfiguration();notice('草稿已保存，尚未影响处理任务。');}catch(err){notice(err.message,true);}finally{button.disabled=false;}
  });
  function renderMapRecord(record,data){
    const host=$('map-diagram'),details=$('map-details');host.replaceChildren();details.replaceChildren();
    const recordId='record:'+record.id, edges=data.edges.filter(e=>e.source===recordId),targets=edges.map(e=>data.nodes.find(n=>n.id===e.target));
    const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 620 '+Math.max(190,targets.length*100));svg.setAttribute('role','img');svg.setAttribute('aria-label','所选记忆的来源与治理关系');
    const height=Math.max(190,targets.length*100),mid=height/2;
    function box(x,y,label,kind){const rect=document.createElementNS(ns,'rect');for(const [k,v]of Object.entries({x,y:y-28,width:210,height:56,rx:7}))rect.setAttribute(k,v);svg.append(rect);const text=document.createElementNS(ns,'text');text.setAttribute('x',x+105);text.setAttribute('y',y-3);text.setAttribute('text-anchor','middle');text.textContent=kind;svg.append(text);const sub=document.createElementNS(ns,'text');sub.setAttribute('x',x+105);sub.setAttribute('y',y+16);sub.setAttribute('text-anchor','middle');sub.textContent=label.slice(0,18);svg.append(sub);}
    edges.forEach((edge,i)=>{const y=50+i*100;const path=document.createElementNS(ns,'path');path.setAttribute('d','M230 '+mid+' L390 '+y);svg.append(path);const text=document.createElementNS(ns,'text');text.setAttribute('x',300);text.setAttribute('y',(mid+y)/2-8);text.setAttribute('text-anchor','middle');text.textContent=edge.relation+' →';svg.append(text);box(390,y,targets[i].label,targets[i].kind==='source'?'原文来源':targets[i].kind==='subject'?'讨论对象':targets[i].kind==='holder'?'观点持有者':'旧版本');});
    box(20,mid,record.statement,'所选记忆');host.append(svg);
    details.append(node('h3',record.statement),node('p','状态：'+(record.usable?'可供 Agent 使用':record.governance.state==='verified'?'已核实 · 当前不满足使用条件':record.governance.state==='candidate'?'待核实':record.governance.state)+' · '+(labels[record.lifecycle]||record.lifecycle),'tag'),node('p','成立时间：'+(record.governance.as_of||'未知')+'；失效时间：'+(record.governance.valid_until||'未指定'),'muted'));
    const quote=node('details');quote.append(node('summary','原文证据（最多 500 字符预览）'),node('blockquote',record.quote));details.append(quote);
    const read=node('button','查看原文消息');read.addEventListener('click',async()=>{const scope=$('scope').value,who=identity;try{const raw=await api('/source?'+new URLSearchParams({source_id:record.source_id,message_id:record.message_id,scope}));if(scope!==$('scope').value||who!==identity)return;openDocument('原文依据',JSON.stringify(raw,null,2));}catch(err){notice(err.message,true);}});details.append(read);
  }
  async function refreshMap(offset=0){
    const epoch=++mapEpoch,scope=$('scope').value,who=identity;
    const data=await api('/memory-map?'+new URLSearchParams({scope,q:$('map-query').value,state:$('map-state').value,offset,limit:40}));
    if(epoch!==mapEpoch||scope!==$('scope').value||identity!==who)return;
    mapNext=data.next_offset;$('map-more').hidden=mapNext===null;
    $('map-summary').textContent='匹配 '+data.total+' 条；本页 '+data.records.length+' 条 · 关系来自已有字段，缺失归属不会自动推断。';
    const host=$('map-records');host.replaceChildren();$('map-diagram').replaceChildren();$('map-details').replaceChildren();
    for(const r of data.records){const b=node('button',r.statement,'map-record');b.addEventListener('click',()=>{host.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderMapRecord(r,data);});host.append(b);}
    if(data.records.length){host.querySelector('button').setAttribute('aria-pressed','true');renderMapRecord(data.records[0],data);}else host.append(node('p','此范围没有匹配的记忆。可先查看原文检索，或在记忆管理中补充。','muted'));
  }
  $('map-form').addEventListener('submit',e=>{e.preventDefault();refreshMap().catch(err=>notice(err.message,true));});
  $('map-more').addEventListener('click',()=>{if(mapNext!==null)refreshMap(mapNext).catch(err=>notice(err.message,true));});
  $('scope').addEventListener('change',()=>{configurationData=null;configurationOffset=0;configurationEventOffset=0;++configurationEpoch;++mapEpoch;$('configuration-active').replaceChildren();$('configuration-compare').replaceChildren();mapNext=null;$('configuration-versions').replaceChildren();$('configuration-events').replaceChildren();$('map-records').replaceChildren();$('map-diagram').replaceChildren();$('map-details').replaceChildren();showView();});

  function showView() {
    const requested=location.hash.slice(1);
    const view=['documents','records','ingest','jobs','archives','evidence','configuration','map'].includes(requested)?requested:'documents';
    if(identity && view==='configuration' && identity.can_correct)refreshConfiguration().catch(err=>notice(err.message,true));
    if(identity && view==='map')refreshMap().catch(err=>notice(err.message,true));
    document.querySelectorAll('[data-panel]').forEach(el=>{el.hidden=el.dataset.panel!==view;});
    document.querySelectorAll('[data-view]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.view===view)));
  }
  document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{location.hash=button.dataset.view;showView();if(button.dataset.view==='ingest' && identity?.can_correct)refreshMaterials(true).catch(err=>notice(err.message,true));}));
  window.addEventListener('hashchange',showView);
  showView();
  connect();
})();

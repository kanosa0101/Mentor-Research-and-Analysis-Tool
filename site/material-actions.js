/* 公开原文阅读与私人准备记录分离；不上传文件、不使用浏览器持久存储。 */
(function(root){
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stages={application:'报名与材料提交',screening:'初审',interview:'面试与考核',admission:'录取',enrollment:'入学',other:'其他事项'};
  const applicabilityLabels={goal_incomplete:'申请目标不完整，请先编辑项目',program_pending:'专业 / 项目尚未明确，不能确认适用',source_missing:'动作来源未完整登记'};
  const statuses={todo:'待准备',prepared:'已准备',submitted:'已提交（人工记录）',needs_revision:'需补正'};
  function evidence(item){return item?`<p>${escape(item.text)}</p><details><summary>原文与定位</summary><blockquote>${escape(item.quote)}</blockquote><p>${escape(item.locator)}</p></details>`:'';}
  function references(policy,item,data){return (item?.source_ids||[policy.source_id]).map(id=>data.sources[id]).filter(Boolean).map(s=>`<a href="${escape(s.url)}" target="_blank" rel="noopener">${escape(s.label||'官方原文')}</a>`).join(' · ');}
  function publicActions(policy,data){
    if(!policy.material_actions?.length)return '';
    const quality=root.AdmissionsRules.quality(policy,data.checks);
    return `<section class="material-actions"><h3>分阶段材料准备</h3><p>按原文逐项核对适用范围与提交方式；文件存在不表示完成提交。</p><p class="quality ${escape(quality.state)}">${escape(quality.label)}</p>${Object.entries(stages).map(([stage,label])=>{const actions=policy.material_actions.filter(a=>a.stage===stage);return actions.length?`<section><h4>${label}</h4>${actions.map(a=>`<article><h4>${escape(a.label)}</h4>${evidence(a.instruction)}${references(policy,a.instruction,data)}${policy.applies_if?`<p>政策适用条件</p>${evidence(policy.applies_if)}${references(policy,policy.applies_if,data)}`:''}${a.applies_if?`<p>动作适用条件</p>${evidence(a.applies_if)}${references(policy,a.applies_if,data)}`:''}${(a.event_indexes||[]).map(i=>{const e=policy.events[i];return e?`<p>关联事项：${escape(e.label)} · ${escape(e.at)}<br>原文：${escape(e.quote)} · ${escape(e.locator)} · ${references(policy,e,data)}</p>`:'';}).join('')}</article>`).join('')}</section>`:'';}).join('')}</section>`;
  }
  let workflow={projects:{},materials:{}},data={actions:{},records:{}},project='',dirty=false,serial=0,revision=0,hook=null,loadedScope='',loadError='';
  const goalKeys=['school_id','dept_id','year','degree','route','track','program_code','program_name'];
  let filterScope='',stageFilter='',statusFilter='';
  const currentScope=()=>JSON.stringify([project,...goalKeys.map(key=>workflow.projects[project]?.[key]??'')]);
  const dirtyForms=new Set(),openActions=new Set();
  const node=id=>document.getElementById(id);
  function feedback(text,error=false){const n=node('preparation-feedback');if(n){n.textContent=text;n.classList.toggle('error',error);}}
  function discard(){if(!dirty)return true;if(!root.confirm('准备清单有尚未保存的修改，继续会放弃这些修改。继续？'))return false;dirty=false;dirtyForms.clear();revision++;render();return true;}
  async function request(path='',body){const response=await fetch('/api/workflow/material-tasks'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});let result;try{result=await response.json();}catch{throw new Error('服务未返回可读数据，请重试。');}if(!response.ok){const e=new Error(result.error||'请求失败：'+response.status);e.status=response.status;throw e;}return result;}
  async function refresh(next,selected){
    if(!node('preparation-list'))return;
    workflow=next;
    if(project!==selected){if(dirty)return;project=selected;revision++;}
    const ticket=++serial,editRevision=revision,requestedScope=currentScope(),previousLoadError=loadError;loadError='';
    if(!dirty){if(previousLoadError)feedback('');render();}
    else if(loadedScope!==requestedScope){feedback('申请目标已变化；未保存输入与原指纹已保留，请重新核对清单后保存。',true);node('preparation-list').querySelectorAll('[type="submit"],[data-material-reminder]').forEach(b=>b.disabled=true);}
    try{const result=await request();if(ticket!==serial)return;/* Never replace the basis of visible unsaved inputs with a newer policy fingerprint. */if(!dirty&&editRevision===revision){data=result;loadedScope=requestedScope;render();}else {const changed=loadedScope!==requestedScope||JSON.stringify(data.actions?.[project])!==JSON.stringify(result.actions?.[project])||JSON.stringify(data.records)!==JSON.stringify(result.records);feedback(changed?'目标、来源、文件版本或历史检查结果已变化；未保存输入与原指纹已保留。请保存前重新核对清单。':'当前输入已保留；保存时会重新核对目标、来源和文件版本。',changed);}}
    catch(e){if(ticket===serial){loadError=e.message;if(!dirty&&loadedScope!==requestedScope)render();feedback('准备清单暂不可用：'+e.message+' 已有项目、文件与其他记录仍可使用。请点击“重新核对清单”重试后保存。',true);node('preparation-list').querySelectorAll('[type="submit"],[data-material-reminder]').forEach(b=>b.disabled=true);}}
  }
  function conditionText(c){return typeof c==='string'?c:c?.evidence?.text||c?.text||'';}
  function policyReturn(p){
    const scope={school:p.school_id||'',dept:p.dept_id||'',year:p.year,degree:p.degree||'',route:p.route||'',track:p.track||'',program:p.program_name?(p.program_code||'')+'|'+p.program_name:''},query=new URLSearchParams();
    for(const [key,value] of Object.entries(scope))if(value)query.set(key,value);
    const ready=root.AdmissionsRules.checklist(root.ADMISSIONS_DATA,scope).ready;
    const pending=!ready?'申请目标尚未完整或院系尚未确认，请先编辑项目；回查链接仅保留已填范围，未知范围不表示适用。':!p.program_name?'正式专业 / 项目尚未明确；如需核对专业专属要求，请编辑项目补充名称。':'';
    return `<p><a href="admissions.html?${escape(query.toString())}">核对本项目政策与材料要求</a></p>${pending?`<p class="scope-note">${escape(pending)}</p><button type="button" data-project-section="project" data-project-id="${escape(project)}" data-edit-project="${escape(project)}">编辑项目</button>`:''}`;
  }
  function recordHtml(record){
    const reasonLabels={project_missing:'项目已不存在',goal_changed:'项目目标已变化',action_changed:'动作或来源已变化',action_unavailable:'当前目标已无此动作',scope_pending:'适用范围尚待核实',source_changed:'来源已变化',source_error:'来源检查失败',source_stale:'来源检查已过期',source_unknown:'来源状态未知',source_review:'摘要需重新核对',conditions_unconfirmed:'适用条件尚未确认',files_changed:'所用文件版本需复核'};
    const fileLabels={unchanged:'与保存版本一致',changed:'文件已变化',missing:'文件缺失',path_changed:'登记路径已变化',unknown_material:'材料索引已不存在',unreadable:'文件无法读取'};
    const reasons=(record.review_reasons||[]).map(r=>reasonLabels[r]||r),files=record.files||record.attachments||[];
    const goal=record.goal_snapshot||{},action=record.action||{};
    return `<article><h4>${escape(statuses[record.status]||record.status)} · ${escape(record.created_at||'保存时间待核对')}</h4>${reasons.length?`<p class="bad">需复核：${reasons.map(escape).join('；')}</p>`:''}<p>${escape(record.notes)}</p><details><summary>保存时的目标、动作、来源与文件版本</summary><p>目标：${Object.values(goal).filter(Boolean).map(escape).join(' · ')}</p><p>${escape(record.policy_title)} · ${escape(action.label)}</p>${evidence(action.instruction)}${(record.source_snapshot?.conditions||[]).map(c=>`<p>保存时适用条件${record.confirmed_conditions?'（已人工确认）':'（未确认）'}</p>${evidence(c.evidence)}`).join('')}${Object.entries(record.source_snapshot?.sources||{}).map(([id,source])=>`<p>登记时来源 ${escape(id)}：${source.url?`<a href="${escape(source.url)}" target="_blank" rel="noopener">官方原文</a>`:''}<small class="path">${escape(source.hash||source.review_hash||'')}</small></p>`).join('')}${files.map(f=>`<p><strong>${escape(f.title)}</strong> · ${escape(fileLabels[f.state]||'保存时的版本')}<br><span class="path">${escape(f.path)}</span><br><small>保存时 ${escape(f.size)} 字节 · 修改时间 ${escape(f.mtime)}<br>内容指纹 ${escape(f.sha256)}</small></p>`).join('')||'<p>本次未选择文件。</p>'}</details></article>`;
  }
  function registrationState(view){
    const latest=data.records?.[view.latest_record_id];
    if(!latest||latest.review_required||latest.applicable===false||view.can_record===false||view.program_pending||view.quality?.state!=='checked')return 'pending';
    return latest.status==='prepared'||latest.status==='submitted'?latest.status:'pending';
  }
  function render(){
    const list=node('preparation-list');if(!list)return;
    if(filterScope!==currentScope()){filterScope=currentScope();stageFilter='';statusFilter='';}
    const p=workflow.projects[project];
    if(!p){list.innerHTML='<div class="empty"><h3>先选择一个申请项目</h3><p>准备进度按项目和材料动作分别保存。请在上方选择项目，或先创建项目并明确申请目标。</p><button type="button" data-section="project">创建申请项目</button></div>';return;}
    if(loadedScope!==currentScope()){list.innerHTML=`<p class="scope-note">${escape(p.name)}</p><p role="status">${loadError?'准备清单暂不可用，请点击“重新核对清单”重试。':'正在读取当前项目清单，请稍候。'}</p>`;return;}
    const rows=data.actions?.[project]||[];
    const visible=rows.filter(view=>(!stageFilter||view.action.stage===stageFilter)&&(!statusFilter||registrationState(view)===statusFilter));
    list.innerHTML=`<p class="scope-note">${escape(p.name)} · 每个动作独立记录；同一文件用于另一项目或动作时，需要分别保存。</p>${policyReturn(p)}<button type="button" data-project-section="material" data-project-id="${escape(project)}">登记 / 管理已有文件</button><div class="actions"><label>阶段<select id="preparation-stage-filter" name="preparation_stage"><option value="">全部阶段</option>${Object.entries(stages).map(([key,label])=>`<option value="${key}"${stageFilter===key?' selected':''}>${label}</option>`).join('')}</select></label><label>登记状态<select id="preparation-status-filter" name="preparation_status">${Object.entries({'':'全部登记状态',pending:'待处理',prepared:'已准备',submitted:'已登记提交'}).map(([key,label])=>`<option value="${key}"${statusFilter===key?' selected':''}>${label}</option>`).join('')}</select></label></div><p role="status">显示${visible.length}/${rows.length}项已整理事项，条件事项须核对适用</p>${!rows.length?'<p class="empty">当前目标尚无已整理的分阶段动作。请核对完整官方政策；没有清单不表示没有材料要求。</p>':!visible.length?'<p class="empty">当前筛选下没有已整理事项。<button type="button" data-preparation-clear>清除筛选，查看全部已整理事项</button>；请继续核对完整官方政策与适用条件。</p>':''}`+Object.entries(stages).map(([stage,label])=>{const items=visible.filter(v=>v.action.stage===stage);return items.length?`<section><h3>${label}</h3>${items.map((view)=>{
      const a=view.action,key=rows.indexOf(view),detailKey=project+'|'+view.policy_id+'|'+view.action_id,latest=data.records?.[view.latest_record_id],records=Object.values(data.records||{}).filter(r=>r.project_id===project&&r.policy_id===view.policy_id&&r.action_id===view.action_id).sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||'')));
      const conditions=view.conditions||[],personalOnly=['stale','review'].includes(view.quality?.state),blocked=!!loadError||view.can_record===false||!!view.program_pending||!['checked','stale','review'].includes(view.quality?.state);
      const policy=(root.ADMISSIONS_DATA?.policies||[]).find(p=>p.id===view.policy_id);
      const sourceDates=Object.keys(policy?.review_hashes||{}).map(id=>root.ADMISSIONS_DATA.checks?.[id]?.last_success||'未知');
      const files=Object.values(workflow.materials).filter(m=>(m.project_ids||[]).includes(project));
      return `<article class="preparation-action"><h4>${escape(a.label)}</h4><p>${escape(view.policy_title)}</p><p class="muted">摘要核对：${escape(policy?.reviewed_at||'未知')} · 来源成功检查：${[...new Set(sourceDates)].map(escape).join('、')||'未知'}</p><p>${latest?`最近人工登记：${escape(statuses[latest.status]||latest.status)}${latest.review_required?' · 需复核，请展开历史记录':''}`:'尚未保存本动作的准备记录'}</p><p class="quality ${escape(view.quality?.state)}">${escape(view.quality?.label||'来源状态未知，需核对')}${(view.applicability_reasons||[]).length?' · '+view.applicability_reasons.map(r=>escape(applicabilityLabels[r]||r)).join('；'):view.program_pending?' · 专业 / 项目未明确，不能确认适用':''}</p>${conditions.length?`<p class="scope-note">有 ${conditions.length} 项适用条件，须展开逐项核对并明确确认；未确认前仅供参考。</p>`:''}<details data-prepare-detail="${escape(detailKey)}"${openActions.has(detailKey)?' open':''}><summary>查看要求并登记准备</summary>${evidence(a.instruction)}${references((root.ADMISSIONS_DATA?.policies||[]).find(p=>p.id===view.policy_id)||{source_id:''},a.instruction,root.ADMISSIONS_DATA||{sources:{}})}${conditions.map(c=>`<p class="scope-note">适用条件：${escape(conditionText(c))}${c.evidence?.quote?'<br>原文：'+escape(c.evidence.quote)+' · '+escape(c.evidence.locator):''}${c.evidence?' · '+references((root.ADMISSIONS_DATA?.policies||[]).find(p=>p.id===view.policy_id)||{source_id:''},c.evidence,root.ADMISSIONS_DATA||{sources:{}}):''}</p>`).join('')}
      ${personalOnly&&!blocked?'<p class="scope-note">可继续登记个人准备进度；政策依据待复核，本次保存不会确认官方要求仍有效。记录仍列入“待处理”，直到来源与摘要重新核对。</p>':''}<form data-material-action="${key}"><fieldset ${blocked?'disabled':''}><label>本次人工登记状态<select name="status">${Object.entries(statuses).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label><fieldset class="preparation-files"><legend>选择本项目已登记文件（可多选）</legend>${files.map(m=>`<label class="check"><input type="checkbox" name="material_ids" value="${escape(m.id)}">${escape(m.title)}${m.missing?' · 文件缺失':''}<small class="path">${escape(m.path)}</small></label>`).join('')||'<p>暂无关联文件。可先登记已有文件并关联本项目。</p>'}</fieldset>${conditions.length?'<label class="check"><input type="checkbox" name="confirmed_conditions" required>我已逐项核对上述条件，确认适用于本次申请</label>':''}<label>准备 / 提交备注<textarea name="notes" maxlength="10000" placeholder="例如：已合并PDF，待在系统上传；不要在这里粘贴材料正文"></textarea></label><p class="muted">“已提交”仅为人工记录，不表示院方收到或审核通过。保存会新增历史快照，不上传文件。</p><button class="primary" type="submit">保存本次准备记录</button></fieldset></form>
      <details data-material-history data-prepare-detail="${escape('history|'+detailKey)}"${openActions.has('history|'+detailKey)?' open':''}><summary>查看历史记录（${records.length}）与文件版本</summary>${records.map(r=>recordHtml(r)+((view.events||[]).length?`<div class="actions">${view.events.map(e=>`<button type="button" data-material-reminder="${escape(r.id)}" data-action-index="${key}" data-event-index="${e.event_index}" ${blocked||view.quality?.state!=='checked'||!r.applicable||r.id!==view.latest_record_id?'disabled':''}>${view.quality?.state!=='checked'?'来源待复核，暂不可设为提醒：':r.review_required?'设为提醒（文件仍需复核）：':'设为提醒：'}${escape(e.event.label)} · ${escape(e.event.at)}</button>`).join('')}</div>`:'')).join('')||'<p>尚无人工保存记录。</p>'}</details>${(view.events||[]).map(e=>`<p>关联事项：${escape(e.event.label)} · ${escape(e.event.at)}<br><small>原文：${escape(e.event.quote)} · ${escape(e.event.locator)}${e.source_url?` · <a href="${escape(e.source_url)}" target="_blank" rel="noopener">官方出处</a>`:''}；提醒按北京时间日期，未注明时刻不补造。</small></p>`).join('')}</details></article>`;
    }).join('')}</section>`:'';}).join('');
    const historical=Object.values(data.records||{}).filter(r=>r.project_id===project&&!rows.some(v=>v.policy_id===r.policy_id&&v.action_id===r.action_id));
    if(historical.length)list.insertAdjacentHTML('beforeend',`<section><h3>当前清单之外的历史记录</h3><p>原目标或政策动作可能已变化，历史记录不作为当前进度。</p>${historical.map(recordHtml).join('')}</section>`);
  }
  function init(options){
    hook=options;
    node('preparation-reload').onclick=()=>{if(discard())refresh(workflow,project);};
    node('preparation-list').addEventListener('toggle',e=>{const key=e.target.dataset.prepareDetail;if(key){if(e.target.open)openActions.add(key);else openActions.delete(key);}},true);
    node('preparation-list').addEventListener('input',e=>{const form=e.target.closest('[data-material-action]');if(form){dirtyForms.add(form.dataset.materialAction);dirty=true;revision++;}});
    node('preparation-list').addEventListener('change',e=>{
      const stage=e.target.id==='preparation-stage-filter',status=e.target.id==='preparation-status-filter';if(!stage&&!status)return;
      const value=e.target.value;e.target.value=stage?stageFilter:statusFilter;
      if(!discard())return;
      if(stage)stageFilter=value;else statusFilter=value;
      render();
    });
    node('preparation-list').addEventListener('submit',async e=>{
      const form=e.target.closest('[data-material-action]');if(!form)return;e.preventDefault();
      const view=data.actions?.[project]?.[Number(form.dataset.materialAction)];if(!view){feedback('动作已变化，请重新载入后核对。',true);return;}
      const body={project_id:project,expected_goal:view.goal_snapshot,policy_id:view.policy_id,action_id:view.action_id,expected_action:view.action_fingerprint,status:form.elements.status.value,material_ids:[...form.querySelectorAll('[name="material_ids"]:checked')].map(n=>n.value),notes:form.elements.notes.value,confirmed_conditions:!!form.elements.confirmed_conditions?.checked};
      const button=form.querySelector('[type="submit"]');button.disabled=true;
      const savedRevision=revision;
      try{const saved=await request('',body);if(savedRevision===revision){dirtyForms.delete(form.dataset.materialAction);dirty=dirtyForms.size>0;revision++;}feedback(saved.review_required?'个人准备记录已保存；政策或文件仍需复核，不代表已满足当前官方要求。':'本次准备记录已保存；已提交仅为人工登记。');await hook.reload();}
      catch(error){feedback(error.status===409?'目标或来源已变化，未保存。输入已保留，请核对当前原文后重新填写并保存。':error.message,true);}
      finally{if(button.isConnected)button.disabled=false;}
    });
    node('preparation-list').addEventListener('click',async e=>{
      if(e.target.closest('[data-preparation-clear]')){if(discard()){stageFilter='';statusFilter='';render();}return;}
      const b=e.target.closest('[data-material-reminder]');if(!b)return;
      const view=data.actions?.[project]?.[Number(b.dataset.actionIndex)];if(!view)return;
      b.disabled=true;
      try{await request('/'+encodeURIComponent(b.dataset.materialReminder)+'/reminders',{expected_goal:view.goal_snapshot,expected_action:view.action_fingerprint,event_index:Number(b.dataset.eventIndex)});feedback('已按该事项的北京时间日期登记项目提醒，精确原文保留在备注中。');await hook.reload();}catch(error){feedback(error.message,true);b.disabled=false;}
    });
    root.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  }
  root.MaterialPreparation={publicActions,init,refresh,discard,isDirty:()=>dirty};
})(window);

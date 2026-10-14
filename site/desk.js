/* 目标导师上下文贯穿草稿、回复与任务。私人数据不写入静态页或浏览器存储。 */
const el=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const people=new Map((window.MENTOR_DATA||[]).map(p=>[p.page,p]));
const stages={research:'待调研',preparing:'准备联系',waiting:'等待回复',replied:'已回复',materials:'需要补充材料',meeting:'约谈中',closed:'已结束'};
const priorities={high:'优先',normal:'一般',low:'暂缓'};
const eventLabels={draft:'历史草稿',sent:'已发送',replied:'收到回复',note:'备注 / 阶段变更'};
const params=new URLSearchParams(location.search);
const incomingMentor=people.has(params.get('mentor')) ? params.get('mentor') : '';
let FLOW={projects:{},materials:{},communications:{},reminders:{},targets:{},drafts:{}};
let currentTarget=params.get('target')||'', currentDraft='', chosenMentor=incomingMentor, dirty=false, replyDirty=false, loadedTarget='';
let currentView=['today','targets','prepare'].includes(params.get('view')) ? params.get('view') : incomingMentor ? 'prepare' : 'today';
window.CONTACT_READY=false;
const today=()=>new Date().toLocaleDateString('sv-SE');
const personName=id=>people.get(id)?.name||id;
const personLabel=id=>{const p=people.get(id);return p ? `${p.name} · ${p.school_name||p.school} · ${p.dept_name||p.dept}` : id;};
const projectLabel=id=>{const p=FLOW.projects[id];return p ? `${p.name} · ${p.year??'年度未知'}` : '';};
const target=()=>FLOW.targets[currentTarget];
function message(text,error=false){el('desk-message').textContent=text;el('desk-message').classList.toggle('error',error);}
async function api(path='',body,method='GET'){
  const response=await fetch('/api/workflow'+path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const result=await response.json();if(!response.ok)throw new Error(result.error||`请求失败 ${response.status}`);return result;
}
function showView(view){
  currentView=view;
  for(const name of ['today','targets','prepare']) el('view-'+name).hidden=name!==view;
  document.querySelectorAll('.tabs [data-view]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view===view)));
  const query=new URLSearchParams();query.set('view',view);if(incomingMentor)query.set('mentor',incomingMentor);if(currentTarget)query.set('target',currentTarget);
  history.replaceState(null,'',location.pathname+'?'+query);
}
function optionList(id,items,emptyLabel){
  const old=el(id).value;el(id).innerHTML=(emptyLabel===undefined?'':`<option value="">${esc(emptyLabel)}</option>`)+items.map(([key,name])=>`<option value="${esc(key)}">${esc(name)}</option>`).join('');
  if([...el(id).options].some(o=>o.value===old))el(id).value=old;
}
function manageUrl(){
  const mentor=target()?.mentor_id||incomingMentor;
  const q=new URLSearchParams({return:'desk'});if(mentor)q.set('mentor',mentor);if(currentTarget)q.set('target',currentTarget);
  return 'applications.html?'+q;
}
function targetCard(t,attribute){
  const latest=Object.values(FLOW.communications).filter(e=>e.target_id===t.id&&e.kind==='sent').sort((a,b)=>b.date.localeCompare(a.date))[0];
  const next=Object.values(FLOW.reminders).filter(r=>!r.completed&&r.project_id===t.project_id&&r.mentor_id===t.mentor_id).sort((a,b)=>a.due_date.localeCompare(b.due_date))[0];
  return `<article><h3>${esc(personLabel(t.mentor_id))}</h3><small>${esc(projectLabel(t.project_id))}</small><p><span class="badge">${esc(stages[t.stage])}</span><span class="badge">${esc(priorities[t.priority])}</span></p>${t.reason?`<p>${esc(t.reason)}</p>`:''}${latest?`<small>最近发送：${esc(latest.date)}</small>`:''}${next?`<p>下一步：${esc(next.title)} · ${esc(next.due_date)}</p>`:''}<div class="article-actions"><button ${attribute}="${t.id}">继续推进 →</button><a href="p/${encodeURIComponent(t.mentor_id)}.html">查看导师</a></div></article>`;
}
function render(){
  el('welcome').hidden=Object.keys(FLOW.projects).length>0;
  for(const id of ['manage-link','welcome-manage','target-manage','draft-manage'])el(id).href=manageUrl();
  const projectItems=Object.values(FLOW.projects).map(p=>[p.id,projectLabel(p.id)]);
  optionList('target-project',projectItems,'选择申请项目');optionList('targets-project',projectItems,'全部项目');
  const stageItems=Object.entries(stages);optionList('targets-stage',stageItems,'全部阶段');
  optionList('context-stage-edit',stageItems);optionList('reply-stage',stageItems);
  if(!el('reply-stage').dataset.initialized){el('reply-stage').value='replied';el('reply-stage').dataset.initialized='true';}
  const pending=Object.values(FLOW.reminders).filter(r=>!r.completed).sort((a,b)=>a.due_date.localeCompare(b.due_date));
  const waiting=Object.values(FLOW.targets).filter(t=>t.stage==='waiting');
  const preparing=Object.values(FLOW.targets).filter(t=>['research','preparing'].includes(t.stage));
  el('stat-due').textContent=pending.filter(r=>r.due_date<=today()).length;
  el('stat-waiting').textContent=waiting.length;el('stat-preparing').textContent=preparing.length;
  el('task-list').innerHTML=pending.map(r=>{
    const t=Object.values(FLOW.targets).find(t=>t.project_id===r.project_id&&t.mentor_id===r.mentor_id);
    return `<article><h3>${esc(r.title)}</h3><span class="${r.due_date<=today()?'overdue':'muted'}">${r.due_date<=today()?'已到期':'计划日期'} · ${esc(r.due_date)}</span><p>${esc(projectLabel(r.project_id))} ${esc(r.mentor_id?personName(r.mentor_id):'')}</p><p>${esc(r.notes)}</p><div class="article-actions"><button data-complete-task="${r.id}">完成</button>${t?`<button data-continue-target="${t.id}">继续该导师</button>`:`<a href="${esc(manageUrl())}">管理任务</a>`}</div></article>`;
  }).join('')||'<div class="empty">暂无待办。记录回复时，可以同时安排下一步。</div>';
  el('waiting-list').innerHTML=waiting.map(t=>targetCard(t,'data-continue-target')).join('')||'<div class="empty">暂无等待回复的目标。</div>';
  el('preparing-list').innerHTML=preparing.map(t=>targetCard(t,'data-continue-target')).join('')||'<div class="empty">暂无待准备的目标。</div>';
  const q=el('targets-query').value.toLowerCase().trim(),project=el('targets-project').value,stage=el('targets-stage').value;
  el('target-list').innerHTML=Object.values(FLOW.targets).filter(t=>(!project||t.project_id===project)&&(!stage||t.stage===stage)&&(!q||`${personLabel(t.mentor_id)} ${t.reason}`.toLowerCase().includes(q))).sort((a,b)=>['high','normal','low'].indexOf(a.priority)-['high','normal','low'].indexOf(b.priority)).map(t=>targetCard(t,'data-target')).join('')||'<div class="empty">暂无符合条件的目标。选择项目和导师即可加入。</div>';
  renderContext();showView(currentView);
}
function renderContext(){
  const t=target();el('prepare-empty').hidden=!!t;el('prepare-detail').hidden=!t;if(!t)return;
  const p=people.get(t.mentor_id);
  el('context-name').textContent=personName(t.mentor_id);el('context-project').textContent=projectLabel(t.project_id);
  el('context-stage').textContent=stages[t.stage];el('context-priority').textContent=priorities[t.priority];el('context-reason').textContent=t.reason||'尚未记录选择理由';
  el('context-profile').href='p/'+encodeURIComponent(t.mentor_id)+'.html';el('context-research').textContent=p?.research_direction_raw ? '官网方向：'+p.research_direction_raw : '官网未提供明确研究方向，请进一步核实。';
  const next=Object.values(FLOW.reminders).filter(r=>!r.completed&&r.mentor_id===t.mentor_id&&r.project_id===t.project_id).sort((a,b)=>a.due_date.localeCompare(b.due_date))[0];
  el('context-next').textContent=next ? '下一步：'+next.title+' · '+next.due_date : '尚未安排下一步';
  el('context-stage-edit').value=t.stage;
  const drafts=Object.values(FLOW.drafts).filter(d=>d.target_id===t.id).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
  optionList('draft-choice',drafts.map(d=>[d.id,(d.subject||'未填写主题')+' · '+d.updated_at.slice(0,10)]),'新草稿');el('draft-choice').value=currentDraft;
  const events=Object.values(FLOW.communications).filter(e=>e.target_id===t.id).sort((a,b)=>b.date.localeCompare(a.date)||b.created_at.localeCompare(a.created_at));
  el('contact-history').innerHTML=events.map(e=>`<article><span class="event-time">${esc(e.date)}</span> <span class="badge">${esc(eventLabels[e.kind])}</span><h3>${esc(e.subject)}</h3><p class="history-body">${esc(e.content)}</p>${e.recipient?`<small>收件人：${esc(e.recipient)}</small>`:''}${e.attachments.length?`<p><small>发送时附件：${e.attachments.map(a=>`${esc(a.title)} · ${a.size} 字节 · SHA256 ${esc(a.sha256)}`).join('<br>')}</small></p>`:''}</article>`).join('')||'<div class="empty">暂无联系记录。保存草稿和导出不会算作发送。</div>';
  updateDraftState();
}
function loadDraft(id=''){
  currentDraft=id;dirty=false;const d=FLOW.drafts[id],t=target();if(!t)return;
  const p=people.get(t.mentor_id);const fields={recipient:d?.recipient||((p?.email&&!/[;,，；\s]/.test(p.email))?p.email:''),subject:d?.subject||'',body:d?.body||'',basis:d?.basis||''};
  for(const [key,value]of Object.entries(fields))el('draft-'+key).value=value;
  const eligible=Object.values(FLOW.materials).filter(m=>m.mentor_ids.includes(t.mentor_id)||m.project_ids.includes(t.project_id)||(!m.mentor_ids.length&&!m.project_ids.length)||(d?.material_ids||[]).includes(m.id));
  el('draft-materials').innerHTML=eligible.map(m=>`<label class="check"><input type="checkbox" value="${m.id}" data-missing="${m.missing}" ${(d?.material_ids||[]).includes(m.id)?'checked':''} ${m.missing&&!(d?.material_ids||[]).includes(m.id)?'disabled':''}>${esc(m.title)}${m.missing?'（文件缺失，可取消已选附件）':''}</label>`).join('')||`<small>暂无适用材料，可从“整理材料”登记或关联文件。</small>`;
  el('attachment-state').textContent=d?.attachments.length ? d.attachments.map(a=>`${a.title} · ${a.size} 字节 · ${a.sha256.slice(0,12)}…`).join('；') : '保存草稿时固定本次附件版本；文件变更后需重新选择保存。';
  el('sent-confirmed').checked=false;el('sent-date').value=today();el('draft-choice').value=id;updateDraftState();
}
function updateDraftState(){
  const sent=Object.values(FLOW.communications).find(e=>e.draft_id&&e.draft_id===currentDraft);
  el('draft-fields').disabled=!!sent;
  el('draft-export').disabled=!currentDraft||dirty||!!sent;
  el('sent-confirmed').disabled=!currentDraft||dirty||!!sent;
  el('draft-confirm').disabled=!currentDraft||dirty||!!sent||!el('sent-confirmed').checked;
  el('sent-date').disabled=!!sent;
  el('sent-state').textContent=sent ? `已确认发送于 ${sent.date}。此版本已锁定，需要再次联系时请新建草稿。` : dirty ? '草稿有未保存的修改，请先保存。' : '草稿和导出不会计为已发送。';
}
async function refresh(){
  FLOW=await api();
  if(!FLOW.targets[currentTarget]){
    const matches=Object.values(FLOW.targets).filter(t=>!incomingMentor||t.mentor_id===incomingMentor);
    currentTarget=(incomingMentor&&matches.length!==1)?'':matches[0]?.id||'';
    if(incomingMentor&&matches.length>1){currentView='targets';el('targets-query').value=personName(incomingMentor);}
  }
  if(loadedTarget!==currentTarget){loadedTarget=currentTarget;currentDraft='';resetReply();const drafts=Object.values(FLOW.drafts).filter(d=>d.target_id===currentTarget).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));loadDraft(drafts[0]?.id||'');}
  render();el('desk-hint').hidden=true;window.CONTACT_READY=true;el('desk-backup').disabled=false;
}
async function action(task,success){
  el('desk-workspace').disabled=true;el('desk-restore').disabled=true;el('desk-backup').disabled=true;
  try{await task();await refresh();message(success);}
  catch(e){message(e.message,true);}
  finally{el('desk-workspace').disabled=!window.CONTACT_READY;el('desk-restore').disabled=false;el('desk-backup').disabled=!window.CONTACT_READY;}
}
function chooseTarget(id){
  if(id===currentTarget){showView('prepare');return;}
  if(!allowSwitch())return;
  resetReply();
  currentTarget=id;loadedTarget=id;const drafts=Object.values(FLOW.drafts).filter(d=>d.target_id===id).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));loadDraft(drafts[0]?.id||'');currentView='prepare';render();el('view-prepare').scrollIntoView({block:'start'});
}
function allowSwitch(){return !(dirty||replyDirty)||confirm('草稿或回复/下一步尚未保存，切换会放弃修改。继续？');}
function resetReply(){el('reply-form').reset();el('reply-date').value=today();el('reply-stage').value='replied';replyDirty=false;}
function renderMentorSearch(){
  const q=el('target-query').value.toLowerCase().trim();el('target-choice').textContent=chosenMentor ? '已选择：'+personLabel(chosenMentor) : '请选择搜索结果中的导师';
  el('target-results').innerHTML=(q?[...people.values()].filter(p=>`${p.page} ${personLabel(p.page)}`.toLowerCase().includes(q)).slice(0,15):[]).map(p=>`<button type="button" data-choose-mentor="${esc(p.page)}">${esc(personLabel(p.page))}<br><small>${esc(p.page)}</small></button>`).join('');
}
document.querySelector('main').onclick=e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.view)showView(b.dataset.view);
  const id=b.dataset.target||b.dataset.continueTarget;if(id)chooseTarget(id);
  if(b.dataset.chooseMentor){chosenMentor=b.dataset.chooseMentor;el('target-query').value='';renderMentorSearch();}
  if(b.dataset.completeTask)action(()=>api('/reminders/'+b.dataset.completeTask,{completed:true},'PATCH'),'待办已完成');
};
el('target-query').oninput=()=>{chosenMentor='';renderMentorSearch();};
el('target-form').onsubmit=e=>{
  e.preventDefault();if(!allowSwitch())return;action(async()=>{
    const t=await api('/targets',{project_id:el('target-project').value,mentor_id:chosenMentor,priority:el('target-priority').value,reason:el('target-reason').value},'POST');
    currentTarget=t.id;currentView='prepare';loadedTarget='';
  },'已加入目标，可以准备联系');
};
el('targets-project').onchange=render;el('targets-stage').onchange=render;el('targets-query').oninput=render;
el('draft-fields').addEventListener('input',e=>{
  if(e.target.dataset.missing==='true'&&!e.target.checked)e.target.disabled=true;
  dirty=true;updateDraftState();
});
el('sent-confirmed').onchange=updateDraftState;
el('draft-choice').onchange=e=>{
  if(dirty&&!confirm('尚未保存，切换会放弃修改。继续？')){e.target.value=currentDraft;return;}
  loadDraft(e.target.value);
};
el('draft-new').onclick=()=>{if(dirty&&!confirm('尚未保存，清空后重新写草稿？'))return;loadDraft();};
el('draft-form').onsubmit=e=>{
  e.preventDefault();action(async()=>{
    if(!target())throw new Error('请先选择目标导师');
    const body={recipient:el('draft-recipient').value.trim(),subject:el('draft-subject').value,body:el('draft-body').value,basis:el('draft-basis').value,
      material_ids:[...el('draft-materials').querySelectorAll('input:checked')].map(i=>i.value),...(currentDraft?{}:{target_id:currentTarget})};
    const draft=await api('/drafts'+(currentDraft?'/'+currentDraft:''),body,currentDraft?'PATCH':'POST');
    FLOW.drafts[draft.id]=draft;loadDraft(draft.id);
  },'草稿已保存；尚未记为发送');
};
el('draft-export').onclick=()=>action(async()=>{
  const r=await fetch('/api/workflow/drafts/'+currentDraft+'/eml');if(!r.ok)throw new Error((await r.json()).error);
  const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='mentor-draft.eml';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
},'已导出邮件与附件，请在邮件客户端核对并发送；尚未记为发送');
el('draft-confirm').onclick=()=>action(()=>api('/drafts/'+currentDraft+'/confirm',{sent:el('sent-confirmed').checked,date:el('sent-date').value},'POST'),'已记录实际发送，当前目标进入等待回复');
el('stage-save').onclick=()=>action(()=>api('/targets/'+currentTarget,{stage:el('context-stage-edit').value},'PATCH'),'联系阶段已更新并留痕');
el('reply-form').onsubmit=e=>{
  e.preventDefault();action(async()=>{
    const task=el('reply-task').value.trim(),due=el('reply-due').value;
    if(!task&&due)throw new Error('填写计划日期时也请填写下一步内容');
    await api('/targets/'+currentTarget+'/reply',{content:el('reply-content').value,date:el('reply-date').value,stage:el('reply-stage').value,
      ...(task?{task:{title:task,due_date:due}}:{})},'POST');
    resetReply();
  },'回复已记录，下一步已同步到待办');
};
el('reply-form').addEventListener('input',()=>{replyDirty=true;});
window.addEventListener('beforeunload',e=>{if(dirty||replyDirty){e.preventDefault();e.returnValue='';}});
el('desk-backup').onclick=()=>action(async()=>{
  const result=await api('/backup'),url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='contact-workflow-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
},'备份已导出（不包含附件原文件）');
el('desk-restore').onclick=()=>el('desk-restore-file').click();
el('desk-restore-file').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  if(!confirm('恢复会替换私人工作流，服务将先保留原索引副本。继续？')){e.target.value='';return;}
  await action(async()=>{await api('/restore',JSON.parse(await file.text()),'POST');loadedTarget='';dirty=false;},'已恢复备份');e.target.value='';
};
el('reply-date').value=today();el('sent-date').value=today();renderMentorSearch();showView(currentView);
if(location.protocol==='http:'){
  el('desk-restore').disabled=false;
  refresh().then(()=>{el('desk-workspace').disabled=false;})
    .catch(e=>message('无法读取私人工作流：'+e.message,true));
}

/* 目标导师上下文贯穿草稿、回复与任务。私人数据不写入静态页或浏览器存储。 */
const el=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const people=new Map((window.MENTOR_DATA||[]).map(p=>[p.page,p]));
const stages={research:'待调研',preparing:'准备联系',waiting:'等待回复',replied:'已回复',materials:'需要补充材料',meeting:'约谈中',closed:'已结束'};
const priorities={high:'优先',normal:'一般',low:'暂缓'};
const eventLabels={draft:'历史草稿',sent:'已发送',replied:'收到回复',note:'备注 / 阶段变更'};
const params=new URLSearchParams(location.search);
const discoveryReturn=(()=>{const value=params.get('discovery_return')||'';try{if(!/^discovery\.html(?:\?[^#]*)?$/.test(value)||/[\\\u0000-\u0020\u007f]/.test(value)||/[\\\u0000-\u001f\u007f]/.test(decodeURIComponent(value)))return '';const url=new URL(value,location.href);return url.origin===location.origin&&url.pathname.endsWith('/discovery.html')?value:'';}catch(e){return '';}})();
function mentorProfileUrl(id){const q=new URLSearchParams();if(discoveryReturn)q.set('discovery_return',discoveryReturn);return 'p/'+encodeURIComponent(id)+'.html'+(q.size?'?'+q:'');}
let projectContext=params.get('project')||'',projectContextReady=false;
const incomingMentor=people.has(params.get('mentor')) ? params.get('mentor') : '';
const intentYear=Number(params.get('year'));
const incomingGoal={...(Number.isInteger(intentYear)&&intentYear>=2000&&intentYear<=2100?{year:intentYear}:{}),
  ...(['master','phd'].includes(params.get('degree'))?{degree:params.get('degree')}:{}),
  ...(['recommend','exam','assessment'].includes(params.get('route'))?{route:params.get('route')}: {})};
for(const key of ['school','dept','track','program'])if(params.get(key))incomingGoal[key]=params.get(key);
const goalDegree={master:'硕士',phd:'博士'},goalRoute={recommend:'推免',exam:'统考',assessment:'申请考核'};
let FLOW={projects:{},materials:{},communications:{},reminders:{},targets:{},drafts:{}};
let currentTarget=params.get('target')||'', currentDraft='', chosenMentor=incomingMentor, dirty=false, replyDirty=false, loadedTarget='';
let currentView=['today','targets','prepare'].includes(params.get('view')) ? params.get('view') : incomingMentor ? 'prepare' : 'today';
let currentPanel=['mail','tasks','reply','history'].includes(params.get('panel'))?params.get('panel'):'mail';
let taskDirty=false,editingTask='',statusArea='',actionBusy=false;
window.CONTACT_READY=false;
const today=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
const personName=id=>people.get(id)?.name||id;
const personLabel=id=>{const p=people.get(id);return p ? `${p.name} · ${p.school_name||p.school} · ${p.dept_name||p.dept}` : id;};
const projectLabel=id=>{const p=FLOW.projects[id];return p ? `${p.name} · ${p.year??'年度未知'}` : '';};
const target=()=>FLOW.targets[currentTarget];
function savedGoal(){const p=FLOW.projects[target()?.project_id||projectContext];return p?.school_id&&p.dept_id&&p.year&&p.degree&&p.route&&p.track?{school:p.school_id,dept:p.dept_id,year:p.year,degree:p.degree,route:p.route,track:p.track,...(p.program_name?{program:(p.program_code||'')+'|'+p.program_name}:{})}:null;}
function forwardedGoal(){
  if(savedGoal())return savedGoal();
  const goal={...incomingGoal},p=people.get(target()?.mentor_id||incomingMentor);
  if(p){
    if(target()||goal.school!==p.school||goal.dept!==p.dept){delete goal.track;delete goal.program;}
    goal.school=p.school;goal.dept=p.dept;
  }
  return goal;
}
function renderGoal(){
  const saved=savedGoal();
  if(saved){
    const p=people.get(target()?.mentor_id||incomingMentor),mismatch=p&&(p.school!==saved.school||p.dept!==saved.dept);
    el('incoming-goal').hidden=false;
    el('incoming-goal').textContent='已保存项目目标：'+[saved.school,saved.dept,saved.year,goalDegree[saved.degree],goalRoute[saved.route],saved.track==='special'?'专项 / 特定项目':'普通招生',saved.program?.replace('|',' · ')].filter(Boolean).join(' · ')+'。'+(mismatch?'当前导师与项目目标单位不同，项目政策不能据此认定适用于该导师；请核实跨院系招生关系。':'项目目标用于带范围核对政策，不表示个人符合资格或导师有名额。');
    return;
  }
  const scoped=!!(incomingGoal.track||incomingGoal.program),goal=forwardedGoal();
  const intent=[incomingGoal.year,goalDegree[incomingGoal.degree],goalRoute[incomingGoal.route]].filter(Boolean).join(' · ');
  el('incoming-goal').hidden=!Object.keys(incomingGoal).length;
  el('incoming-goal').textContent=(intent?'来访申请意向：'+intent+'。':'')+
    '来访招生范围仅供核对，尚未绑定该申请项目；不表示招生已确认，也不代表项目字段。'+
    (scoped?(target()?'已按你选择的目标继续；链接已移除未绑定的类别 / 专业。':!goal.track&&!goal.program?
      ((!incomingGoal.school||!incomingGoal.dept)?'来访单位信息不完整，无法确定适用院系，已移除类别 / 专业。':'来访单位与当前导师不符，已移除类别 / 专业，请重新核对。'):
      '请选择适用申请项目，系统不会按类别 / 专业自动匹配私人项目。'):'');
}
function message(text,error=false){const node=el(statusArea)||el('desk-message');node.textContent=text;node.classList.toggle('error',error);}
async function api(path='',body,method='GET'){
  const response=await fetch('/api/workflow'+path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const result=await response.json();if(!response.ok)throw new Error(result.error||`请求失败 ${response.status}`);return result;
}
function showView(view){
  currentView=view;
  for(const name of ['today','targets','prepare']) el('view-'+name).hidden=name!==view;
  document.querySelectorAll('.tabs [data-view]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view===view)));
  const query=new URLSearchParams();query.set('view',view);query.set('panel',currentPanel);if(target()?.mentor_id||incomingMentor)query.set('mentor',target()?.mentor_id||incomingMentor);if(currentTarget)query.set('target',currentTarget);
  if(FLOW.projects[target()?.project_id||projectContext])query.set('project',target()?.project_id||projectContext);
  for(const [key,value] of Object.entries(forwardedGoal()))query.set(key,value);
  if(discoveryReturn)query.set('discovery_return',discoveryReturn);
  if(discoveryReturn)for(const link of document.querySelectorAll('a[href]'))if(link.getAttribute('href').split('?')[0]==='discovery.html')link.href=discoveryReturn;
  history.replaceState(null,'',location.pathname+'?'+query);
}
function optionList(id,items,emptyLabel){
  const old=el(id).value;el(id).innerHTML=(emptyLabel===undefined?'':`<option value="">${esc(emptyLabel)}</option>`)+items.map(([key,name])=>`<option value="${esc(key)}">${esc(name)}</option>`).join('');
  if([...el(id).options].some(o=>o.value===old))el(id).value=old;
}
function manageUrl(){
  const mentor=target()?.mentor_id||incomingMentor;
  const q=new URLSearchParams({return:'desk',panel:currentPanel});if(mentor)q.set('mentor',mentor);if(currentTarget)q.set('target',currentTarget);
  if(FLOW.projects[target()?.project_id||projectContext])q.set('project',target()?.project_id||projectContext);
  for(const [key,value] of Object.entries(forwardedGoal()))q.set(key,value);
  if(discoveryReturn)q.set('discovery_return',discoveryReturn);
  return 'applications.html?'+q;
}
function reminderManageUrl(reminder){
  const q=new URLSearchParams({return:'desk',section:'reminder'});
  if(discoveryReturn)q.set('discovery_return',discoveryReturn);
  if(FLOW.projects[reminder.project_id])q.set('project',reminder.project_id);
  if(people.has(reminder.mentor_id))q.set('mentor',reminder.mentor_id);
  return 'applications.html?'+q;
}
function targetCard(t,attribute){
  const latest=Object.values(FLOW.communications).filter(e=>e.target_id===t.id&&e.kind==='sent').sort((a,b)=>b.date.localeCompare(a.date))[0];
  const next=Object.values(FLOW.reminders).filter(r=>!r.completed&&r.project_id===t.project_id&&r.mentor_id===t.mentor_id).sort((a,b)=>a.due_date.localeCompare(b.due_date))[0];
  return `<article><h3>${esc(personLabel(t.mentor_id))}</h3><small>${esc(projectLabel(t.project_id))}</small><p><span class="badge">${esc(stages[t.stage])}</span><span class="badge">${esc(priorities[t.priority])}</span></p>${t.reason?`<p>${esc(t.reason)}</p>`:''}${latest?`<small>最近发送：${esc(latest.date)}</small>`:''}${next?`<p>下一步：${esc(next.title)} · ${esc(next.due_date)}</p>`:''}<div class="article-actions"><button ${attribute}="${t.id}">继续推进 →</button><a href="${esc(mentorProfileUrl(t.mentor_id))}">查看导师</a></div></article>`;
}
function render(){
  el('welcome').hidden=Object.keys(FLOW.projects).length>0;
  for(const id of ['manage-link','welcome-manage','target-manage','draft-manage'])el(id).href=manageUrl();
  const projectItems=Object.values(FLOW.projects).map(p=>[p.id,projectLabel(p.id)]);
  optionList('target-project',projectItems,'选择申请项目');optionList('targets-project',projectItems,'全部项目');
  if(!projectContextReady){const id=target()?.project_id||projectContext;if(FLOW.projects[id]){el('target-project').value=id;el('targets-project').value=id;}projectContextReady=true;}
  const stageItems=Object.entries(stages);optionList('targets-stage',stageItems,'全部阶段');
  optionList('context-stage-edit',stageItems);optionList('reply-stage',stageItems);
  if(!el('reply-stage').dataset.initialized){el('reply-stage').value='replied';el('reply-stage').dataset.initialized='true';}
  const overviewProject=el('targets-project').value,withinProject=item=>!overviewProject||item.project_id===overviewProject;
  if(el('overview-scope'))el('overview-scope').textContent=overviewProject?'当前项目：'+projectLabel(overviewProject)+'；下方待办与联系进度按此项目展示。':'当前显示全部项目的待办与联系进度。';
  const pending=Object.values(FLOW.reminders).filter(r=>!r.completed&&withinProject(r)).sort((a,b)=>a.due_date.localeCompare(b.due_date));
  const waiting=Object.values(FLOW.targets).filter(t=>t.stage==='waiting'&&withinProject(t));
  const preparing=Object.values(FLOW.targets).filter(t=>['research','preparing'].includes(t.stage)&&withinProject(t));
  el('stat-due').textContent=pending.filter(r=>r.due_date<=today()).length;
  el('stat-waiting').textContent=waiting.length;el('stat-preparing').textContent=preparing.length;
  const taskCards=pending.map(r=>{
    const t=Object.values(FLOW.targets).find(t=>t.project_id===r.project_id&&t.mentor_id===r.mentor_id);
    return `<article><h3>${esc(r.title)}</h3><span class="${r.due_date<=today()?'overdue':'muted'}">${r.due_date<=today()?'已到期':'计划日期'} · ${esc(r.due_date)}</span><p>${esc(projectLabel(r.project_id))} ${esc(r.mentor_id?personName(r.mentor_id):'')}</p><p>${esc(r.notes)}</p><div class="article-actions"><button data-complete-task="${r.id}">完成</button>${t?`<button data-continue-target="${t.id}">继续该导师</button>`:`<a href="${esc(reminderManageUrl(r))}">管理任务</a>`}</div></article>`;
  });
  el('task-list').innerHTML=taskCards.filter((_,i)=>pending[i].due_date<=today()).join('')||'<div class="empty">今日没有到期事项。可从目标导师安排下一步。</div>';
  el('future-task-list').innerHTML=taskCards.filter((_,i)=>pending[i].due_date>today()).join('')||'<div class="empty">暂无未来计划。</div>';
  el('waiting-list').innerHTML=waiting.map(t=>targetCard(t,'data-continue-target')).join('')||'<div class="empty">暂无等待回复的目标。</div>';
  el('preparing-list').innerHTML=preparing.map(t=>targetCard(t,'data-continue-target')).join('')||'<div class="empty">暂无待准备的目标。</div>';
  const unplanned=Object.values(FLOW.targets).filter(t=>withinProject(t)&&['replied','materials','meeting'].includes(t.stage)&&!pending.some(r=>r.project_id===t.project_id&&r.mentor_id===t.mentor_id));
  el('unplanned-list').innerHTML=unplanned.map(t=>targetCard(t,'data-continue-target')).join('')||'<div class="empty">已回复、需补材料或约谈的导师均已安排下一步，或暂无这类目标。</div>';
  const q=el('targets-query').value.toLowerCase().trim(),project=el('targets-project').value,stage=el('targets-stage').value;
  el('target-list').innerHTML=Object.values(FLOW.targets).filter(t=>(!project||t.project_id===project)&&(!stage||t.stage===stage)&&(!q||`${personLabel(t.mentor_id)} ${t.reason}`.toLowerCase().includes(q))).sort((a,b)=>['high','normal','low'].indexOf(a.priority)-['high','normal','low'].indexOf(b.priority)).map(t=>targetCard(t,'data-target')).join('')||'<div class="empty">暂无符合条件的目标。选择项目和导师即可加入。</div>';
  renderContext();renderIncoming();showPanel(currentPanel);showView(currentView);
  renderGoal();renderMentorSearch();
  el('draft-manage').href=manageUrl()+'&section=material';
}
function renderContext(){
  const t=target();el('prepare-empty').hidden=!!t;el('prepare-detail').hidden=!t;if(!t)return;
  const p=people.get(t.mentor_id);
  el('context-name').textContent=personName(t.mentor_id);el('context-project').textContent=projectLabel(t.project_id);
  el('context-stage').textContent=stages[t.stage];el('context-priority').textContent=priorities[t.priority];el('context-reason').textContent=t.reason||'尚未记录选择理由';
  el('context-profile').href=mentorProfileUrl(t.mentor_id);el('context-research').textContent=p?.research_direction_raw ? '官网方向：'+p.research_direction_raw : '暂未整理明确研究方向，请查看官网核实。';
  const next=Object.values(FLOW.reminders).filter(r=>!r.completed&&r.mentor_id===t.mentor_id&&r.project_id===t.project_id).sort((a,b)=>a.due_date.localeCompare(b.due_date))[0];
  renderTargetTasks();
  el('context-next').textContent=next ? '下一步：'+next.title+' · '+next.due_date : '尚未安排下一步';
  el('context-stage-edit').value=t.stage;
  const drafts=Object.values(FLOW.drafts).filter(d=>d.target_id===t.id).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
  optionList('draft-choice',drafts.map(d=>[d.id,(d.subject||'未填写主题')+' · '+d.updated_at.slice(0,10)]),'新草稿');el('draft-choice').value=currentDraft;
  const events=Object.values(FLOW.communications).filter(e=>e.target_id===t.id).sort((a,b)=>b.date.localeCompare(a.date)||b.created_at.localeCompare(a.created_at));
  el('contact-history').innerHTML=events.map(e=>`<article><span class="event-time">${esc(e.date)}</span> <span class="badge">${esc(eventLabels[e.kind])}</span><h3>${esc(e.subject)}</h3><p class="history-body">${esc(e.content)}</p>${e.recipient?`<small>收件人：${esc(e.recipient)}</small>`:''}${e.attachments.length?`<p><small>发送时附件：${e.attachments.map(a=>`${esc(a.title)} · ${a.size} 字节`).join('<br>')}</small></p>`:''}</article>`).join('')||'<div class="empty">暂无联系记录。保存草稿和导出不会算作发送。</div>';
  updateDraftState();
}
function loadDraft(id=''){
  currentDraft=id;dirty=false;const d=FLOW.drafts[id],t=target();if(!t)return;
  el('draft-status').textContent='';
  const p=people.get(t.mentor_id);const fields={recipient:d?.recipient||((p?.email&&!/[;,，；\s]/.test(p.email))?p.email:''),subject:d?.subject||'',body:d?.body||'',basis:d?.basis||''};
  for(const [key,value]of Object.entries(fields))el('draft-'+key).value=value;
  const eligible=Object.values(FLOW.materials).filter(m=>m.mentor_ids.includes(t.mentor_id)||m.project_ids.includes(t.project_id)||(!m.mentor_ids.length&&!m.project_ids.length)||(d?.material_ids||[]).includes(m.id));
  el('draft-materials').innerHTML=eligible.map(m=>`<label class="check"><input type="checkbox" value="${m.id}" data-missing="${m.missing}" ${(d?.material_ids||[]).includes(m.id)?'checked':''} ${m.missing&&!(d?.material_ids||[]).includes(m.id)?'disabled':''}>${esc(m.title)}${m.missing?'（文件缺失，可取消已选附件）':''}</label>`).join('')||`<small>暂无适用材料，可从“整理材料”上传文件并关联当前项目。</small>`;
  el('attachment-state').textContent=d?.attachments.length ? d.attachments.map(a=>`${a.title} · ${a.size} 字节`).join('；') : '保存草稿时固定本次附件版本；文件变更后需重新选择保存。';
  el('sent-confirmed').checked=false;el('sent-date').value=today();el('draft-choice').value=id;updateDraftState();
}
function updateDraftState(){
  const sent=Object.values(FLOW.communications).find(e=>e.draft_id&&e.draft_id===currentDraft);
  const issues=[];
  const recipient=el('draft-recipient').value.trim(),subject=el('draft-subject').value,body=el('draft-body').value;
  if(!/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/.test(recipient))issues.push('单个有效收件邮箱');
  for(const [key,label]of [['subject','邮件主题'],['body','邮件正文'],['basis','联系依据']])if(!el('draft-'+key).value.trim())issues.push(label);
  if(/[\r\n]/.test(subject))issues.push('主题不可换行');
  if(/【[^】]*】/.test(subject+body))issues.push('替换主题或正文中的占位内容');
  if(target()?.stage==='closed')issues.push('目标已结束，需先更新联系阶段');
  if([...el('draft-materials').querySelectorAll('input:checked')].some(i=>FLOW.materials[i.value]?.missing))issues.push('已选附件文件缺失，请恢复文件或取消选择并保存');
  el('draft-readiness').textContent=sent ? '此版本已记录实际发送并锁定。再次联系请新建草稿。' :
    (issues.length?'还需处理：'+issues.join('；')+'。':'基本填写项已齐全；导出时仍会检查附件文件与版本。')+
    (dirty?' 当前修改或附件选择尚未保存。':!currentDraft?' 请先保存草稿。':'');
  el('draft-fields').disabled=!!sent;
  el('draft-export').disabled=!currentDraft||dirty||!!sent||issues.length>0;
  el('sent-confirmed').disabled=!currentDraft||dirty||!!sent||issues.length>0;
  el('draft-confirm').disabled=!currentDraft||dirty||!!sent||issues.length>0||!el('sent-confirmed').checked;
  el('sent-date').disabled=!!sent;
  el('sent-state').textContent=sent ? `已确认发送于 ${sent.date}。此版本已锁定，需要再次联系时请新建草稿。` : dirty ? '草稿有未保存的修改，请先保存。' : '草稿和导出不会计为已发送。';
}
async function refresh(){
  FLOW=await api();
  if(FLOW.targets[currentTarget])chosenMentor=FLOW.targets[currentTarget].mentor_id;
  if(!FLOW.targets[currentTarget]){
    const matches=Object.values(FLOW.targets).filter(t=>{
      if(projectContext&&!FLOW.projects[projectContext])return false;
      if(FLOW.projects[projectContext]&&t.project_id!==projectContext)return false;
      const p=FLOW.projects[t.project_id];
      if(p.school_id&&p.dept_id){const scope={school:p.school_id,dept:p.dept_id,year:p.year,degree:p.degree,route:p.route,track:p.track,program:p.program_name?(p.program_code||'')+'|'+p.program_name:''};return (!incomingMentor||t.mentor_id===incomingMentor)&&Object.entries(incomingGoal).every(([key,value])=>String(scope[key]||'')===String(value));}
      return (!incomingMentor||t.mentor_id===incomingMentor)&&(!incomingGoal.year||p.year===incomingGoal.year)&&
        (!(incomingGoal.degree||incomingGoal.route)||p.application_type===[goalDegree[incomingGoal.degree],goalRoute[incomingGoal.route]].filter(Boolean).join(' / '));
    });
    const precise=matches.length===1&&FLOW.projects[matches[0].project_id]?.school_id&&FLOW.projects[matches[0].project_id]?.dept_id;
    currentTarget=((incomingGoal.track||incomingGoal.program)&&!precise||(incomingMentor&&matches.length!==1))?'':matches[0]?.id||'';
    if(!incomingMentor&&matches.length>1)currentTarget='';
    if(incomingMentor&&matches.length>1){currentView='targets';el('targets-query').value=personName(incomingMentor);}
  }
  if(loadedTarget!==currentTarget){loadedTarget=currentTarget;currentDraft='';resetReply();resetTask();const drafts=Object.values(FLOW.drafts).filter(d=>d.target_id===currentTarget).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));loadDraft(drafts[0]?.id||'');}
  render();el('desk-hint').hidden=true;window.CONTACT_READY=true;el('desk-backup').disabled=false;
}
async function action(task,success){
  if(actionBusy)return;
  actionBusy=true;
  const button=document.activeElement?.tagName==='BUTTON'?document.activeElement:null,label=button?.textContent;
  if(button)button.textContent='正在保存…';
  el('desk-workspace').disabled=true;el('desk-workspace').setAttribute('aria-busy','true');el('desk-restore').disabled=true;el('desk-backup').disabled=true;
  let saved=false;
  try{await task();saved=true;await refresh();message(success);}
  catch(e){message(saved?'操作已完成，但列表刷新失败，请刷新页面核对，勿重复提交。':e.message,true);}
  finally{actionBusy=false;el('desk-workspace').removeAttribute('aria-busy');el('desk-workspace').disabled=!window.CONTACT_READY;el('desk-restore').disabled=false;el('desk-backup').disabled=!window.CONTACT_READY;if(button?.textContent==='正在保存…')button.textContent=label;}
}
function chooseTarget(id){
  if(id===currentTarget){showView('prepare');return;}
  if(!allowSwitch())return;
  resetReply();resetTask();
  currentTarget=id;loadedTarget=id;const drafts=Object.values(FLOW.drafts).filter(d=>d.target_id===id).sort((a,b)=>b.updated_at.localeCompare(a.updated_at));loadDraft(drafts[0]?.id||'');currentView='prepare';render();el('view-prepare').scrollIntoView({block:'start'});
}
function allowSwitch(){return !(dirty||replyDirty||taskDirty)||confirm('草稿或回复/下一步尚未保存，切换会放弃修改。继续？');}
function resetReply(){el('reply-form').reset();el('reply-date').value=today();el('reply-stage').value='replied';replyDirty=false;}
function renderMentorSearch(){
  const q=el('target-query').value.toLowerCase().trim();el('target-choice').textContent=chosenMentor ? '已选择：'+personLabel(chosenMentor) : '请选择搜索结果中的导师';
  el('target-results').innerHTML=(q?[...people.values()].filter(p=>`${p.page} ${personLabel(p.page)}`.toLowerCase().includes(q)).slice(0,15):[]).map(p=>`<button type="button" data-choose-mentor="${esc(p.page)}">${esc(personLabel(p.page))}<br><small>${esc(p.page)}</small></button>`).join('');
}
document.querySelector('main').onclick=e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.panel&&b.dataset.panel!==currentPanel){if(!allowSwitch())return;discardPrepare();showPanel(b.dataset.panel);showView(currentView);return;}
  if(b.dataset.view&&b.dataset.view!==currentView){if(!allowSwitch())return;discardPrepare();showView(b.dataset.view);}
  const id=b.dataset.target||b.dataset.continueTarget;if(id)chooseTarget(id);
  if(b.dataset.chooseMentor){chosenMentor=b.dataset.chooseMentor;el('target-query').value='';renderMentorSearch();}
  if(b.dataset.completeTask)action(()=>api('/reminders/'+b.dataset.completeTask,{completed:true},'PATCH'),'待办已完成');
};
el('target-query').oninput=()=>{chosenMentor='';renderMentorSearch();};
el('target-form').onsubmit=e=>{
  statusArea='';
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
  statusArea='draft-status';
  e.preventDefault();action(async()=>{
    if(!target())throw new Error('请先选择目标导师');
    const body={recipient:el('draft-recipient').value.trim(),subject:el('draft-subject').value,body:el('draft-body').value,basis:el('draft-basis').value,
      material_ids:[...el('draft-materials').querySelectorAll('input:checked')].map(i=>i.value),...(currentDraft?{}:{target_id:currentTarget})};
    const draft=await api('/drafts'+(currentDraft?'/'+currentDraft:''),body,currentDraft?'PATCH':'POST');
    FLOW.drafts[draft.id]=draft;loadDraft(draft.id);
  },'草稿已保存；尚未记为发送');
};
el('draft-export').onclick=()=>{statusArea='draft-status';return action(async()=>{
  const r=await fetch('/api/workflow/drafts/'+currentDraft+'/eml');if(!r.ok)throw new Error((await r.json()).error);
  const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='mentor-draft.eml';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
},'已导出邮件与附件，请在邮件客户端核对并发送；尚未记为发送');};
el('draft-confirm').onclick=()=>action(()=>api('/drafts/'+currentDraft+'/confirm',{sent:el('sent-confirmed').checked,date:el('sent-date').value},'POST'),'已记录实际发送，当前目标进入等待回复');
el('stage-save').onclick=()=>action(()=>api('/targets/'+currentTarget,{stage:el('context-stage-edit').value},'PATCH'),'联系阶段已更新并留痕');
el('reply-form').onsubmit=e=>{
  statusArea='reply-status';
  const hasTask=!!el('reply-task').value.trim();
  e.preventDefault();action(async()=>{
    const task=el('reply-task').value.trim(),due=el('reply-due').value;
    if(!task&&due)throw new Error('填写计划日期时也请填写下一步内容');
    await api('/targets/'+currentTarget+'/reply',{content:el('reply-content').value,date:el('reply-date').value,stage:el('reply-stage').value,
      ...(task?{task:{title:task,due_date:due}}:{})},'POST');
    resetReply();
  },hasTask?'回复已记录，下一步已同步到待办':'回复已记录；本次未新增下一步，可到“下一步”安排提醒');
};
el('reply-form').addEventListener('input',()=>{replyDirty=true;});
window.addEventListener('beforeunload',e=>{if(dirty||replyDirty||taskDirty){e.preventDefault();e.returnValue='';}});
el('desk-backup').onclick=()=>action(async()=>{
  const result=await api('/backup'),url=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='contact-workflow-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
},'备份已导出（不包含附件原文件）');
el('desk-restore').onclick=()=>el('desk-restore-file').click();
el('desk-restore-file').onchange=async e=>{
  const file=e.target.files[0];if(!file)return;
  if(!confirm('恢复会替换私人工作流，服务将先保留原索引副本。继续？')){e.target.value='';return;}
  await action(async()=>{await api('/restore',JSON.parse(await file.text()),'POST');loadedTarget='';dirty=false;},'已恢复备份');e.target.value='';
};
function showPanel(panel){
  currentPanel=panel;
  for(const name of ['mail','tasks','reply','history'])el('prepare-'+name).hidden=name!==panel;
  document.querySelectorAll('[data-panel]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.panel===panel)));
  for(const id of ['manage-link','welcome-manage','target-manage','draft-manage'])el(id).href=manageUrl();
  el('draft-manage').href=manageUrl()+'&section=material';
}
function resetTask(){el('task-form').reset();editingTask='';taskDirty=false;el('task-save').textContent='新增提醒';}
function discardPrepare(){if(dirty)loadDraft(currentDraft);if(replyDirty)resetReply();if(taskDirty)resetTask();}
function renderTargetTasks(){
  const t=target();if(!t)return;
  const rows=Object.values(FLOW.reminders).filter(r=>r.project_id===t.project_id&&r.mentor_id===t.mentor_id).sort((a,b)=>Number(a.completed)-Number(b.completed)||a.due_date.localeCompare(b.due_date));
  el('target-task-list').innerHTML=rows.map(r=>`<article><h3>${esc(r.title)}</h3><small>${r.completed?'已完成':r.due_date<=today()?'已到期':'计划'} · ${esc(r.due_date)}</small><div class="article-actions"><button type="button" data-task-toggle="${r.id}">${r.completed?'重新打开':'完成'}</button><button type="button" data-task-edit="${r.id}">编辑</button></div></article>`).join('')||'<p class="muted">还没有下一步。可先安排核对要求、准备材料或后续联系。</p>';
}
function renderIncoming(){
  if(!incomingMentor||target())return;
  el('welcome').hidden=true;
  el('prepare-empty').innerHTML=`<h2>准备联系 ${esc(personName(incomingMentor))}</h2><p>${esc(personLabel(incomingMentor))}</p>`+(Object.keys(FLOW.projects).length?'<p>选择适用的申请项目，即可把这位导师加入目标，无需重新搜索。</p><button data-view="targets">选择项目并加入 →</button>':`<p>先为这位导师建立申请项目，再准备材料与邮件。</p><a href="${esc(manageUrl())}">为这位导师建立项目 →</a>`);
}
el('task-form').addEventListener('input',()=>taskDirty=true);
el('task-reset').onclick=()=>{if(taskDirty&&!confirm('提醒尚未保存，清空修改？'))return;resetTask();};
el('task-form').onsubmit=e=>{e.preventDefault();statusArea='task-status';action(async()=>{
  const t=target();await api('/reminders'+(editingTask?'/'+editingTask:''),{title:el('task-title').value,due_date:el('task-due').value,mentor_id:t.mentor_id,project_id:t.project_id},editingTask?'PATCH':'POST');resetTask();
},'提醒已保存，可继续添加下一条');};
el('target-task-list').onclick=e=>{const b=e.target.closest('button');if(!b)return;statusArea='task-status';
  if(b.dataset.taskToggle){const r=FLOW.reminders[b.dataset.taskToggle];action(()=>api('/reminders/'+r.id,{completed:!r.completed},'PATCH'),'提醒已更新');}
  if(b.dataset.taskEdit){if(taskDirty&&!confirm('提醒尚未保存，放弃修改并编辑另一条？'))return;const r=FLOW.reminders[b.dataset.taskEdit];editingTask=r.id;el('task-title').value=r.title;el('task-due').value=r.due_date;taskDirty=false;el('task-save').textContent='保存提醒';el('task-title').focus();}
};
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.closest('#draft-form')||b.id==='draft-confirm'||b.id==='draft-export')statusArea='draft-status';else if(b.closest('#reply-form'))statusArea='reply-status';else if(b.closest('#task-form')||b.closest('#target-task-list'))statusArea='task-status';else statusArea='';},true);
el('reply-date').value=today();el('sent-date').value=today();renderMentorSearch();showPanel(currentPanel);showView(currentView);
renderGoal();
if(['http:','https:'].includes(location.protocol)){
  el('desk-restore').disabled=false;
  refresh().then(()=>{el('desk-workspace').disabled=false;})
    .catch(e=>message('无法读取私人工作流：'+e.message,true));
}

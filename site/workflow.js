/* Account-scoped workflow; private records are never embedded in static pages. */
const el = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mentors = new Map((window.MENTOR_DATA || []).map(p => [p.page, p]));
const projectLabels = {planned:'准备中',submitted:'已提交',interview:'面试中',accepted:'已录取',rejected:'未录取',archived:'归档'};
const materialLabels = {paper:'论文',letter:'信件',cv:'简历',application:'申请材料',other:'其他'};
const communicationLabels = {draft:'草稿',sent:'已发送',replied:'收到回复',note:'备注 / 更正'};
let WORKFLOW = {projects:{},materials:{},communications:{},reminders:{}};
let currentSection=['project','preparation','material','communication','reminder'].includes(new URLSearchParams(location.search).get('section')) ? new URLSearchParams(location.search).get('section') : 'project';
let contextReady=false,actionBusy=false;
let materialView='current';
const formDirty=new Set();
let editing = {project:null,material:null,reminder:null};
let projectDates=[];
let renderedPolicyEvents;
const projectSchools=Array.isArray(window.ADMISSIONS_DATA.schools)?window.ADMISSIONS_DATA.schools.map(s=>[s.id,s.name]):[...new Map(window.ADMISSIONS_DATA.units.map(u=>[u.school,u.school_name])).entries()];
const schoolName=id=>projectSchools.find(s=>s[0]===id)?.[1]||id;
const goalLabels={master:'硕士',phd:'博士',recommend:'推免',exam:'统考',assessment:'申请考核',ordinary:'普通招生',special:'专项 / 特定项目'};
const dateLabels={deadline:'报名 / 材料截止',exam:'考试 / 考核安排',qualification:'资格相关时间',plan:'个人计划'};
const goalKeys={school_id:'school-id',dept_id:'dept-id',degree:'degree',route:'route',track:'track',program_code:'program-code',program_name:'program-name'};
let contextMentor = new URLSearchParams(location.search).get('mentor') || '';
if(!mentors.has(contextMentor)) contextMentor = '';
const backQuery=new URLSearchParams({view:'prepare'});
if(contextMentor)backQuery.set('mentor',contextMentor);
let returnTarget=new URLSearchParams(location.search).get('target');
let returnProject=new URLSearchParams(location.search).get('project');
if(returnTarget)backQuery.set('target',returnTarget);
const incomingGoal=new URLSearchParams(location.search);
const discoveryReturn=incomingGoal.get('discovery_return')||'';
const validDiscoveryReturn=/^discovery\.html(?:\?[^#\\\x00-\x20]*)?$/.test(discoveryReturn);
if(validDiscoveryReturn){backQuery.set('discovery_return',discoveryReturn);for(const a of document.querySelectorAll('a[href="discovery.html"]'))a.href=discoveryReturn;}
let incomingPolicy=window.ADMISSIONS_DATA?.policies.find(p=>p.id===incomingGoal.get('policy'));
for(const key of ['year','degree','route','school','dept','track','program','panel'])if(incomingGoal.has(key))backQuery.set(key,incomingGoal.get(key));
el('back-desk').href='desk.html?'+backQuery;
const chosen = {project:[],material:[],communication:[],reminder:[]};
window.WORKFLOW_READY = false;
const mentorName = id => {
  const p = mentors.get(id);
  return p ? `${p.name} · ${p.school_name || p.school} · ${p.dept_name || p.dept}` : id;
};
const mentorLinks = ids => ids.map(id=>`<a href="p/${encodeURIComponent(id)}.html">${esc(mentorName(id))}</a>`).join('；');
const projectName = id => WORKFLOW.projects[id]?.name || '';
const selected = id => [...el(id).selectedOptions].map(o=>o.value);
function projectScope(p){return {school:p.school_id||'',dept:p.dept_id||'',year:p.year,degree:p.degree||'',route:p.route||'',track:p.track||'',program:p.program_name?(p.program_code||'')+'|'+p.program_name:''};}
function projectChecklist(p){return AdmissionsRules.checklist(window.ADMISSIONS_DATA,projectScope(p));}
function projectForm(){return {...Object.fromEntries(Object.entries(goalKeys).map(([key,suffix])=>[key,el('project-'+suffix).value.trim()])),year:el('project-year').value?Number(el('project-year').value):null};}
function setGoalOptions(id,rows,value=''){el(id).innerHTML='<option value="">未知 / 未指定</option>'+rows.map(([key,label])=>`<option value="${esc(key)}">${esc(label)}</option>`).join('');if(value&&!rows.some(row=>row[0]===value))el(id).add(new Option('原记录：'+value+'（目录未收录，需核对）',value));el(id).value=value;}
function projectDepts(value=''){setGoalOptions('project-dept-id',window.ADMISSIONS_DATA.units.filter(u=>u.school===el('project-school-id').value).map(u=>[u.dept,u.dept_name]),value);}
function setProjectGoal(p){setGoalOptions('project-school-id',projectSchools,p.school_id||'');projectDepts(p.dept_id||'');for(const [key,suffix] of Object.entries(goalKeys))if(!['school_id','dept_id'].includes(key))el('project-'+suffix).value=p[key]||'';}
function applicableEvents(p){const result=projectChecklist(p);return result.ready?result.events.filter(row=>!row.conditional&&!(p.track==='special'&&row.policy.level==='school')):[];}
function policyDate(row){const source_ids=row.event.source_ids||[row.policy.source_id];return {label:row.event.label,kind:row.event.kind,at:row.event.at,origin:'policy',policy_id:row.policy.id,source_ids,source_url:window.ADMISSIONS_DATA.sources[source_ids[0]].url,quote:row.event.quote,locator:row.event.locator};}
function dateKey(d){return JSON.stringify([d.policy_id,d.kind,d.label,d.at,d.quote,d.locator,d.source_ids,d.source_url]);}
function dateStatus(d){
  const state=AdmissionsRules.eventState({at:d.at});
  if(d.origin==='manual')return state==='unknown'?'日期状态未知，需核实':state==='past'?'计划日期已过':'个人计划日期未过';
  if(state==='unknown')return '日期状态未知，需核实；不表示接受新报名';
  if(d.kind==='deadline')return state==='past'?'该事项已截止；不表示整轮招生结束':'该事项截止（报名/材料/准考证等）；不表示接受新报名';
  if(d.kind==='exam')return state==='past'?'既往考核安排；不代表新报名':'考核安排，仅适用已达本轮条件者；不代表新报名';
  return state==='past'?'既往安排；不代表新报名':'已登记安排；适用条件须核对，不表示接受新报名';
}
function reminderDay(at){return /^\d{4}-\d{2}-\d{2}$/.test(at)?at:new Date(at).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});}
function snapshotStatus(d){if(d.origin!=='policy')return '个人计划（手动登记，参考来源未核验）';const p=window.ADMISSIONS_DATA.policies.find(p=>p.id===d.policy_id);if(!p||!(p.events||[]).some(event=>dateKey(policyDate({policy:p,event}))===dateKey(d)))return '原政策已变化 / 未找到，日期需重新核对';if(p.applies_if)return '条件待本人核对：'+p.applies_if.text+'；历史快照保留，不表示已确认适用';return AdmissionsRules.quality(p,window.ADMISSIONS_DATA.checks).label;}
function sourceLinks(policy,item){return AdmissionsRules.sourceReferences(policy,item,window.ADMISSIONS_DATA.sources).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>`).join(' · ');}
function snapshotLinks(d){const refs=d.source_ids.map(id=>window.ADMISSIONS_DATA.sources[id]).filter(Boolean),current=refs.map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label||'官方原文')}</a>`).join(' · ');return current+(d.source_url&&(!refs.length||refs[0].url!==d.source_url)?`${current?' · ':''}<a href="${esc(d.source_url)}" target="_blank" rel="noopener">${d.origin==='manual'?'手动参考来源':'登记时来源'}</a>`:'');}
function goalQuery(p){const q=new URLSearchParams();for(const [key,value] of Object.entries(projectScope(p)))if(value)q.set(key,value);return q;}
function goalTitle(p){
  if(p.opportunity)return '活动准备 · '+p.opportunity.unit+' · '+(p.opportunity.graduation_year?p.opportunity.graduation_year+'届':'届别未明确');
  const unit=window.ADMISSIONS_DATA.units.find(u=>u.school===p.school_id&&u.dept===p.dept_id);
  const known=[schoolName(p.school_id),unit?.dept_name||p.dept_id,p.year,goalLabels[p.degree],goalLabels[p.route],goalLabels[p.track],p.program_name?(p.program_code||'')+' '+p.program_name:''].filter(Boolean);
  if(!['school_id','dept_id','year','degree','route','track'].every(key=>p[key]))known.push('招生目标待补充，暂不能匹配完整要求');
  return known.join(' · ');
}
function reminderStatus(r,today=reminderDay(new Date().toISOString())){return r.completed?'已完成':r.due_date<today?'逾期未完成':r.due_date===today?'今天':'待办';}
function projectRecentActions(p){
  const pending=Object.values(WORKFLOW.reminders).filter(r=>r.project_id===p.id&&!r.completed).sort((a,b)=>a.due_date.localeCompare(b.due_date));
  const reminder=pending[0],now=new Date().toISOString();
  const dates=(p.deadlines||[]).filter(d=>AdmissionsRules.eventState(d,now)==='future');
  const firstDay=dates.map(d=>reminderDay(d.at)).sort()[0];
  const sameDay=dates.filter(d=>reminderDay(d.at)===firstDay),dateOnly=sameDay.some(d=>/^\d{4}-\d{2}-\d{2}$/.test(d.at));
  // Without a time, same-day events have no known order. Keep their saved order instead of inventing midnight.
  if(!dateOnly)sameDay.sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
  const date=sameDay[0];
  if(!reminder&&!date)return '';
  return `<div class="project-next-actions"><h4>${p.status==='archived'?'归档记录':'近期行动'}</h4>${p.status==='archived'?'<p class="muted">项目已归档；保留的未完成提醒仍可管理。</p>':''}<p><strong>未完成提醒${pending.length?' · '+pending.length+' 项':''}</strong>${reminder?`<br><span class="${reminder.due_date<reminderDay(now)?'overdue':''}">${esc(reminderStatus(reminder,reminderDay(now)))} · ${esc(reminder.due_date)}</span> · ${esc(reminder.title)}<br>${reminder.mentor_id?'导师事项：'+esc(mentorName(reminder.mentor_id)):'项目事项'}`:'<br><span class="muted">暂无未完成提醒。</span>'}</p><button type="button" data-project-section="reminder" data-project-id="${esc(p.id)}">查看此项目提醒</button><p><strong>后续安排</strong>${date?`<br>${esc(date.origin==='policy'?'官方事件快照':'个人计划')} · ${esc(dateLabels[date.kind])} · ${esc(date.label)}<br>${esc(date.at)} · ${esc(dateStatus(date))}${date.origin==='policy'?`<br><small>${esc(snapshotStatus(date))}；申请前核对原文。</small>`:''}${sameDay.length>1?`<br><small>同日另有 ${sameDay.length-1} 条安排${dateOnly?'，因日期精度不同或未注明时刻，先后未确定':''}；完整安排请展开目标与要求。</small>`:/^\d{4}-\d{2}-\d{2}$/.test(date.at)?'<br><small>仅登记日期，未注明具体时刻。</small>':''}`:'<br><span class="muted">尚未登记后续安排；不表示没有申请截止时间。</span>'}</p></div>`;
}
function projectCard(p){return `<article><h3>${esc(p.name)} <span class="tag">${esc(projectLabels[p.status])}</span></h3><p>${esc(goalTitle(p))}</p>${p.school||p.college||p.application_type?`<details><summary>旧说明（不参与政策匹配）</summary><p>${esc([p.school,p.college,p.application_type].filter(Boolean).join(' · '))}</p></details>`:''}<p>${mentorLinks(p.mentor_ids)}</p><p>${esc(p.notes)}</p>${projectRecentActions(p)}${projectRequirements(p)}<button type="button" data-project-section="material" data-project-id="${esc(p.id)}">上传材料</button> <button type="button" data-project-section="communication" data-project-id="${esc(p.id)}">记录沟通</button> <button type="button" data-project-section="preparation" data-project-id="${esc(p.id)}">准备清单</button> <button type="button" data-edit-project="${p.id}">编辑项目</button> <button type="button" data-focus-project="${p.id}">查看关联记录</button></article>`;}
function renderGoalEditor(){
  const p=projectForm(),result=projectChecklist(p);
  el('project-goal-preview').textContent=result.ready?'目标已填写；保存后绑定。专业 / 项目未指定时，其专属要求仅作条件性参考。':'结构化目标尚未完整，保存后也不会借用其他目标政策。';
  el('project-dates').innerHTML=projectDates.map((d,i)=>`<p>${esc(d.origin==='policy'?'官方事件快照':'手动登记')} · ${esc(dateLabels[d.kind])} · ${esc(d.label)} · ${esc(d.at)} · ${esc(dateStatus(d))} <button type="button" data-remove-project-date="${i}">移除</button> ${snapshotLinks(d)}<br><small>${esc(snapshotStatus(d))}</small></p>`).join('')||'<p class="muted">尚未保存项目日期。</p>';
  const events=applicableEvents(p);
  const eventHtml=events.map((row,i)=>`<p>${esc(dateLabels[row.event.kind])} · ${esc(row.event.label)} · ${esc(row.event.at)} · ${esc(dateStatus({...row.event,origin:"policy"}))} · ${sourceLinks(row.policy,row.event)} <button type="button" data-add-policy-date="${i}">加入项目日期</button><br><small>${esc(row.quality.label)}</small></p>`).join('')||'<p class="muted">当前目标没有可直接加入的官方事件；未知日期仍须查原文。</p>';
  if(renderedPolicyEvents!==eventHtml){el('project-policy-dates').innerHTML=eventHtml;renderedPolicyEvents=eventHtml;}
}
let opportunityCheckRunning=false;
async function refreshOpportunityChanges(){
  if(opportunityCheckRunning||!Object.values(WORKFLOW.projects).some(p=>p.opportunity))return;
  opportunityCheckRunning=true;
  try{
    const response=await fetch('/api/opportunities');if(!response.ok)throw new Error();
    const catalog=await response.json();
    for(const node of document.querySelectorAll('[data-opportunity-changes]')){
      const saved=WORKFLOW.projects[node.dataset.opportunityChanges]?.opportunity;if(!saved)continue;
      const current=catalog.opportunities.find(o=>o.id===saved.id),changes=OpportunityRules.changes(saved,current);
      const value=v=>Array.isArray(v)?v.map(x=>typeof x==='object'?[x.department,x.direction,x.contact,x.email].filter(Boolean).join(' · '):x).join('；'):String(v??'未明确')||'未明确';
      node.innerHTML=(!current?'<p class="hint">当前目录未找到此活动，请核对官方通知。原申请记录保留。</p>':
        `<p class="hint">当前活动状态：${esc(OpportunityRules.labels[OpportunityRules.state(current)])}。${catalog.feed_error?'更新服务暂不可用，以下比较基于服务器资料。':''}${changes.length?'发现 '+changes.length+' 项与保存时不同，请检查材料与个人提醒。':'与保存快照相比，申请条件、材料与时间未发现差异；仍需核对当前报名状态。'}</p>`)+
        (changes.length?'<details open><summary>查看变更，不覆盖原记录</summary>'+changes.map(c=>`<p><strong>${esc(c.label)}</strong><br>保存时：${esc(value(c.before))}<br>当前记录：${esc(value(c.after))}</p>`).join('')+'<p>个人准备进度和提醒日期未自动修改，请按核实后的要求调整。</p></details>':'');
    }
  }catch(error){for(const node of document.querySelectorAll('[data-opportunity-changes]'))node.textContent='暂时无法检查活动更新；保存记录仍可使用，请通过官方通知核对。';}
  finally{opportunityCheckRunning=false;}
}
function projectRequirements(p){
  if(p.opportunity){
    const o=p.opportunity,files=Object.values(WORKFLOW.materials).filter(m=>m.project_ids.includes(p.id));
    const list=values=>values.length?'<ul>'+values.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul>':'<p>尚未取得明确清单，请查原文。</p>';
    const window=o.application_window,windowInfo=window?`<p class="opportunity-window"><strong>${window.mode==='month'?'官方截止月份：'+esc(window.end_month)+'（具体日期未公布）':'官方说明长期 / 滚动受理；当前余位须联系确认'}</strong><br>原文：${esc(window.quote)}</p>`:'';
    const attachments=(o.source_attachments||[]).map((doc,index)=>`<p><a href="${esc(doc.url)}" target="_blank" rel="noopener">官方申请材料附件 ${index+1}（DOCX） ↗</a> · 核对 ${esc(doc.checked_at)}</p>`).join('');
    return `<details open><summary>活动条件与准备材料 · 关联文件 ${files.length}</summary><div data-opportunity-changes="${esc(p.id)}" role="status">正在核对活动更新…</div><p>${esc(o.unit)} · 面向 ${o.graduation_year?esc(o.graduation_year)+' 届':'届别未明确'} · 活动年份 ${o.camp_year||'未明确'}</p><p>登记的报名截止：${esc(o.deadline||'未明确')} · 活动时间：${esc(o.event_start||'待核对')}${o.event_end?' 至 '+esc(o.event_end):''}</p>${windowInfo}<p class="hint">保存时快照，核查于 ${esc(o.verified_at)}。${esc(o.source_note)} 活动不是正式录取；当前更新请回活动页核对。</p><a href="opportunities.html?id=${encodeURIComponent(o.id)}">查看活动最新记录 →</a> · <a href="${esc(o.source_url)}" target="_blank" rel="noopener">官方原文 ↗</a><h4>申请条件</h4>${list(o.eligibility)}<h4>材料与提交阶段</h4>${list(o.materials)}${attachments}<p>${esc(o.application_method)}</p><p>${esc(o.admission_note)}</p><h4>我的关联材料</h4>${files.length?'<ul>'+files.map(m=>'<li>'+esc(m.title)+(m.missing?' · 文件缺失':' · 已登记文件，不代表已提交')+'</li>').join('')+'</ul>':'<p>尚未关联材料。先上传材料，再关联到此项目。</p>'}<button type="button" data-project-section="material" data-project-id="${esc(p.id)}">关联上传材料</button></details>`;
  }
  const scope=projectScope(p),result=projectChecklist(p),q=goalQuery(p);
  const materials=Object.values(WORKFLOW.materials).filter(m=>m.project_ids.includes(p.id));
  const materialRows=materials.map(m=>`<li><strong>${esc(m.title)}</strong> · ${esc(materialLabels[m.kind])} · ${m.missing?'<span class="bad">索引标记文件缺失</span>':'已登记文件'} <button type="button" data-project-section="material" data-project-id="${esc(p.id)}" data-edit-material="${esc(m.id)}">编辑材料关联</button></li>`).join('');
  const unit=window.ADMISSIONS_DATA.units.find(u=>u.school===scope.school&&u.dept===scope.dept);
  const summary=result.ready?`${unit.school_name} · ${unit.dept_name} · ${p.year} · ${goalLabels[p.degree]} · ${goalLabels[p.route]} · ${goalLabels[p.track]}${p.program_name?' · '+(p.program_code||'')+' '+p.program_name:' · 正式专业 / 项目未知'}`:'结构化目标尚未完整：请编辑项目明确学校、院系、年度、学位、渠道和类别；旧文本不用于匹配。';
  const rows=result.ready?result.items.find(item=>item.key==='materials').rows:[];
  const requirements=rows.map(row=>`<p>${esc({school:'学校通用',dept:'院系要求',program:'专业 / 项目要求'}[row.policy.level])}${row.conditional?' · '+esc(AdmissionsRules.conditionLabel(row.policy,true)):''}${p.track==='special'&&row.policy.level==='school'?' · 专项适用待核实':''} · ${esc(row.policy.title)}<br>${row.field?esc(row.field.text):'材料要求尚未整理，需查原文；不代表没有要求。'}<br>${row.field?`原文：${esc(row.field.quote)} · ${esc(row.field.locator)}<br>`:''}${sourceLinks(row.policy,row.field)}${row.policy.applies_if?`<br>适用条件原文：${esc(row.policy.applies_if.quote)} · ${esc(row.policy.applies_if.locator)} · ${sourceLinks(row.policy,row.policy.applies_if)}`:''}<br><small>${esc(row.quality.label)}</small></p>`).join('')||'<p>当前目标的材料要求尚未整理，需查官方原文。</p>';
  const dates=(p.deadlines||[]).map((d,i)=>`<p>${esc(d.origin==='policy'?'官方事件快照':'手动登记')} · ${esc(dateLabels[d.kind])} · ${esc(d.label)} · ${esc(d.at)} · ${esc(dateStatus(d))} ${snapshotLinks(d)}${d.quote||d.locator?`<br>原文：${esc(d.quote)} · ${esc(d.locator)}`:''}<br><small>${esc(snapshotStatus(d))}</small> <button type="button" data-project-reminder="${esc(p.id)}" data-date-index="${i}">设为项目提醒</button></p>`).join('')||'<p>尚无已保存日期；未显示不表示无截止安排。</p>';
  return `<details><summary data-project-requirements="${esc(p.id)}">目标与要求 · ${result.ready?'目标已保存':'结构化目标尚未完整'} · 关联材料 ${materials.length} · 已保存日期 ${(p.deadlines||[]).length}</summary><p>${esc(summary)}</p>${!result.ready&&projectSchools.some(s=>s[0]===scope.school)?`<p>${esc(schoolName(scope.school))} · ${scope.dept?'院系及完整目标需继续核对':'院系待补'}；学校层目标已保存，尚未绑定完整申请要求或官方日期。<a href="admissions.html?${q}">回查学校政策</a></p>`:''}${result.ready?`<p><a href="admissions.html?${q}">核对对应政策</a> · <a href="discovery.html?project=${encodeURIComponent(p.id)}&${q}">带目标找导师</a> · <a href="desk.html?view=targets&project=${encodeURIComponent(p.id)}&${q}">到联系人工作台</a></p><p>当前范围 ${result.policies.length} 条政策摘要。摘要与材料登记不表示要求完整或符合资格。</p>`:''}<h4>材料要求与已有文件</h4>${requirements}<p>已关联 ${materials.length} 个文件 · 索引标记缺失 ${materials.filter(m=>m.missing).length} 个。请按官方要求核对文件内容。</p>${materialRows?`<ul class="project-materials">${materialRows}</ul>`:'<p class="muted">尚无直接关联文件，可先登记或关联已有材料。</p>'}<div class="actions"><button type="button" data-project-section="material" data-project-id="${esc(p.id)}">管理此项目材料</button></div><h4>项目日期</h4>${dates}<p class="muted">日历提醒按北京时间日期，具体时刻见原文。抓取、发布、摘要核对日期不作为报名截止；官方快照须申请前重新核对。</p></details>`;
}
function message(text, error=false){const node=window.WORKFLOW_READY ? el(currentSection+'-feedback') : el('message');node.textContent=text;node.classList.toggle('error',error);}
async function api(path='', body, method='GET'){
  const r = await fetch('/api/workflow' + path, {method, headers:{'Content-Type':'application/json'},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await r.json();
  if(!r.ok) throw new Error(data.error || `请求失败：${r.status}`);
  return data;
}
async function refresh(){
  WORKFLOW=await api();render();
  if(!contextReady){
    const t=WORKFLOW.targets?.[returnTarget];
    if(t){contextMentor=t.mentor_id;el('filter-project').value=t.project_id;backQuery.set('mentor',t.mentor_id);el('back-desk').href='desk.html?'+backQuery;}
    else if(WORKFLOW.projects[returnProject]){el('filter-project').value=returnProject;backQuery.set('project',returnProject);el('back-desk').href='desk.html?'+backQuery;}
    contextReady=true;for(const key of Object.keys(chosen))reset(key);render();
  }
  window.WORKFLOW_READY=true;showSection(currentSection);el('service-hint').hidden=true;el('workflow-backup').disabled=false;
}
async function action(task, success){
  if(actionBusy)return;
  actionBusy=true;
  const button=document.activeElement?.tagName==='BUTTON'?document.activeElement:null;
  const label=button?.textContent,busyText=button?.id==='material-save'&&!editing.material?'正在上传…':'正在保存…';
  if(button)button.textContent=busyText;
  el('workspace').disabled=true;el('workspace').setAttribute('aria-busy','true');
  el('workflow-restore').disabled=true;el('workflow-backup').disabled=true;
  let saved=false;
  try{await task();saved=true;await refresh();message(typeof success==='function' ? success() : success);}
  catch(e){message(saved?'操作已完成，但列表刷新失败，请刷新页面核对，勿重复提交。':e.message,true);}
  finally{
    actionBusy=false;el('workspace').removeAttribute('aria-busy');
    el('workspace').disabled=!window.WORKFLOW_READY;el('workflow-restore').disabled=false;el('workflow-backup').disabled=!window.WORKFLOW_READY;
    if(button?.textContent===busyText)button.textContent=label;
    el(currentSection+'-feedback')?.scrollIntoView({block:'nearest'});
  }
}
function options(id, entries, placeholder){
  const old = selected(id);
  el(id).innerHTML=(placeholder === undefined ? '' : `<option value="">${esc(placeholder)}</option>`) +
    entries.map(([key,label])=>`<option value="${esc(key)}">${esc(label)}</option>`).join('');
  for(const o of el(id).options) o.selected=old.includes(o.value);
  if(!el(id).multiple && el(id).selectedIndex < 0) el(id).selectedIndex=0;
}
function renderPicker(prefix){
  el(prefix+'-mentor-selected').innerHTML=chosen[prefix].map(id=>`<span class="tag">${esc(mentorName(id))} <button type="button" data-remove-mentor="${esc(id)}" aria-label="取消关联">×</button></span>`).join('');
  const query=el(prefix+'-mentor-query').value.trim().toLowerCase();
  const results=query ? [...mentors.values()].filter(p=>!chosen[prefix].includes(p.page) &&
    `${p.page} ${p.name} ${p.school_name} ${p.dept_name}`.toLowerCase().includes(query)).slice(0,20) : [];
  el(prefix+'-mentor-results').innerHTML=results.map(p=>`<button type="button" data-add-mentor="${esc(p.page)}">${esc(mentorName(p.page))}<br><small>${esc(p.page)}</small></button>`).join('');
}
document.querySelectorAll('[data-mentor-picker]').forEach(box=>{
  const prefix=box.dataset.mentorPicker;
  box.innerHTML=`<label>关联导师${box.dataset.multiple ? '（可多选）' : '（单选）'}<input id="${prefix}-mentor-query" placeholder="搜索姓名 / 学校 / 导师 ID" autocomplete="off"></label><div class="mentor-results" id="${prefix}-mentor-results"></div><div class="selected" id="${prefix}-mentor-selected"></div>`;
  el(prefix+'-mentor-query').oninput=()=>renderPicker(prefix);
  box.onclick=e=>{
    const add=e.target.closest('[data-add-mentor]'), remove=e.target.closest('[data-remove-mentor]');
    if(add){chosen[prefix]=box.dataset.multiple ? [...chosen[prefix],add.dataset.addMentor] : [add.dataset.addMentor]; el(prefix+'-mentor-query').value='';}
    if(remove) chosen[prefix]=chosen[prefix].filter(id=>id!==remove.dataset.removeMentor);
    renderPicker(prefix);
  };
});
function reset(prefix){
  formDirty.delete(prefix);
  el(prefix+'-form').reset();
  if(prefix==='project'){projectDates=[];setProjectGoal({});el('project-date-feedback').textContent='';}
  if(prefix==='project'&&!WORKFLOW.targets?.[returnTarget]){
    const year=Number(incomingGoal.get('year'));
    if(Number.isInteger(year)&&year>=2000&&year<=2100)el('project-year').value=year;
    const degree={master:'硕士',phd:'博士'}[incomingGoal.get('degree')],route={recommend:'推免',exam:'统考',assessment:'申请考核'}[incomingGoal.get('route')];
    if(degree||route)el('project-type').value=[degree,route].filter(Boolean).join(' / ');
    const targetSchool=incomingGoal.get('school'),targetDept=incomingGoal.get('dept');
    const targetUnit=window.ADMISSIONS_DATA?.units.find(u=>u.school===targetSchool&&u.dept===targetDept);
    const knownSchool=projectSchools.some(s=>s[0]===targetSchool);
    if(knownSchool)el('project-school').value=schoolName(targetSchool);
    if(targetUnit)el('project-college').value=targetUnit.dept_name;
    const targetProgram=window.ADMISSIONS_DATA?.policies.find(p=>p.school===targetSchool&&p.dept===targetDept&&p.year===year&&p.degree===incomingGoal.get('degree')&&p.route===incomingGoal.get('route')&&p.track===incomingGoal.get('track')&&(p.program_code||'')+'|'+(p.program||'')===incomingGoal.get('program'));
    if(incomingGoal.get('track')==='special')el('project-type').value+=' / '+(targetProgram?.program||'专项（具体类型需核对）');
    if(knownSchool){
      const policyQuery=new URLSearchParams();
      for(const key of ['school','dept','year','degree','route','track','program'])if(incomingGoal.get(key))policyQuery.set(key,incomingGoal.get(key));
      el('project-notes').value='申请目标核对：'+new URL('admissions.html?'+policyQuery,location.href).href+'\n专业/项目'+(incomingGoal.get('program')?'：'+incomingGoal.get('program').replace('|',' · '):'未指定，需核对代码及正式名称')+'；未判断个人资格、导师机会或报名是否开放。';
    }
    if(incomingPolicy){
      const p=incomingPolicy,dept=p.dept||(targetSchool===p.school&&targetUnit?targetDept:''),unit=window.ADMISSIONS_DATA.units.find(u=>u.school===p.school&&u.dept===dept);
      el('project-name').value=p.title;el('project-year').value=p.year;
      el('project-school').value=schoolName(p.school);el('project-college').value=unit?.dept_name||'';
      el('project-type').value=[{master:'硕士',phd:'博士'}[p.degree],{recommend:'推免',exam:'统考',assessment:'申请考核'}[p.route]].join(' / ');
      if(p.track==='special')el('project-type').value+=' / '+(p.program||'专项（具体类型需核对）');
      el('project-notes').value='政策参考：'+p.title+'\n'+window.ADMISSIONS_DATA.sources[p.source_id].url+'\n摘要核对日期：'+p.reviewed_at+'；提交前需核实完整学校/院系/专业要求，不表示已符合资格。';
    }
    const policy=incomingPolicy;
    const dept=policy?(policy.dept||(targetSchool===policy.school&&targetUnit?targetDept:'')):incomingGoal.get('dept')||'';
    const same=policy&&targetSchool===policy.school&&targetUnit&&(!policy.dept||policy.dept===targetDept)&&year===policy.year&&incomingGoal.get('degree')===policy.degree&&incomingGoal.get('route')===policy.route;
    const generic=policy&&(!policy.track||policy.track==='general');
    const track=policy?(generic?(same?incomingGoal.get('track')||'':''):policy.track):incomingGoal.get('track')||'';
    const program=(policy?(policy.program?AdmissionsRules.programKey(policy):same&&track===incomingGoal.get('track')?incomingGoal.get('program')||'':''):incomingGoal.get('program')||'').split('|');
    setProjectGoal({school_id:policy?.school||incomingGoal.get('school')||'',dept_id:dept,degree:policy?.degree||incomingGoal.get('degree')||'',route:policy?.route||incomingGoal.get('route')||'',track,program_code:program[0]||'',program_name:program.slice(1).join('|')});
  }
  const project=el('filter-project').value,projectMentors=WORKFLOW.projects[project]?.mentor_ids||[];
  chosen[prefix]=contextMentor ? [contextMentor] : prefix!=='project'&&projectMentors.length===1 ? [...projectMentors] : [];
  if(prefix==='material')for(const o of el('material-projects').options)o.selected=o.value===project;
  if(prefix==='reminder'||prefix==='communication')el(prefix+'-project').value=project;
  renderPicker(prefix);
  if(prefix==='communication') el('communication-date').value=reminderDay(new Date().toISOString());
  else{
    editing[prefix]=null;
    el(prefix+'-save').textContent={project:'新增项目',material:'上传材料',reminder:'新增提醒'}[prefix];
    if(prefix==='material'){el('material-file-label').hidden=false;el('material-file').required=true;el('material-details').open=!project;}
  }
  if(prefix==='project')renderGoalEditor();
}
function render(){
  const projectOptions=Object.values(WORKFLOW.projects).map(p=>[p.id,`${p.name} · ${p.year ?? '年度未知'}`]);
  options('filter-project',projectOptions,'全部项目');
  options('material-projects',projectOptions);
  options('communication-project',projectOptions,'不关联项目');
  options('reminder-project',projectOptions,'不关联项目');
  options('communication-materials',Object.values(WORKFLOW.materials).map(m=>[m.id,`${m.title}${m.missing ? '（缺失）' : ''}`]));
  el('context-mentor').textContent=contextMentor ? '当前导师：'+mentorName(contextMentor) : '';
  el('clear-context').hidden=!contextMentor;
  const projectFilter=el('filter-project').value;
  el('project-context').hidden=!projectFilter;
  el('project-context').textContent=projectFilter ? '当前项目：'+projectName(projectFilter)+'。上传材料、记录沟通与提醒会默认关联此项目，可在表单中调整。' : '当前显示全部项目。新增记录时请选择关联项目。';
  const relatedProject=id=>!!id && (!projectFilter || id===projectFilter) && (!contextMentor || WORKFLOW.projects[id]?.mentor_ids.includes(contextMentor));
  const linked=(mentorIds,projectIds)=> (!projectFilter || projectIds.includes(projectFilter)) &&
    (!contextMentor || mentorIds.includes(contextMentor) || projectIds.some(relatedProject));
  const list=(id,rows)=>el(id).innerHTML=rows.join('') || '<div class="empty">暂无记录</div>';
  list('project-list',Object.values(WORKFLOW.projects).filter(p=>(!projectFilter || p.id===projectFilter) && (!contextMentor || p.mentor_ids.includes(contextMentor))).map(projectCard));
  if(!el('project-list').querySelector('article'))el('project-list').innerHTML='<div class="empty">'+(Object.keys(WORKFLOW.projects).length?'当前范围暂无申请项目；可切换项目或查看全部导师。':'先在下方填写项目名称并保存，学校与招生目标可以随后补充；再添加心仪导师、材料与提醒。')+'</div>';
  const materials=Object.values(WORKFLOW.materials);
  const scopedMaterials=materials.filter(m=>linked(m.mentor_ids,m.project_ids));
  const unassigned=materials.filter(m=>!m.project_ids.length);
  el('material-summary').textContent=`当前范围已上传 ${scopedMaterials.length} 份材料，其中 ${scopedMaterials.filter(m=>m.missing).length} 份需重新上传；另有 ${unassigned.length} 份材料未关联申请项目。请按学校官方要求检查材料是否齐全。`;
  el('material-current').setAttribute('aria-pressed',String(materialView==='current'));
  el('material-unassigned').setAttribute('aria-pressed',String(materialView==='unassigned'));
  el('material-scope').textContent=materialView==='unassigned' ? `正在查看全部未关联任何项目的材料（不按导师筛选）。${projectFilter ? '点击关联将加入项目：'+projectName(projectFilter)+'。' : '请先选择目标项目，再逐条关联。'}` : `正在按当前项目与导师范围查看材料。${projectFilter ? '当前项目：'+projectName(projectFilter)+'。' : ''}`;
  const visibleMaterials=materialView==='unassigned' ? unassigned : scopedMaterials;
  list('material-list',visibleMaterials.map(m=>
    `<article><h3>${esc(m.title)} <span class="tag">${esc(materialLabels[m.kind])}</span> ${m.missing ? '<span class="bad">文件缺失</span>' : ''}</h3><p><a href="/api/materials/${encodeURIComponent(m.id)}/download">下载材料</a></p><small>${m.size} 字节 · 保存时间：${esc(String(m.mtime||'').replace('T',' ').slice(0,16))}</small><p>${mentorLinks(m.mentor_ids)}</p><p>项目：${esc(m.project_ids.map(projectName).join('；')) || '未关联'}</p><p>${esc(m.notes)}</p><button type="button" data-edit-material="${m.id}">编辑关联</button> <button type="button" data-delete-material="${m.id}">删除材料</button>${projectFilter&&!m.project_ids.includes(projectFilter) ? ` <button type="button" data-link-material="${m.id}">关联到项目：${esc(projectName(projectFilter))}</button>` : ''}</article>`));
  if(!visibleMaterials.length)el('material-list').innerHTML=`<div class="empty">${!materials.length ? '尚未上传材料。请选择文件上传，并关联申请项目。' : materialView==='unassigned' ? '暂无未关联项目的材料。' : '当前范围暂无关联材料。未关联的文件不会自动归入项目，可查看未关联项目材料并逐条关联。'}</div>`;
  list('communication-list',Object.values(WORKFLOW.communications).filter(c=>(!projectFilter || c.project_id===projectFilter) && (!contextMentor || c.mentor_id===contextMentor)).sort((a,b)=>b.date.localeCompare(a.date) || b.created_at.localeCompare(a.created_at)).map(c=>
    `<article><h3>${esc(c.subject)} <span class="tag">${esc(communicationLabels[c.kind])}</span></h3><small>${esc(c.date)} · ${mentorLinks([c.mentor_id])} · ${esc(projectName(c.project_id))}</small><p>${esc(c.content)}</p><p>材料：${esc(c.material_ids.map(id=>WORKFLOW.materials[id].title).join('；')) || '未关联'}</p></article>`));
  const today=reminderDay(new Date().toISOString());
  list('reminder-list',Object.values(WORKFLOW.reminders).filter(r=>(!el('only-pending').checked || !r.completed) && linked(r.mentor_id ? [r.mentor_id] : [],r.project_id ? [r.project_id] : [])).sort((a,b)=>Number(a.completed)-Number(b.completed) || a.due_date.localeCompare(b.due_date)).map(r=>
    `<article><h3>${esc(r.title)}</h3><span class="${r.completed ? 'done' : r.due_date<today ? 'overdue' : ''}">${esc(reminderStatus(r,today))} · ${esc(r.due_date)}</span><p>${mentorLinks(r.mentor_id ? [r.mentor_id] : [])} ${esc(projectName(r.project_id))}</p><p>${esc(r.notes)}</p><button type="button" data-toggle-reminder="${r.id}">${r.completed ? '重新打开' : '完成'}</button> <button type="button" data-edit-reminder="${r.id}">编辑提醒</button></article>`));
  refreshOpportunityChanges();
}
function bindSubmit(prefix, collection, body){
  el(prefix+'-form').onsubmit=e=>{
    e.preventDefault();
    const payload=body();
    if(prefix==='project'){
      const old=WORKFLOW.projects[editing.project];
      const changed=old&&['year',...Object.keys(goalKeys)].some(key=>(old[key]??'')!==(payload[key]??''));
      const kept=changed?projectDates.filter(d=>d.origin!=='policy'):projectDates,removed=projectDates.length-kept.length;
      if(removed&&!confirm(`申请目标已改变。保存将清理 ${removed} 条官方事件快照，请保存后重新选择适用事件；手动计划保留。确认清理并保存？`))return;
      payload.deadlines=kept;
    }
    action(async()=>{
      const id=editing[prefix];
      const saved=await api('/'+collection+(id ? '/'+id : ''),payload,id ? 'PATCH' : 'POST');
      if(prefix==='project'&&!id){
        WORKFLOW.projects[saved.id]=saved;
        options('filter-project',Object.values(WORKFLOW.projects).map(p=>[p.id,p.name]),'全部项目');
        el('filter-project').value=saved.id;syncProjectContext();render();
        for(const key of Object.keys(chosen))reset(key);
        el('project-next').hidden=false;
      }else reset(prefix);
    },prefix==='project'?'申请项目已保存。可以继续上传材料或记录沟通。':prefix==='communication'?'沟通记录已保存到当前账号。':'提醒已保存');
  };
}
bindSubmit('project','projects',()=>({name:el('project-name').value,school:el('project-school').value,
  college:el('project-college').value,application_type:el('project-type').value,
  ...projectForm(),
  status:el('project-status').value,notes:el('project-notes').value,mentor_ids:chosen.project}));
el('material-form').onsubmit=e=>{
  e.preventDefault();
  action(async()=>{
    const payload={title:el('material-title').value,kind:el('material-kind').value,notes:el('material-notes').value,mentor_ids:chosen.material,project_ids:selected('material-projects')};
    if(editing.material)await api('/materials/'+editing.material,payload,'PATCH');
    else{
      const file=el('material-file').files[0];if(!file)throw new Error('请选择需要上传的文件');
      if(file.size>20_000_000)throw new Error('单个文件不能超过 20 MB');
      const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
      const response=await fetch('/api/materials/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,filename:file.name,content_base64:encoded})}),result=await response.json();
      if(!response.ok)throw new Error(result.error||'上传失败');
    }
    reset('material');
  },'材料已保存到账号，可在其他设备查看与下载');
};
bindSubmit('communication','communications',()=>({mentor_id:chosen.communication[0] || '',
  project_id:el('communication-project').value,kind:el('communication-kind').value,
  date:el('communication-date').value,subject:el('communication-subject').value,content:el('communication-content').value,
  material_ids:selected('communication-materials')}));
bindSubmit('reminder','reminders',()=>({title:el('reminder-title').value,due_date:el('reminder-due').value,
  mentor_id:chosen.reminder[0] || '',project_id:el('reminder-project').value,notes:el('reminder-notes').value}));
for(const prefix of ['project','material','reminder']) el(prefix+'-reset').onclick=()=>reset(prefix);
el('project-school-id').onchange=()=>{projectDepts();renderGoalEditor();};
for(const id of ['dept-id','degree','route','track','program-code','program-name','year'])el('project-'+id).addEventListener('change',renderGoalEditor);
el('project-add-date').onclick=()=>{
  const label=el('project-date-label').value.trim(),at=el('project-date-at').value;
  if(!label||!at){el('project-date-feedback').textContent='请填写个人计划名称与日期。';return;}
  const source=el('project-date-source').value.trim();
  if(source){try{const url=new URL(source);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error();}catch{el('project-date-feedback').textContent='参考来源需为不含账号密码的 HTTP(S) 链接。';return;}}
  projectDates.push({label:label.includes('个人计划')?label:'个人计划：'+label,kind:'plan',at,origin:'manual',policy_id:'',source_ids:[],source_url:el('project-date-source').value.trim(),quote:el('project-date-quote').value.trim(),locator:el('project-date-locator').value.trim()});
  formDirty.add('project');for(const suffix of ['label','at','source','quote','locator'])el('project-date-'+suffix).value='';el('project-date-feedback').textContent='个人计划已加入编辑列表；保存项目后生效。';renderGoalEditor();
};
for(const view of ['current','unassigned'])el('material-'+view).onclick=()=>{materialView=view;render();el('material-list').focus({preventScroll:true});el('material-list').scrollIntoView({block:'center'});};
document.querySelector('main').addEventListener('click',e=>{
  const button=e.target.closest('button'); if(!button) return;
  const d=button.dataset;
  if(d.deleteMaterial){if(!confirm('删除这份材料及文件？已被邮件、沟通历史或准备记录引用的材料不能直接删除。'))return;action(async()=>{const response=await fetch('/api/materials/'+encodeURIComponent(d.deleteMaterial),{method:'DELETE',headers:{'Content-Type':'application/json'},body:'{}'}),result=await response.json();if(!response.ok)throw new Error(result.error||'删除失败');},'材料已删除');return;}
  if(d.projectSection){
    el('filter-project').value=d.projectId;
    if(!el('filter-project').onchange())return;
    showSection(d.projectSection);
    el('section-'+d.projectSection).scrollIntoView({block:'start'});
  }
  if(d.removeProjectDate!==undefined){projectDates.splice(Number(d.removeProjectDate),1);formDirty.add('project');renderGoalEditor();}
  if(d.addPolicyDate!==undefined){const row=applicableEvents(projectForm())[Number(d.addPolicyDate)];if(row){const date=policyDate(row);if(!projectDates.some(item=>dateKey(item)===dateKey(date)))projectDates.push(date);formDirty.add('project');renderGoalEditor();}}
  if(d.projectReminder){const p=WORKFLOW.projects[d.projectReminder],date=p.deadlines[Number(d.dateIndex)];const due=reminderDay(date.at),title=date.label;
    if(Object.values(WORKFLOW.reminders).some(r=>r.project_id===p.id&&!r.mentor_id&&r.due_date===due&&r.title===title)){message('同名同日项目提醒已存在，未重复添加；可到提醒分区管理。');return;}
    action(()=>api('/reminders',{title,due_date:due,project_id:p.id,mentor_id:'',notes:[date.origin==='policy'?'官方事件快照；申请前核对原文':'个人计划',dateLabels[date.kind],'原始时间：'+date.at,'日历提醒按北京时间日期；具体事项时刻请查来源',date.source_url,date.quote,date.locator].filter(Boolean).join('\n')},'POST'),'已按北京时间日期设置项目提醒；原始时间与来源保存在备注。');
  }
  if(d.linkMaterial){
    const project=el('filter-project').value,m=WORKFLOW.materials[d.linkMaterial];
    if(!project||!m)return;
    action(()=>api('/materials/'+m.id,{project_ids:[...new Set([...m.project_ids,project])]},'PATCH'),'已关联到项目：'+projectName(project));
  }
  if(d.focusProject){el('filter-project').value=d.focusProject;el('filter-project').onchange();}
  if(d.toggleReminder){const r=WORKFLOW.reminders[d.toggleReminder]; action(()=>api('/reminders/'+r.id,{completed:!r.completed},'PATCH'),'提醒已更新');}
  for(const prefix of ['project','material','reminder']){
    const key=d['edit'+prefix[0].toUpperCase()+prefix.slice(1)]; if(!key) continue;
    const collection={project:'projects',material:'materials',reminder:'reminders'}[prefix];
    const item=WORKFLOW[collection][key]; editing[prefix]=key;
    const fields={project:{name:'name',school:'school',college:'college',type:'application_type',year:'year',status:'status',notes:'notes'},
      material:{title:'title',kind:'kind',notes:'notes'},reminder:{title:'title',due:'due_date',project:'project_id',notes:'notes'}}[prefix];
    for(const [suffix,field] of Object.entries(fields)) el(prefix+'-'+suffix).value=item[field] ?? '';
    if(prefix==='project'){el('project-goal-details').open=true;el('project-date-details').open=!!item.deadlines?.length;el('project-notes-details').open=!!item.notes;setProjectGoal(item);projectDates=(item.deadlines||[]).map(d=>({...d,source_ids:[...d.source_ids]}));renderGoalEditor();}
    chosen[prefix]=prefix==='reminder' ? (item.mentor_id ? [item.mentor_id] : []) : [...item.mentor_ids];
    renderPicker(prefix);
    if(prefix==='material'){
      el('material-file-label').hidden=true;el('material-file').required=false;el('material-details').open=true;
      for(const o of el('material-projects').options) o.selected=item.project_ids.includes(o.value);
    }
    el(prefix+'-save').textContent='保存修改';
    el(prefix+'-form').scrollIntoView({behavior:'smooth',block:'center'});
  }
});
function syncProjectContext(){
  const project=el('filter-project').value,p=WORKFLOW.projects[project];
  returnTarget=null;returnProject=project;incomingPolicy=null;
  for(const key of [...incomingGoal.keys()])incomingGoal.delete(key);
  if(!p||(contextMentor&&!p.mentor_ids.includes(contextMentor)))contextMentor='';
  const q=new URLSearchParams({section:currentSection});
  if(validDiscoveryReturn)q.set('discovery_return',discoveryReturn);
  if(project)q.set('project',project);
  if(contextMentor)q.set('mentor',contextMentor);
  history.replaceState(null,'',location.pathname+'?'+q);
  for(const key of [...backQuery.keys()])backQuery.delete(key);
  backQuery.set('view',project?'prepare':'today');
  if(validDiscoveryReturn)backQuery.set('discovery_return',discoveryReturn);
  if(project)backQuery.set('project',project);
  if(contextMentor)backQuery.set('mentor',contextMentor);
  el('back-desk').href='desk.html?'+backQuery;
}
el('filter-project').onchange=()=>{
  if(!discardChanges()){el('filter-project').value=lastProject;return false;}
  lastProject=el('filter-project').value;
  materialView='current';syncProjectContext();
  for(const key of Object.keys(chosen))reset(key);render();showSection(currentSection);
  el('project-next').hidden=true;
  return true;
};
el('only-pending').onchange=render;
el('clear-context').onclick=()=>{if(!discardChanges())return;contextMentor='';syncProjectContext();for(const key of Object.keys(chosen))reset(key);render();};
el('workflow-backup').onclick=()=>action(async()=>{
  const blob=new Blob([JSON.stringify(await api('/backup'),null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=url;a.download='application-workflow-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
},'备份已导出（不包含原材料文件）');
el('workflow-restore').onclick=()=>el('workflow-restore-file').click();
el('workflow-restore-file').onchange=async e=>{
  const file=e.target.files[0]; if(!file) return;
  if(!confirm('恢复将替换工作台全部记录，服务会先保留旧索引。原材料文件不受影响。')){e.target.value='';return;}
  await action(async()=>{
    await api('/restore',JSON.parse(await file.text()),'POST');
for(const prefix of Object.keys(chosen)) reset(prefix);
  },'已恢复工作台备份');
  e.target.value='';
};
let lastProject='';
function showSection(section){
  currentSection=section;
  for(const key of [...Object.keys(chosen),'preparation'])el('section-'+key).hidden=key!==section;
  document.querySelectorAll('[data-section]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.section===section)));
  const q=new URLSearchParams(location.search);q.set('section',section);history.replaceState(null,'',location.pathname+'?'+q);
  lastProject=el('filter-project').value;
  el('project-context').hidden=!lastProject&&section!=='material';
  if(section==='preparation'&&window.WORKFLOW_READY)window.MaterialPreparation?.refresh(WORKFLOW,lastProject);
}
function discardChanges(){
  if(window.MaterialPreparation&&!window.MaterialPreparation.discard())return false;
  if(!formDirty.size)return true;
  if(!confirm('表单尚未保存，继续会放弃修改。继续？'))return false;
  for(const key of [...formDirty])reset(key);return true;
}
for(const key of Object.keys(chosen))el(key+'-form').addEventListener('input',()=>formDirty.add(key));
document.addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.section){if(discardChanges())showSection(b.dataset.section);return;}
  if(b.dataset.editProject||b.dataset.editMaterial||b.dataset.editReminder||b.dataset.linkMaterial||['material-current','material-unassigned'].includes(b.id)||b.id.endsWith('-reset')){
    if(!discardChanges()){e.preventDefault();e.stopImmediatePropagation();}
  }
  if(b.dataset.addMentor||b.dataset.removeMentor){const box=b.closest('[data-mentor-picker]');if(box)formDirty.add(box.dataset.mentorPicker);}
},true);
window.addEventListener('beforeunload',e=>{if(formDirty.size){e.preventDefault();e.returnValue='';}});
window.MaterialPreparation?.init({reload:refresh});
showSection(currentSection);
for(const prefix of Object.keys(chosen)) reset(prefix);
if(['http:','https:'].includes(location.protocol)){
  el('workflow-restore').disabled=false;
  refresh().then(()=>{el('workspace').disabled=false;})
    .catch(e=>message('无法读取私人工作台：'+e.message,true));
}

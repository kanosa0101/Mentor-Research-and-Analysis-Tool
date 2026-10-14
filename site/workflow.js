/* 私人数据只经本地 API 读取；不写入静态文件或 localStorage。 */
const el = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mentors = new Map((window.MENTOR_DATA || []).map(p => [p.page, p]));
const projectLabels = {planned:'准备中',submitted:'已提交',interview:'面试中',accepted:'已录取',rejected:'未录取',archived:'归档'};
const materialLabels = {paper:'论文',letter:'信件',cv:'简历',application:'申请材料',other:'其他'};
const communicationLabels = {draft:'草稿',sent:'已发送',replied:'收到回复',note:'备注 / 更正'};
let WORKFLOW = {projects:{},materials:{},communications:{},reminders:{}};
let editing = {project:null,material:null,reminder:null};
let contextMentor = new URLSearchParams(location.search).get('mentor') || '';
if(!mentors.has(contextMentor)) contextMentor = '';
const backQuery=new URLSearchParams({view:'prepare'});
if(contextMentor)backQuery.set('mentor',contextMentor);
const returnTarget=new URLSearchParams(location.search).get('target');
if(returnTarget)backQuery.set('target',returnTarget);
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
function message(text, error=false){el('message').textContent=text; el('message').classList.toggle('error',error);}
async function api(path='', body, method='GET'){
  const r = await fetch('/api/workflow' + path, {method, headers:{'Content-Type':'application/json'},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await r.json();
  if(!r.ok) throw new Error(data.error || `请求失败：${r.status}`);
  return data;
}
async function refresh(){WORKFLOW=await api(); render(); el('service-hint').hidden=true; window.WORKFLOW_READY=true;}
async function action(task, success){
  el('workspace').disabled=true;
  el('workflow-restore').disabled=true;
  try{await task(); await refresh(); message(typeof success==='function' ? success() : success);}
  catch(e){message(e.message,true);}
  finally{el('workspace').disabled=!window.WORKFLOW_READY;el('workflow-restore').disabled=false;}
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
  el(prefix+'-form').reset();
  chosen[prefix]=contextMentor ? [contextMentor] : [];
  renderPicker(prefix);
  if(prefix==='communication') el('communication-date').value=new Date().toLocaleDateString('sv-SE');
  else{
    editing[prefix]=null;
    el(prefix+'-save').textContent={project:'新增项目',material:'登记文件',reminder:'新增提醒'}[prefix];
    if(prefix==='material') el('material-path').readOnly=false;
  }
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
  const relatedProject=id=>!!id && (!projectFilter || id===projectFilter) && (!contextMentor || WORKFLOW.projects[id]?.mentor_ids.includes(contextMentor));
  const linked=(mentorIds,projectIds)=> (!projectFilter || projectIds.includes(projectFilter)) &&
    (!contextMentor || mentorIds.includes(contextMentor) || projectIds.some(relatedProject));
  const list=(id,rows)=>el(id).innerHTML=rows.join('') || '<div class="empty">暂无记录</div>';
  list('project-list',Object.values(WORKFLOW.projects).filter(p=>(!projectFilter || p.id===projectFilter) && (!contextMentor || p.mentor_ids.includes(contextMentor))).map(p=>
    `<article><h3>${esc(p.name)} <span class="tag">${esc(projectLabels[p.status])}</span></h3><p>${esc(p.school)} · ${esc(p.college)} · ${esc(p.application_type)} · ${p.year ?? '年度未知'}</p><p>${mentorLinks(p.mentor_ids)}</p><p>${esc(p.notes)}</p><button type="button" data-edit-project="${p.id}">编辑项目</button> <button type="button" data-focus-project="${p.id}">查看关联记录</button></article>`));
  list('material-list',Object.values(WORKFLOW.materials).filter(m=>linked(m.mentor_ids,m.project_ids)).map(m=>
    `<article><h3>${esc(m.title)} <span class="tag">${esc(materialLabels[m.kind])}</span> ${m.missing ? '<span class="bad">文件缺失</span>' : ''}</h3><p class="path">${esc(m.path)}</p><small>${m.size} 字节 · 文件修改：${esc(m.mtime)}</small><p>${mentorLinks(m.mentor_ids)}</p><p>项目：${esc(m.project_ids.map(projectName).join('；')) || '未关联'}</p><p>${esc(m.notes)}</p><button type="button" data-edit-material="${m.id}">编辑关联</button></article>`));
  list('communication-list',Object.values(WORKFLOW.communications).filter(c=>(!projectFilter || c.project_id===projectFilter) && (!contextMentor || c.mentor_id===contextMentor)).sort((a,b)=>b.date.localeCompare(a.date) || b.created_at.localeCompare(a.created_at)).map(c=>
    `<article><h3>${esc(c.subject)} <span class="tag">${esc(communicationLabels[c.kind])}</span></h3><small>${esc(c.date)} · ${mentorLinks([c.mentor_id])} · ${esc(projectName(c.project_id))}</small><p>${esc(c.content)}</p><p>材料：${esc(c.material_ids.map(id=>WORKFLOW.materials[id].title).join('；')) || '未关联'}</p></article>`));
  const today=new Date().toLocaleDateString('sv-SE');
  list('reminder-list',Object.values(WORKFLOW.reminders).filter(r=>(!el('only-pending').checked || !r.completed) && linked(r.mentor_id ? [r.mentor_id] : [],r.project_id ? [r.project_id] : [])).sort((a,b)=>Number(a.completed)-Number(b.completed) || a.due_date.localeCompare(b.due_date)).map(r=>
    `<article><h3>${esc(r.title)}</h3><span class="${r.completed ? 'done' : r.due_date<=today ? 'overdue' : ''}">${r.completed ? '已完成' : r.due_date<=today ? '已到期' : '待办'} · ${esc(r.due_date)}</span><p>${mentorLinks(r.mentor_id ? [r.mentor_id] : [])} ${esc(projectName(r.project_id))}</p><p>${esc(r.notes)}</p><button type="button" data-toggle-reminder="${r.id}">${r.completed ? '重新打开' : '完成'}</button> <button type="button" data-edit-reminder="${r.id}">编辑提醒</button></article>`));
}
function bindSubmit(prefix, collection, body){
  el(prefix+'-form').onsubmit=e=>{
    e.preventDefault();
    action(async()=>{
      const id=editing[prefix];
      await api('/'+collection+(id ? '/'+id : ''),body(),id ? 'PATCH' : 'POST');
      reset(prefix);
    },'已保存');
  };
}
bindSubmit('project','projects',()=>({name:el('project-name').value,school:el('project-school').value,
  college:el('project-college').value,application_type:el('project-type').value,
  year:el('project-year').value ? Number(el('project-year').value) : null,
  status:el('project-status').value,notes:el('project-notes').value,mentor_ids:chosen.project}));
bindSubmit('material','materials',()=>({...(editing.material ? {} : {path:el('material-path').value}),
  title:el('material-title').value,kind:el('material-kind').value,notes:el('material-notes').value,
  mentor_ids:chosen.material,project_ids:selected('material-projects')}));
bindSubmit('communication','communications',()=>({mentor_id:chosen.communication[0] || '',
  project_id:el('communication-project').value,kind:el('communication-kind').value,
  date:el('communication-date').value,subject:el('communication-subject').value,content:el('communication-content').value,
  material_ids:selected('communication-materials')}));
bindSubmit('reminder','reminders',()=>({title:el('reminder-title').value,due_date:el('reminder-due').value,
  mentor_id:chosen.reminder[0] || '',project_id:el('reminder-project').value,notes:el('reminder-notes').value}));
for(const prefix of ['project','material','reminder']) el(prefix+'-reset').onclick=()=>reset(prefix);
el('scan-form').onsubmit=e=>{
  e.preventDefault();
  let summary;
  action(async()=>{summary=await api('/scan',{root:el('scan-root').value},'POST');},
    ()=>`扫描 ${summary.scanned} 个文件，新增 ${summary.added}，缺失 ${summary.missing}`);
};
document.querySelector('main').addEventListener('click',e=>{
  const button=e.target.closest('button'); if(!button) return;
  const d=button.dataset;
  if(d.focusProject){el('filter-project').value=d.focusProject; render();}
  if(d.toggleReminder){const r=WORKFLOW.reminders[d.toggleReminder]; action(()=>api('/reminders/'+r.id,{completed:!r.completed},'PATCH'),'提醒已更新');}
  for(const prefix of ['project','material','reminder']){
    const key=d['edit'+prefix[0].toUpperCase()+prefix.slice(1)]; if(!key) continue;
    const collection={project:'projects',material:'materials',reminder:'reminders'}[prefix];
    const item=WORKFLOW[collection][key]; editing[prefix]=key;
    const fields={project:{name:'name',school:'school',college:'college',type:'application_type',year:'year',status:'status',notes:'notes'},
      material:{path:'path',title:'title',kind:'kind',notes:'notes'},reminder:{title:'title',due:'due_date',project:'project_id',notes:'notes'}}[prefix];
    for(const [suffix,field] of Object.entries(fields)) el(prefix+'-'+suffix).value=item[field] ?? '';
    chosen[prefix]=prefix==='reminder' ? (item.mentor_id ? [item.mentor_id] : []) : [...item.mentor_ids];
    renderPicker(prefix);
    if(prefix==='material'){
      el('material-path').readOnly=true;
      for(const o of el('material-projects').options) o.selected=item.project_ids.includes(o.value);
    }
    el(prefix+'-save').textContent='保存修改';
    el(prefix+'-form').scrollIntoView({behavior:'smooth',block:'center'});
  }
});
el('filter-project').onchange=render;
el('only-pending').onchange=render;
el('clear-context').onclick=()=>{contextMentor='';history.replaceState(null,'',location.pathname);render();};
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
for(const prefix of Object.keys(chosen)) reset(prefix);
if(location.protocol==='http:'){
  el('workflow-restore').disabled=false;
  refresh().then(()=>{el('workspace').disabled=false;})
    .catch(e=>message('无法读取私人工作台：'+e.message,true));
}

const el=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DATA=window.MENTOR_DATA,MODES=['research','qualification','email','opportunity','eligibility'];
const incoming=new URLSearchParams(location.search);
let contextTrack=incoming.get('track')||'',contextProgram=incoming.get('program')||'',projectScoped=incoming.has('project')||DiscoveryRules.projectScoped({track:contextTrack,program:contextProgram});
let contextSchool=incoming.get('school')||'',contextDept=incoming.get('dept')||'';
let PRIVATE={preferences:{year:null,degree:'any',route:'unknown',topics:[],schools:[],keep_unknown:true,modes:{research:'hard',qualification:'soft',email:'soft',opportunity:'soft',eligibility:'soft'}},reviews:{}},API_OK=false,view=[],limit=20,reviewMentor='',applied=null,appliedGroup={value:'',label:'全部'};
let appliedName='',originalSchools=[],schoolSelectionChanged=false;
let matchingOrder=false, PROJECTS={projects:{},replies:{},project_reviews:{}},PROJECT_API=false,selectedProject='',reviewDirty=false,reviewGoal=null,selectionGoal=null,projectLoad=0,reviewRevision=0,savingReview=false;
const currentProject=()=>PROJECTS.projects[selectedProject];
const projectContext=()=>({project:currentProject(),projectIntent:projectScoped,project_reviews:PROJECTS.project_reviews});
const matchesCurrent=(prefs=readCriteria())=>DiscoveryRules.projectMatches(currentProject(),{...prefs,goal_snapshot:selectionGoal});
const protectedReview=()=>projectScoped&&!matchesCurrent();
function discardReview(){return !reviewDirty||confirm('核对表单尚未保存。放弃修改并切换？');}
function closeReview(){reviewRevision++;reviewDirty=false;reviewMentor='';el('review-panel').hidden=true;}
function projectGoalText(p){const g=p.goal_snapshot,u=window.ADMISSIONS_DATA?.units.find(u=>u.school===g.school_id&&u.dept===g.dept_id);return [u?.school_name||DATA.find(m=>m.school===g.school_id)?.school_name||g.school_id||'学校待补',u?.dept_name||DATA.find(m=>m.school===g.school_id&&m.dept===g.dept_id)?.dept_name||g.dept_id||'院系待补',g.year||'年度待补',degreeLabels[g.degree]||'学位待补',routeLabels[g.route]||'渠道待补',{ordinary:'普通招生',special:'专项'}[g.track]||'招生范围待补',g.program_code,g.program_name||'正式专业未指定'].filter(Boolean).join(' · ');}
function renderProjectCreate(){
  const prefs=readCriteria(),q=publicScope(),school=prefs.schools.length===1?prefs.schools[0]:'';
  if(q.get('school')!==school)for(const key of ['dept','track','program'])q.delete(key);
  if(school)q.set('school',school);else q.delete('school');
  for(const key of ['year','degree','route']){if(prefs[key]&&!['any','unknown'].includes(prefs[key]))q.set(key,prefs[key]);else q.delete(key);}
  el('review-project-create').href='applications.html'+(q.size?'?'+q:'');
}
function renderProject(){renderProjectCreate();const p=currentProject();el('project-options-label').textContent=p?'申请项目：'+p.name:projectScoped?'申请项目待核对':'申请项目与核对（可选）';if(p||selectedProject)el('project-context').hidden=true;el('generic-context').hidden=!projectScoped;const history=Object.values(PROJECTS.project_reviews).filter(r=>r.project_id===selectedProject&&(!r.applicable||[...(r.reasons||[]),...(r.opportunity_reasons||[]),...(r.eligibility_reasons||[])].some(reason=>reason!=='source_unmonitored')));el('review-project-history').hidden=!history.length;el('review-project-history-list').innerHTML=history.map(r=>`<p>${esc(DATA.find(m=>m.page===r.mentor_id)?.name||r.mentor_id)} · ${esc(r.checked_at)}：${esc([...new Set([...(r.reasons||[]),...(r.opportunity_reasons||[]),...(r.eligibility_reasons||[])])].map(DiscoveryRules.reviewReason).join('；'))}。对应失效结论按待核实处理，旧目标记录不参与当前判断。</p>`).join('');if(selectedProject&&!p&&!Array.from(el('review-project').options).some(o=>o.value===selectedProject))el('review-project').add(new Option('原项目已不存在或无法读取',selectedProject));el('review-project').value=selectedProject;el('review-project-edit').hidden=!p;el('review-project-confirm').hidden=!p;el('review-project-edit').href='applications.html?project='+encodeURIComponent(selectedProject);el('review-project-goal').textContent=p?('当前项目：'+p.name+' · '+projectGoalText(p)+(p.complete?(matchesCurrent()?'。核对记录只适用于此完整目标。':'。浏览目标与此项目不一致或目标已变更，请重新选择项目确认；已撤下旧判断。'):'。目标尚未完整：请补齐学校、院系、年度、学位、渠道、招生范围；专项需正式专业名称，有代码也需名称。')):(projectScoped?'当前项目不可用或未选择有效申请项目；判断保持待核实，不能保存。请重新选择项目，或明确选择普通浏览退出此范围。':'未选择申请项目；一般浏览保持原规则。具体专业／专项须选择完整申请项目才能保存核对。');for(const k of ['opportunity','eligibility'])el('mode-'+k).disabled=protectedReview();el('project-filter-hint').hidden=!protectedReview();if(protectedReview())el('project-filter-hint').textContent='尚无与当前浏览条件一致的完整项目，两项判断保持待核实，不借用通用结论过滤或排序；即使取消保留待核实，也不会据此排除。请选择项目，或编辑完整目标。';}
async function loadProjects(){const serial=++projectLoad;const data=await api('/project-reviews');if(serial!==projectLoad)return;PROJECTS=data;PROJECT_API=true;el('review-project').innerHTML='<option value="">普通浏览，不选择项目</option>'+Object.values(PROJECTS.projects).map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');if(selectedProject&&!currentProject())projectScoped=true;el('review-project-api').textContent=(Object.keys(PROJECTS.projects).length?'项目和核对仅在本机读取；选择和浏览不会保存。':'尚未创建申请项目。可先创建申请目标，再按完整目标核对导师；浏览与预填不会保存。');renderProject();}
function selectProject(id,fill=true){selectedProject=id;if(id)el('project-options').open=true;const p=currentProject();selectionGoal=p?structuredClone(p.goal_snapshot):null;if(p){const g=p.goal_snapshot;contextSchool=g.school_id;contextDept=g.dept_id;contextTrack=g.track;contextProgram=g.program_code||g.program_name?(g.program_code||'')+'|'+(g.program_name||''):'';projectScoped=true;if(fill){const prefs=readCriteria();fillCriteria({...prefs,year:g.year,degree:g.degree||'any',route:g.route||'unknown',schools:g.school_id?[g.school_id]:[]});}}else{contextSchool='';contextDept='';contextTrack='';contextProgram='';projectScoped=!!id;}closeReview();const q=new URLSearchParams(location.search);if(id)q.set('project',id);else for(const key of ['project','track','program','school','dept'])q.delete(key);history.replaceState(null,'',location.pathname+(q.size?'?'+q:''));renderProject();}

const orderSeed=(()=>{const fresh=()=>globalThis.crypto?.randomUUID?.()||String(Date.now()+Math.random());try{let seed=sessionStorage.getItem('discovery-order-seed');if(!seed){seed=fresh();sessionStorage.setItem('discovery-order-seed',seed);}return seed;}catch(e){return fresh();}})();
function publicScope(p){
  const q=new URLSearchParams();
  for(const k of ['year','degree','route'])if(applied?.[k]&& !['any','unknown'].includes(applied[k]))q.set(k,applied[k]);
  const school=contextSchool||(applied?.schools.length===1?applied.schools[0]:'');if(school)q.set('school',school);if(contextDept)q.set('dept',contextDept);
  if(contextSchool&&contextDept&&(!selectedProject||matchesCurrent(applied||readCriteria()))){const g=currentProject()?.goal_snapshot,track=g?.track||contextTrack,program=g?(g.program_code||g.program_name?(g.program_code||'')+'|'+(g.program_name||''):''):contextProgram;if(track)q.set('track',track);if(program)q.set('program',program);}
  if(p){if(q.get('school')!==p.school||q.get('dept')!==p.dept){q.delete('track');q.delete('program');}q.set('school',p.school);q.set('dept',p.dept);}
  return q;
}
const degreeLabels={any:'学位未确定',master:'硕士',phd:'博士'},routeLabels={unknown:'渠道未确定',recommend:'推免',exam:'统考',assessment:'申请考核'};
function message(text,error=false){el('discovery-message').textContent=text;el('discovery-message').classList.toggle('error',error);}
function readCriteria(){return {year:el('intent-year').value?Number(el('intent-year').value):null,degree:el('intent-degree').value,route:el('intent-route').value,
  topics:[...new Set(el('intent-topics').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean))],schools:[...el('intent-schools').selectedOptions].map(o=>o.value),keep_unknown:el('keep-unknown').checked,modes:Object.fromEntries(MODES.map(k=>[k,el('mode-'+k).value]))};}
function fillCriteria(p){el('intent-year').value=p.year??'';el('intent-degree').value=p.degree;el('intent-route').value=p.route;el('intent-topics').value=p.topics.join(', ');el('keep-unknown').checked=p.keep_unknown;for(const o of el('intent-schools').options)o.selected=p.schools.includes(o.value);for(const k of MODES)el('mode-'+k).value=p.modes[k];syncSchoolPicker();}
function syncSchoolPicker(){
  const options=[...el('intent-schools').options],selected=options.filter(o=>o.selected);
  for(const box of el('school-options').querySelectorAll('input'))box.checked=options.some(o=>o.value===box.value&&o.selected);
  el('school-chips').innerHTML=selected.map(o=>`<button type="button" data-remove-school="${esc(o.value)}" aria-label="移除${esc(o.textContent)}">${esc(o.textContent)} <span aria-hidden="true">×</span></button>`).join('');
  el('filter-options-label').textContent='学校与更多筛选 · '+(selected.length?selected.slice(0,2).map(o=>o.textContent).join('、')+(selected.length>2?' 等 '+selected.length+' 所':''):'不限学校');el('school-selected-count').textContent=selected.length?`已选 ${selected.length} 所`:'不限学校';el('clear-schools').disabled=!selected.length;
  const visible=[...el('school-options').children].filter(option=>!option.hidden);
  el('select-visible-schools').disabled=!visible.some(option=>!option.querySelector('input').checked);
}
function changeSchool(id,selected){if(!discardReview()){syncSchoolPicker();return;}closeReview();for(const o of el('intent-schools').options)if(o.value===id||id===null||Array.isArray(id)&&id.includes(o.value))o.selected=selected;el('intent-schools').dispatchEvent(new Event('change',{bubbles:true}));}
async function api(path='',body,method='GET'){const r=await fetch('/api/discovery'+path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d;}
const lazy=new Map();
function script(file){if(!lazy.has(file))lazy.set(file,new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=file+'?v=20261015-'+(file==='admissions-data.js'?'22':'17');s.onload=resolve;s.onerror=()=>{lazy.delete(file);s.remove();reject(new Error('无法加载 '+file+'，请确认静态文件完整'));};document.head.appendChild(s);}));return lazy.get(file);}
let unitCatalogAttempted=false;
async function loadUnitCatalog(){
  if(!contextSchool||!contextDept||DATA.some(p=>p.school===contextSchool&&p.dept===contextDept)||window.ADMISSIONS_DATA||unitCatalogAttempted)return;
  unitCatalogAttempted=true;
  try{await script('admissions-data.js');}catch(e){/* 目录失败不阻断已有导师浏览；院系提示保留待核对。 */}
}
async function apply(preserveReview=false,refresh=true){
  if(!preserveReview&&!discardReview())return;
  el('apply-criteria').disabled=true;
  try{
  await loadUnitCatalog();
  if(PROJECT_API&&refresh)try{await loadProjects();}catch(e){PROJECTS.project_reviews={};message('无法刷新项目核对，当前判断已撤下：'+e.message,true);}
  const prefs=readCriteria(),group={value:el('intent-group').value,label:el('intent-group').selectedOptions[0].textContent};if(prefs.year!==null&&(!Number.isInteger(prefs.year)||prefs.year<2000||prefs.year>2100))throw new Error('请填写有效年度');
  if(!preserveReview)closeReview();
  if(prefs.topics.length&&!window.MENTOR_SEARCH)await script('search.js');if(!window.MENTOR_COMPARE)await script('compare-data.js');
    applied=prefs;appliedName=el('intent-name').value.trim().toLowerCase();appliedGroup=group;el('criteria-dirty').hidden=true;limit=20;
    const rows=DATA.map(p=>({p,result:DiscoveryRules.evaluate(p,{...prefs,track:contextTrack,program:contextProgram,goal_snapshot:selectionGoal},PRIVATE.reviews,window.MENTOR_SEARCH?.[p.page]||'',undefined,projectContext())})).filter(row=>row.result.visible&&(!appliedName||row.p.name.toLowerCase().includes(appliedName))&&(!group.value||row.p.unit_groups?.includes(group.value))&&(!contextSchool||row.p.school===contextSchool)&&(!contextDept||row.p.dept===contextDept));
    const ranked=DiscoveryRules.rankCandidates(rows,prefs,window.MENTOR_COMPARE||{},orderSeed);view=ranked.rows;matchingOrder=ranked.matched;render();
  }finally{el('apply-criteria').disabled=false;}
}
let compareSelection=[];
try{compareSelection=[...new Set(JSON.parse(localStorage.getItem('compare_sel')||'[]'))].filter(id=>DATA.some(p=>p.page===id)).slice(0,5);}catch(e){}
function renderSelection(){for(const a of document.querySelectorAll('.site-header a[href]')){const path=a.getAttribute('href').split('?')[0];if(['discovery.html','compare.html','admissions.html','notices.html','desk.html','applications.html'].includes(path))a.href=path+'?'+publicScope();}el('compare-selection').hidden=!compareSelection.length;el('compare-count').textContent=`已选 ${compareSelection.length} 位导师`;el('compare-open').hidden=!compareSelection.length;el('compare-open').href='compare.html?'+publicScope();el('compare-open').textContent=compareSelection.length===1?'查看已选导师':'查看对比';}
function render(){
  renderProjectCreate();
  renderSelection();
  el('discovery-count').textContent=`${view.length} 位候选 · 当前显示 ${Math.min(limit,view.length)} 位`;
  const schoolNames=applied.schools.map(id=>DATA.find(p=>p.school===id)?.school_name||id);
  const ruleLabels={research:'研究关键词',qualification:'导师资格',email:'公开邮箱',opportunity:'招生机会',eligibility:'申请资格'},modeLabels={hard:'必须',soft:'偏好',off:'不限制'};
  const rules=MODES.map(key=>`${ruleLabels[key]}：${protectedReview()&&['opportunity','eligibility'].includes(key)?'待核实（项目范围暂不应用规则）':modeLabels[applied.modes[key]]}`).join('；');
  const unknownPolicy=applied.keep_unknown?'保留必须条件待核实的候选':'不保留必须条件待核实的候选';
  el('intent-overview').textContent=`${appliedName?'姓名：'+appliedName:'姓名不限'} · ${applied.topics.length?applied.topics.join('、'):'研究关键词不限'} · ${schoolNames.length?schoolNames.join('、'):'学校不限'}${contextDept?' / '+(DATA.find(p=>p.school===contextSchool&&p.dept===contextDept)?.dept_name||contextDept):''} · ${appliedGroup.label} · ${applied.year??'年度未定'} / ${degreeLabels[applied.degree]} / ${routeLabels[applied.route]}`;
  const hardRules=MODES.filter(key=>applied.modes[key]==='hard'&&(key!=='research'||applied.topics.length)&&(key!=='qualification'||applied.degree!=='any')&&!(protectedReview()&&['opportunity','eligibility'].includes(key))).map(key=>ruleLabels[key]);
  el('criteria-explanation-label').textContent=`筛选规则与说明 · 必须：${hardRules.join('、')||'无'} · ${applied.keep_unknown?'保留待核实':'排除必须条件待核实'}`;
  el('candidate-order').textContent=(matchingOrder?'优先符合已设条件，同分时资料更全者优先、同组随机展示。':'资料更全者优先，同组随机展示；本次浏览顺序保持稳定。')+' 资料完整度依据研究方向、有效邮箱、简介与官网资料链接。';
  el('intent-summary').textContent=`姓名：${appliedName||'不限'}（与其他条件取交集） · 研究：${applied.topics.length?applied.topics.join('、'):'关键词不限'} · 学校：${schoolNames.length?schoolNames.join('、'):'不限'} · 院系方向：${appliedGroup.label}。申请目标：${applied.year??'年度未知'} · ${degreeLabels[applied.degree]} · ${routeLabels[applied.route]}。规则：${rules}。${unknownPolicy}。${protectedReview()?'本项目的招生机会与申请资格不据此排除候选，也不借用旧结论排序。':''}${matchingOrder?'先按已命中规则数量排序。':''}资料完整度按研究方向、有效邮箱、简介与官网资料链接的已有项数分层。同组随机排序保持稳定，不表示招生名额、适合程度或录取概率；有日期不等于信息已更新。`;
  el('candidate-list').innerHTML=view.slice(0,limit).map(({p,result})=>{
    const extra=window.MENTOR_COMPARE?.[p.page]||{},prov=extra.provenance||{};
    const policyGoal=publicScope(p),goal=publicScope(p);goal.set('mentor',p.page);if(selectedProject&&matchesCurrent()&&p.school===currentProject().goal_snapshot.school_id&&p.dept===currentProject().goal_snapshot.dept_id)goal.set('project',selectedProject);
    const detailUrl='p/'+encodeURIComponent(p.page)+'.html?'+publicScope(p);
    const proof=field=>{
      const source=prov[field]?.source||p.detail_url||p.profile_url;
      const origin=prov[field]?.origin,dateLabel=origin==='manual'?'人工录入于 ':origin==='crawled'?'采集于 ':'记录于 ';
      return `${source&&/^https?:/.test(source)?`<a href="${esc(source)}" target="_blank" rel="noopener">官网来源</a>`:'官网来源未记录'} · ${prov[field]?.fetched_at?dateLabel+esc(prov[field].fetched_at):'采集日期未知'}`;
    };
    const scopeCleared=(contextTrack||contextProgram)&&(contextSchool!==p.school||contextDept!==p.dept);
    const direction=DiscoveryRules.researchText(window.MENTOR_COMPARE?.[p.page]?.research_direction_raw||p.research_direction_raw);
    const preview=direction||extra.bio_excerpt||'',previewField=direction?'research_direction_raw':'bio_raw';
    const shortPreview=preview.length>220?preview.slice(0,220)+'…':preview;
    const checks=result.checks.filter(c=>c.mode!=='off');
    return `<article class="results-card" data-candidate="${esc(p.page)}">
      <h2><a href="${esc(detailUrl)}">${esc(p.name)}</a></h2>
      <p class="badge">${esc(p.school_name)} · ${esc(p.dept_name)} · ${esc(p.title||'职称未知')}${p.supervisor?' · '+esc(p.supervisor):''}</p>
      <p class="research-preview">${preview?`<strong>${direction?'研究方向':'官网简介摘录'}</strong><br>${esc(shortPreview)}`:'资料待补充，可查看导师资料与官网。'}</p>
      <p class="preview-source note">${proof(previewField)}</p>
      ${DiscoveryRules.validEmail(p.email)?`<p class="public-email"><span class="muted">公开邮箱</span> ${esc(p.email)}</p>`:p.email?'<p class="public-email note">邮箱记录待核对，请查看官网联系方式。</p>':''}
      <div class="actions card-primary-actions"><a href="${esc(detailUrl)}">查看资料 →</a><button type="button" data-compare="${esc(p.page)}" aria-pressed="${compareSelection.includes(p.page)}">${compareSelection.includes(p.page)?'移出对比':'加入对比'}</button></div>
      <details class="candidate-proof"><summary>筛选依据与来源</summary>
        ${direction?`<div class="evidence">官网研究方向：${esc(direction)}<br>${proof('research_direction_raw')}</div>`:''}
        ${checks.length?`<ul class="checks">${checks.map(c=>`<li><strong>${esc(c.label)}${c.mode==='hard'?'（必须）':'（偏好）'}</strong> · ${{pass:'命中',fail:'未命中',unknown:'待核实'}[c.state]}<br>${esc(c.detail)}${c.key==='qualification'?`<br>${proof('supervisor')}`:c.key==='email'?`<br>${proof('email')}`:''}</li>`).join('')}</ul>`:'<p class="note">当前未启用筛选规则。</p>'}
        ${result.evidence.map(e=>`<div class="evidence">${e.field==='bio_raw'?'简介检索片段（已转小写）':'官网研究方向'}：${esc(e.snippet)}<br>${proof(e.field)}</div>`).join('')}
        ${result.review&&!selectedProject?`<p class="note">人工核验 ${esc(result.review.checked_at)}：${esc(result.review.quote)} ${/^https?:/.test(result.review.source_url)?`<a href="${esc(result.review.source_url)}" target="_blank" rel="noopener">核验来源</a>`:''}</p>`:''}
        ${selectedProject&&result.review?['opportunity','eligibility'].map(key=>{const proof=result.review[key+'_evidence'];return proof?`<div class="evidence">${key==='opportunity'?'招生机会':'本人资格'} · 我的核对依据 · ${esc(proof.scope)}<br>原文：${esc(proof.quote)}<br>${proof.kind==='official'?`<a target="_blank" rel="noopener noreferrer" href="${esc(proof.source_url)}">官方来源</a>`:'已登记收到的同项目导师回复'}</div>`:'';}).join(''):''}
      </details>
      <details class="candidate-application"><summary>联系与申请</summary>
        ${scopeCleared?'<p class="note">此导师不在原项目院系，继续时会清除原专业／专项范围，请重新核对招生要求。</p>':''}
        <p class="note">招生信息请到具体项目核对。</p>
        <div class="actions"><a href="desk.html?${esc(goal.toString())}">准备联系 →</a><a href="admissions.html?${esc(policyGoal.toString())}">学校与招生要求</a><a href="notices.html?${esc(policyGoal.toString())}">查招生通知</a><button data-review="${esc(p.page)}" ${API_OK&&(!projectScoped||PROJECT_API&&matchesCurrent()&&p.school===currentProject().goal_snapshot.school_id&&p.dept===currentProject().goal_snapshot.dept_id)?'':'disabled'}>我的核对记录</button></div>
      </details>
    </article>`;
  }).join('')||`<div class="empty">当前库或筛选暂无候选。姓名与研究关键词、学校及其他条件取交集；可清除姓名或研究关键词。也可以放宽必须条件、保留待核实记录，或修改研究关键词。文字未命中不代表真实研究不适合。${publicScope().has('school')&&publicScope().has('dept')?`<p><a id="empty-unit-official" href="admissions.html?${esc(publicScope().toString())}">查看院系与官方师资入口 →</a></p>`:''}</div>`;
  el('more-candidates').hidden=limit>=view.length;
}
el('filter-options').open=!matchMedia('(max-width:850px)').matches;
if(projectScoped)el('project-options').open=true;
el('criteria-form').onsubmit=e=>{e.preventDefault();apply().then(()=>{if(matchMedia('(max-width:850px)').matches)el('discovery-results').scrollIntoView({block:'start'});}).catch(e=>message(e.message,true));};
el('criteria-form').addEventListener('input',e=>{if(!['intent-group','school-search'].includes(e.target.id))el('criteria-dirty').hidden=false;});
el('criteria-form').addEventListener('change',e=>{if(!['intent-group','school-search'].includes(e.target.id))el('criteria-dirty').hidden=false;});
el('more-candidates').onclick=()=>{limit+=20;render();};
el('save-criteria').onclick=async()=>{try{PRIVATE.preferences=await api('',readCriteria(),'POST');await apply();message('私人条件已保存');}catch(e){message(e.message,true);}};
el('candidate-list').onclick=e=>{const cmp=e.target.closest('[data-compare]');if(cmp){const id=cmp.dataset.compare;if(compareSelection.includes(id))compareSelection=compareSelection.filter(x=>x!==id);else if(compareSelection.length<5)compareSelection.push(id);else{message('最多对比5位导师，请先移出一位');return;}try{localStorage.setItem('compare_sel',JSON.stringify(compareSelection));}catch(e){message('浏览器无法保存对比选择',true);return;}renderSelection();cmp.textContent=compareSelection.includes(id)?'移出对比':'加入对比';cmp.setAttribute('aria-pressed',compareSelection.includes(id));return;}const b=e.target.closest('[data-review]');if(!b)return;if(!discardReview())return;if(protectedReview()){message('请选择目标完整、与浏览条件一致的申请项目。',true);return;}if(readCriteria().year!==applied.year||readCriteria().degree!==applied.degree||readCriteria().route!==applied.route){message('申请目标已改变，请先重新查看候选',true);return;}
  if(!applied.year||applied.degree==='any'||applied.route==='unknown'){message('核验前请明确年度、学位和渠道，再查看候选',true);return;}
  reviewMentor=b.dataset.review;const row=view.find(r=>r.p.page===reviewMentor);reviewRevision++;el('review-form').reset();const old=row.result.review;reviewGoal=currentProject()?structuredClone(currentProject().goal_snapshot):null;el('generic-review-evidence').hidden=!!selectedProject;el('project-review-evidence').hidden=!selectedProject;
  el('review-scope').textContent=(currentProject()?currentProject().name+' · '+projectGoalText(currentProject())+' · ':'')+`${row.p.name} · ${applied.year} · ${degreeLabels[applied.degree]} · ${routeLabels[applied.route]}`;
  for(const key of ['opportunity','eligibility','source','quote'])el('review-'+key).value=old?.[key==='source'?'source_url':key]||(['source','quote'].includes(key)?'':'unknown');
  if(selectedProject)for(const key of ['opportunity','eligibility']){const proof=old?.[key+'_evidence'];el(key+'-evidence-kind').value=proof?.kind||'official';const replies=Object.values(PROJECTS.replies).filter(r=>r.project_id===selectedProject&&r.mentor_id===reviewMentor);el(key+'-evidence-reply').innerHTML='<option value="">选择已收到的回复（草稿不可用）</option>'+replies.map(r=>`<option value="${esc(r.id)}">${esc(r.date+' · '+r.subject)}</option>`).join('');el(key+'-evidence-reply').value=proof?.communication_id||'';for(const field of ['url','quote','scope'])el(key+'-evidence-'+field).value=proof?.[field==='url'?'source_url':field]||'';syncEvidence(key);}
  reviewDirty=false;el('review-save').disabled=savingReview||!API_OK;el('review-panel').hidden=false;el('review-panel').scrollIntoView({behavior:'smooth',block:'start'});
};
el('review-form').onsubmit=async e=>{e.preventDefault();if(savingReview)return;const savedRevision=reviewRevision,savedProject=selectedProject,savedMentor=reviewMentor;let postSucceeded=false;savingReview=true;el('review-save').disabled=true;try{
  if(protectedReview())throw new Error('目标不一致或不完整，请重新选择申请项目。');
  if(!applied||JSON.stringify(readCriteria())!==JSON.stringify(applied))throw new Error('条件已变，请重新查看候选并打开核验表单');
  if(selectedProject){
    const savingProject=selectedProject,savingMentor=reviewMentor;
    const evidence=key=>{if(el('review-'+key).value==='unknown')return null;const kind=el(key+'-evidence-kind').value;return {kind,...(kind==='reply'?{communication_id:el(key+'-evidence-reply').value}:{source_url:el(key+'-evidence-url').value}),quote:el(key+'-evidence-quote').value,scope:el(key+'-evidence-scope').value};};
    await api('/project-reviews',{project_id:selectedProject,mentor_id:reviewMentor,expected_goal:reviewGoal,opportunity:el('review-opportunity').value,eligibility:el('review-eligibility').value,opportunity_evidence:evidence('opportunity'),eligibility_evidence:evidence('eligibility'),confirmed:el('review-confirmed').checked},'POST');postSucceeded=true;
    if(selectedProject!==savingProject||reviewMentor!==savingMentor||reviewRevision!==savedRevision){await loadProjects();await apply(true,false);message('提交版本已保存；提交后新输入仍未保存，当前表单保持。');return;}
    closeReview();await loadProjects();await apply(true,false);message('我的核对记录已保存在本机，仅适用于此项目与目标。');return;
  }
  const entry=await api('/reviews' ,{mentor_id:reviewMentor,year:applied.year,degree:applied.degree,route:applied.route,
    opportunity:el('review-opportunity').value,eligibility:el('review-eligibility').value,source_url:el('review-source').value,quote:el('review-quote').value,confirmed:el('review-confirmed').checked},'POST');postSucceeded=true;
  PRIVATE.reviews[entry.id]=entry;if(reviewRevision!==savedRevision||selectedProject!==savedProject||reviewMentor!==savedMentor){await apply(true);message('提交版本已保存；提交后新输入仍未保存，当前表单保持。');return;}closeReview();await apply(true);message('人工核验已保存，仅适用于当前上下文');
}catch(e){if(postSucceeded){PROJECTS.project_reviews={};await apply(true,false);}message(postSucceeded?'已保存，刷新失败，请重新载入核对；当前输入保留。'+e.message:e.message+'；未保存。若项目目标已变更，请重新载入并核对。',true);}finally{savingReview=false;el('review-save').disabled=!API_OK;}};
async function download(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
el('discovery-backup').onclick=()=>api('/backup').then(d=>download(d,'discovery-backup.json')).catch(e=>message(e.message,true));
el('discovery-restore').onclick=()=>el('discovery-file').click();
el('discovery-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;if(!confirm('恢复将替换私人筛选条件与核验记录，服务会保留旧副本。继续？'))return;try{await api('/restore',JSON.parse(await file.text()),'POST');await initPrivate();await apply();message('条件与核验已恢复');}catch(e){message(e.message,true);}finally{e.target.value='';}};
async function initPrivate(){PRIVATE=await api();API_OK=true;fillCriteria(PRIVATE.preferences);for(const id of ['save-criteria','discovery-backup'])el(id).disabled=false;el('private-hint').textContent='筛选与核验记录仅保存在本机。';}
el('intent-schools').innerHTML=[...new Map(DATA.map(p=>[p.school,p.school_name])).entries()].sort((a,b)=>a[1].localeCompare(b[1],'zh')).map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
el('school-options').innerHTML=[...el('intent-schools').options].map(o=>`<label class="school-option"><input type="checkbox" value="${esc(o.value)}"> <span>${esc(o.textContent)}</span></label>`).join('');
el('school-options').onchange=e=>{if(e.target.matches('input[type=checkbox]'))changeSchool(e.target.value,e.target.checked);};
el('school-chips').onclick=e=>{const b=e.target.closest('[data-remove-school]');if(!b)return;const id=b.dataset.removeSchool;changeSchool(id,false);const box=el('school-options').querySelector('input[value="'+CSS.escape(id)+'"]');(box&&!box.parentElement.hidden?box:el('school-search')).focus();};
el('clear-schools').onclick=()=>{changeSchool(null,false);el('school-search').focus();};
el('select-visible-schools').onclick=()=>changeSchool([...el('school-options').children].filter(option=>!option.hidden).map(option=>option.querySelector('input').value),true);
el('clear-school-search').onclick=()=>{el('school-search').value='';el('school-search').dispatchEvent(new Event('input'));el('school-search').focus();};
el('school-search').oninput=()=>{const query=el('school-search').value.trim().toLowerCase();let count=0;for(const option of el('school-options').children){option.hidden=!option.textContent.toLowerCase().includes(query)&&!option.querySelector('input').value.toLowerCase().includes(query);if(!option.hidden)count++;}el('school-search-status').textContent=query?`找到 ${count} 所学校；已选学校保持不变。`:'';el('clear-school-search').hidden=!query;el('select-visible-schools').textContent=query?'选中搜索结果':'全选学校';syncSchoolPicker();};
el('school-search').onkeydown=e=>{if(e.key==='Enter')e.preventDefault();};
fillCriteria(PRIVATE.preferences);
function clearUnitContext(keepProject=false){
  contextSchool='';contextDept='';const q=new URLSearchParams(location.search);
  for(const key of ['school','dept','project','target','notes',...(keepProject?[]:['track','program'])])q.delete(key);
  history.replaceState(null,'',location.pathname+(q.size?'?'+q:''));el('unit-context').hidden=true;el('clear-unit-context').hidden=true;
  if(projectScoped){el('project-context').textContent=keepProject?'学校选择已改变，已退出原学校/院系范围；原专业／专项核验保护保留，招生机会与资格仍须对照对应项目原文核实。':'已清除院系及跨页项目范围；本页仍保留原核验保护，招生机会与资格不借用旧结论。刷新或继续导航后进入通用范围，请重新核对申请目标。';}
}
el('intent-schools').addEventListener('change',()=>{schoolSelectionChanged=true;syncSchoolPicker();const selected=readCriteria().schools;if(contextSchool&&(selected.length!==1||selected[0]!==contextSchool)){clearUnitContext(true);message('已退出原学校/院系范围；点击“查看候选”应用所选学校。'+(projectScoped?'原专业／专项核验保护保留。':''));}});
el('clear-unit-context').onclick=()=>{if(!schoolSelectionChanged)for(const o of el('intent-schools').options)o.selected=originalSchools.includes(o.value);syncSchoolPicker();clearUnitContext();if(projectScoped)message('院系范围已清除；本页保留核验保护，后续导航不沿用原专业／专项。');apply().catch(e=>message(e.message,true));};
el('intent-group').onchange=()=>apply().catch(e=>message(e.message,true));
function incomingCriteria(){
  if(incoming.has('topics'))el('intent-topics').value=incoming.get('topics').slice(0,200);
  if(projectScoped){el('project-context').textContent='当前临时范围：'+(contextTrack==='special'?'专项/特定项目':contextTrack==='ordinary'?'普通招生':'招生范围未指定')+' · '+(contextProgram?contextProgram.replace('|',' · '):'具体项目未指定')+'。核验尚未区分该项目，需对照原文。招生机会和个人申请资格保持待核实，不借用旧结论排序或排除候选，也暂不能保存旧核验记录。清除学校/院系不会退出此项目范围；保存或备份通用条件不包含此临时项目。';el('project-context').hidden=false;el('generic-context').hidden=false;el('project-filter-hint').textContent='本项目的招生机会和个人申请资格尚不能核验。这两项的存量设置暂不生效，即使取消保留待核实候选也不会据此排除；待核实不表示已经满足。其他筛选条件仍正常生效。';el('project-filter-hint').hidden=false;for(const id of ['mode-opportunity','mode-eligibility'])el(id).disabled=true;}

  if(incoming.has('group')){const value=incoming.get('group');if(!Array.from(el('intent-group').options).some(o=>o.value===value))el('intent-group').add(new Option(value+'（未知）',value));el('intent-group').value=value;}
  originalSchools=[...el('intent-schools').selectedOptions].map(o=>o.value);
  if(contextSchool){for(const o of el('intent-schools').options)o.selected=o.value===contextSchool;}
  syncSchoolPicker();
  const year=Number(incoming.get('year'));if(Number.isInteger(year)&&year>=2000&&year<=2100)el('intent-year').value=year;
  if(['master','phd'].includes(incoming.get('degree')))el('intent-degree').value=incoming.get('degree');
  if(['recommend','exam','assessment'].includes(incoming.get('route')))el('intent-route').value=incoming.get('route');
  if(contextSchool||contextDept){
    const p=DATA.find(p=>p.school===contextSchool&&(!contextDept||p.dept===contextDept)),u=window.ADMISSIONS_DATA?.units.find(u=>u.school===contextSchool&&u.dept===contextDept);
    const label=u?u.school_name+' · '+u.dept_name+'；'+(u.roster_pending||'当前导师库暂无该单位记录，师资信息待核对'):p?p.school_name+' · '+(contextDept?p.dept_name:'全校'):'当前导师库暂无该单位记录'+(!window.ADMISSIONS_DATA?'；公开院系目录未能载入，接入状态待核对':'；院系范围仍须核对官方信息');
    const q=new URLSearchParams();for(const key of ['school','dept','year','degree','route','track','program'])if(incoming.get(key))q.set(key,incoming.get(key));
    const rosterLink=!p&&u?.roster_url&&/^https?:\/\//.test(u.roster_url)?' · <a id="unit-roster-direct" href="'+esc(u.roster_url)+'" target="_blank" rel="noopener">查看学院官方师资名录 →</a>':'';
    el('unit-context').innerHTML='来自学校政策的院系范围：'+esc(label)+'。此临时范围不保存到私人条件。'+(!p?' <a href="admissions.html?'+esc(q.toString())+'">回查院系招生要求与官方入口 →</a>':'')+rosterLink;el('unit-context').hidden=false;el('clear-unit-context').hidden=false;
  }
}
(async()=>{if(location.protocol==='http:'){el('discovery-restore').disabled=false;try{await initPrivate();}catch(e){message('无法读取私人条件，可继续筛选或恢复备份：'+e.message,true);}}await loadUnitCatalog();incomingCriteria();if(API_OK){try{await loadProjects();const id=incoming.get('project');if(id&&PROJECTS.projects[id])selectProject(id);else if(id){selectedProject=id;projectScoped=true;message('申请项目不存在或不可读取，未应用任何项目核对。',true);}}catch(e){if(incoming.has('project')){projectScoped=true;selectedProject=incoming.get('project');}el('review-project-api').textContent='本机服务不可用，仍可浏览；未保存任何核对：'+e.message;}}renderProject();await apply();window.DISCOVERY_READY=true;})().catch(e=>message(e.message,true));

function syncEvidence(key){const reply=el(key+'-evidence-kind').value==='reply';el(key+'-evidence-url').parentElement.hidden=reply;el(key+'-evidence-reply').parentElement.hidden=!reply;}
for(const key of ['opportunity','eligibility'])el(key+'-evidence-kind').onchange=()=>syncEvidence(key);
el('review-form').addEventListener('input',()=>{reviewDirty=true;reviewRevision++;});
el('review-form').addEventListener('change',()=>{reviewDirty=true;reviewRevision++;});
el('review-form').addEventListener('reset',()=>reviewRevision++);
el('review-project').onchange=async()=>{const id=el('review-project').value;if(!discardReview()){el('review-project').value=selectedProject;return;}selectProject(id);await apply();};
window.addEventListener('beforeunload',e=>{if(reviewDirty){e.preventDefault();e.returnValue='';}});
for(const id of ['intent-year','intent-degree','intent-route','intent-schools'])el(id).addEventListener('change',()=>{if(selectedProject){closeReview();renderProject();apply().catch(e=>message(e.message,true));}});
el('criteria-form').addEventListener('change',e=>{if(['intent-year','intent-degree','intent-route','intent-schools'].includes(e.target.id)&&reviewDirty){if(!discardReview()){fillCriteria(applied);e.stopImmediatePropagation();e.preventDefault();return;}closeReview();}},true);
async function refreshProjectStatus(){if(!PROJECT_API)return;try{await loadProjects();await apply(true,false);if(reviewDirty)message('已刷新项目状态；未保存输入保留。目标或依据有变化时请重开表单核对后保存。');}catch(e){PROJECTS.project_reviews={};await apply(true,false);message('项目核对刷新失败，判断已撤下；未保存输入保留。',true);}}
window.addEventListener('focus',refreshProjectStatus);
window.addEventListener('pageshow',e=>{if(e.persisted)refreshProjectStatus();});
el('review-project-confirm').onclick=async()=>{if(!discardReview())return;const id=selectedProject;try{await loadProjects();if(selectedProject!==id)return;selectProject(id);await apply();}catch(e){message('无法载入最新项目目标：'+e.message,true);}};
el('review-cancel').onclick=()=>{if(!discardReview())return;closeReview();el('discovery-results').scrollIntoView({block:'start'});};

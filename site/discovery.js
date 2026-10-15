const el=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DATA=window.MENTOR_DATA,MODES=['research','qualification','email','opportunity','eligibility'];
const incoming=new URLSearchParams(location.search);
const contextTrack=incoming.get('track')||'',contextProgram=incoming.get('program')||'',projectScoped=DiscoveryRules.projectScoped({track:contextTrack,program:contextProgram});
let contextSchool=incoming.get('school')||'',contextDept=incoming.get('dept')||'';
let PRIVATE={preferences:{year:null,degree:'any',route:'unknown',topics:[],schools:[],keep_unknown:true,modes:{research:'hard',qualification:'soft',email:'soft',opportunity:'soft',eligibility:'soft'}},reviews:{}},API_OK=false,view=[],limit=20,reviewMentor='',applied=null,appliedGroup={value:'',label:'全部'};
const degreeLabels={any:'学位未确定',master:'硕士',phd:'博士'},routeLabels={unknown:'渠道未确定',recommend:'推免',exam:'统考',assessment:'申请考核'};
function message(text,error=false){el('discovery-message').textContent=text;el('discovery-message').classList.toggle('error',error);}
function readCriteria(){return {year:el('intent-year').value?Number(el('intent-year').value):null,degree:el('intent-degree').value,route:el('intent-route').value,
  topics:[...new Set(el('intent-topics').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean))],schools:[...el('intent-schools').selectedOptions].map(o=>o.value),keep_unknown:el('keep-unknown').checked,modes:Object.fromEntries(MODES.map(k=>[k,el('mode-'+k).value]))};}
function fillCriteria(p){el('intent-year').value=p.year??'';el('intent-degree').value=p.degree;el('intent-route').value=p.route;el('intent-topics').value=p.topics.join(', ');el('keep-unknown').checked=p.keep_unknown;for(const o of el('intent-schools').options)o.selected=p.schools.includes(o.value);for(const k of MODES)el('mode-'+k).value=p.modes[k];}
async function api(path='',body,method='GET'){const r=await fetch('/api/discovery'+path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});const d=await r.json();if(!r.ok)throw new Error(d.error||r.status);return d;}
const lazy=new Map();
function script(file){if(!lazy.has(file))lazy.set(file,new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=file+'?v=20261015-8';s.onload=resolve;s.onerror=()=>{lazy.delete(file);s.remove();reject(new Error('无法加载 '+file+'，请确认静态文件完整'));};document.head.appendChild(s);}));return lazy.get(file);}
async function apply(){
  const prefs=readCriteria(),group={value:el('intent-group').value,label:el('intent-group').selectedOptions[0].textContent};if(prefs.year!==null&&(!Number.isInteger(prefs.year)||prefs.year<2000||prefs.year>2100))throw new Error('请填写有效年度');
  el('review-panel').hidden=true;reviewMentor='';
  el('apply-criteria').disabled=true;
  try{if(prefs.topics.length&&!window.MENTOR_SEARCH)await script('search.js');if(!window.MENTOR_COMPARE)await script('compare-data.js');
    applied=prefs;appliedGroup=group;el('criteria-dirty').hidden=true;limit=20;view=DATA.map(p=>({p,result:DiscoveryRules.evaluate(p,{...prefs,track:contextTrack,program:contextProgram},PRIVATE.reviews,window.MENTOR_SEARCH?.[p.page]||'')})).filter(row=>row.result.visible&&(!group.value||row.p.unit_groups?.includes(group.value))&&(!contextSchool||row.p.school===contextSchool)&&(!contextDept||row.p.dept===contextDept)).sort((a,b)=>b.result.score-a.result.score||a.result.unknown-b.result.unknown);render();
  }finally{el('apply-criteria').disabled=false;}
}
let compareSelection=[];
try{compareSelection=[...new Set(JSON.parse(localStorage.getItem('compare_sel')||'[]'))].filter(id=>DATA.some(p=>p.page===id)).slice(0,5);}catch(e){}
function renderSelection(){el('compare-selection').hidden=!compareSelection.length;el('compare-count').textContent=`已选 ${compareSelection.length} 位导师`;el('compare-open').hidden=compareSelection.length<2;}
function render(){
  renderSelection();
  el('discovery-count').textContent=`${view.length} 位候选 · 当前显示 ${Math.min(limit,view.length)} 位`;
  const schoolNames=applied.schools.map(id=>DATA.find(p=>p.school===id)?.school_name||id);
  const ruleLabels={research:'研究关键词',qualification:'导师资格',email:'公开邮箱',opportunity:'招生机会',eligibility:'申请资格'},modeLabels={hard:'必须',soft:'偏好',off:'不限制'};
  const rules=MODES.map(key=>`${ruleLabels[key]}：${projectScoped&&['opportunity','eligibility'].includes(key)?'待核实（项目范围暂不应用规则）':modeLabels[applied.modes[key]]}`).join('；');
  const unknownPolicy=applied.keep_unknown?'保留必须条件待核实的候选':'不保留必须条件待核实的候选';
  el('intent-summary').textContent=`研究：${applied.topics.length?applied.topics.join('、'):'关键词不限'} · 学校：${schoolNames.length?schoolNames.join('、'):'不限'} · 院系方向：${appliedGroup.label}。申请目标：${applied.year??'年度未知'} · ${degreeLabels[applied.degree]} · ${routeLabels[applied.route]}。规则：${rules}。${unknownPolicy}。${projectScoped?'本项目的招生机会与申请资格不据此排除候选，也不借用旧结论排序。':''}按已命中规则数量排序，不表示录取概率。`;
  el('candidate-list').innerHTML=view.slice(0,limit).map(({p,result})=>{
    const prov=window.MENTOR_COMPARE?.[p.page]?.provenance||{};
    const proof=field=>prov[field]?.source&&/^https?:/.test(prov[field].source)?`<a href="${esc(prov[field].source)}" target="_blank" rel="noopener">字段出处</a> · ${esc(prov[field].fetched_at)}`:`<a href="p/${encodeURIComponent(p.page)}.html">查看官网资料</a>`;
    const policyGoal=new URLSearchParams({school:p.school,dept:p.dept});for(const key of ['year','degree','route'])if(applied[key]&&applied[key]!=='any'&&applied[key]!=='unknown')policyGoal.set(key,applied[key]);if(contextTrack)policyGoal.set('track',contextTrack);if(contextProgram)policyGoal.set('program',contextProgram);
    const goal=new URLSearchParams({mentor:p.page,school:p.school,dept:p.dept});if(contextTrack)goal.set('track',contextTrack);if(contextProgram)goal.set('program',contextProgram);if(applied.year)goal.set('year',applied.year);if(applied.degree!=='any')goal.set('degree',applied.degree);if(applied.route!=='unknown')goal.set('route',applied.route);
    const direction=window.MENTOR_COMPARE?.[p.page]?.research_direction_raw||p.research_direction_raw||'';
    const shortDirection=direction.length>220?direction.slice(0,220)+'…':direction;
    return `<article class="results-card" data-candidate="${esc(p.page)}"><h2><a href="p/${encodeURIComponent(p.page)}.html">${esc(p.name)}</a></h2><span class="badge">${esc(p.school_name)} · ${esc(p.dept_name)} · ${esc(p.title||'职称未知')}</span><p class="research-preview"><strong>研究方向</strong> · ${direction?esc(shortDirection):'暂未整理明确研究方向，可查看官网'}</p><div class="compact-checks"><span class="state">${esc(p.supervisor||'导师资格待查')}</span>${result.checks.some(c=>c.key==='email'&&c.mode!=='off')?'':`<span class="state">${p.email?'有公开邮箱':'邮箱待查'}</span>`}${result.checks.filter(c=>c.mode!=='off').map(c=>`<span class="state ${c.state}">${esc(c.label)}：${{pass:'命中',fail:'未命中',unknown:'待核实'}[c.state]}</span>`).join('')}</div><details class="candidate-proof"><summary>匹配依据与官方出处</summary>${direction?`<div class="evidence">官网研究方向：${esc(direction)}<br>${proof('research_direction_raw')}</div>`:''}<ul class="checks">${result.checks.filter(c=>c.mode!=='off').map(c=>`<li><span class="state ${c.state}">${{pass:'命中',fail:'未命中',unknown:'待核实'}[c.state]}</span>${esc(c.label)}${c.mode==='hard'?'（必须）':'（偏好）'}：${esc(c.detail)}${c.key==='qualification'?` · ${proof('supervisor')}`:c.key==='email'?` · ${proof('email')}`:''}</li>`).join('')}</ul>${result.evidence.map(e=>`<div class="evidence">${e.field==='bio_raw'?'简介检索片段（已转小写）':'官网研究方向'}：${esc(e.snippet)}<br>${proof(e.field)}</div>`).join('')}${result.review?`<p class="note">人工核验 ${esc(result.review.checked_at)}：${esc(result.review.quote)} ${/^https?:/.test(result.review.source_url)?`<a href="${esc(result.review.source_url)}" target="_blank" rel="noopener">核验来源</a>`:''}</p>`:''}</details><div class="actions"><a href="desk.html?${esc(goal.toString())}">准备联系 →</a><a href="p/${encodeURIComponent(p.page)}.html">完整资料</a><a href="admissions.html?${esc(policyGoal.toString())}">学校与招生要求</a><a href="notices.html?${esc(policyGoal.toString())}">查招生通知</a><button type="button" data-compare="${esc(p.page)}" aria-pressed="${compareSelection.includes(p.page)}">${compareSelection.includes(p.page)?'移出对比':'加入对比'}</button><button data-review="${esc(p.page)}" ${API_OK&&!projectScoped?'':'disabled'}>核验申请机会</button></div></article>`;
  }).join('')||'<div class="empty">暂无候选。可以放宽必须条件、保留待核实记录，或修改研究关键词。文字未命中不代表真实研究不适合。</div>';
  el('more-candidates').hidden=limit>=view.length;
}
el('criteria-form').onsubmit=e=>{e.preventDefault();apply().then(()=>{if(matchMedia('(max-width:850px)').matches)el('discovery-results').scrollIntoView({block:'start'});}).catch(e=>message(e.message,true));};
el('criteria-form').addEventListener('input',e=>{if(e.target.id!=='intent-group')el('criteria-dirty').hidden=false;});
el('criteria-form').addEventListener('change',e=>{if(e.target.id!=='intent-group')el('criteria-dirty').hidden=false;});
el('more-candidates').onclick=()=>{limit+=20;render();};
el('save-criteria').onclick=async()=>{try{PRIVATE.preferences=await api('',readCriteria(),'POST');await apply();message('私人条件已保存');}catch(e){message(e.message,true);}};
el('candidate-list').onclick=e=>{const cmp=e.target.closest('[data-compare]');if(cmp){const id=cmp.dataset.compare;if(compareSelection.includes(id))compareSelection=compareSelection.filter(x=>x!==id);else if(compareSelection.length<5)compareSelection.push(id);else{message('最多对比5位导师，请先移出一位');return;}try{localStorage.setItem('compare_sel',JSON.stringify(compareSelection));}catch(e){message('浏览器无法保存对比选择',true);return;}renderSelection();cmp.textContent=compareSelection.includes(id)?'移出对比':'加入对比';cmp.setAttribute('aria-pressed',compareSelection.includes(id));return;}const b=e.target.closest('[data-review]');if(!b)return;if(projectScoped){message('核验尚未区分该项目，需对照原文；请返回学校与招生要求核对。',true);return;}if(readCriteria().year!==applied.year||readCriteria().degree!==applied.degree||readCriteria().route!==applied.route){message('申请目标已改变，请先重新查看候选',true);return;}
  if(!applied.year||applied.degree==='any'||applied.route==='unknown'){message('核验前请明确年度、学位和渠道，再查看候选',true);return;}
  reviewMentor=b.dataset.review;const row=view.find(r=>r.p.page===reviewMentor);el('review-form').reset();const old=row.result.review;
  el('review-scope').textContent=`${row.p.name} · ${applied.year} · ${degreeLabels[applied.degree]} · ${routeLabels[applied.route]}`;
  for(const key of ['opportunity','eligibility','source','quote'])el('review-'+key).value=old?.[key==='source'?'source_url':key]||(['source','quote'].includes(key)?'':'unknown');
  el('review-panel').hidden=false;el('review-panel').scrollIntoView({behavior:'smooth',block:'start'});
};
el('review-form').onsubmit=async e=>{e.preventDefault();try{
  if(projectScoped)throw new Error('核验尚未区分该项目，需对照原文；该范围暂不能保存旧核验记录。');
  if(!applied||JSON.stringify(readCriteria())!==JSON.stringify(applied))throw new Error('条件已变，请重新查看候选并打开核验表单');
  const entry=await api('/reviews',{mentor_id:reviewMentor,year:applied.year,degree:applied.degree,route:applied.route,
    opportunity:el('review-opportunity').value,eligibility:el('review-eligibility').value,source_url:el('review-source').value,quote:el('review-quote').value,confirmed:el('review-confirmed').checked},'POST');
  PRIVATE.reviews[entry.id]=entry;await apply();el('review-panel').hidden=true;message('人工核验已保存，仅适用于当前上下文');
}catch(e){message(e.message,true);}};
async function download(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
el('discovery-backup').onclick=()=>api('/backup').then(d=>download(d,'discovery-backup.json')).catch(e=>message(e.message,true));
el('discovery-restore').onclick=()=>el('discovery-file').click();
el('discovery-file').onchange=async e=>{const file=e.target.files[0];if(!file)return;if(!confirm('恢复将替换私人筛选条件与核验记录，服务会保留旧副本。继续？'))return;try{await api('/restore',JSON.parse(await file.text()),'POST');await initPrivate();await apply();message('条件与核验已恢复');}catch(e){message(e.message,true);}finally{e.target.value='';}};
async function initPrivate(){PRIVATE=await api();API_OK=true;fillCriteria(PRIVATE.preferences);for(const id of ['save-criteria','review-save','discovery-backup'])el(id).disabled=id==='review-save'&&projectScoped;el('private-hint').textContent='筛选与核验记录仅保存在本机。';}
el('intent-schools').innerHTML=[...new Map(DATA.map(p=>[p.school,p.school_name])).entries()].sort((a,b)=>a[1].localeCompare(b[1],'zh')).map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
fillCriteria(PRIVATE.preferences);
el('clear-unit-context').onclick=()=>{contextSchool='';contextDept='';el('unit-context').hidden=true;el('clear-unit-context').hidden=true;apply().catch(e=>message(e.message,true));};
el('intent-group').onchange=()=>apply().catch(e=>message(e.message,true));
function incomingCriteria(){
  if(projectScoped){el('project-context').textContent='当前临时范围：'+(contextTrack==='special'?'专项/特定项目':contextTrack==='ordinary'?'普通招生':'招生范围未指定')+' · '+(contextProgram?contextProgram.replace('|',' · '):'具体项目未指定')+'。核验尚未区分该项目，需对照原文。招生机会和个人申请资格保持待核实，不借用旧结论排序或排除候选，也暂不能保存旧核验记录。清除学校/院系不会退出此项目范围；保存或备份通用条件不包含此临时项目。';el('project-context').hidden=false;el('generic-context').hidden=false;el('project-filter-hint').textContent='本项目的招生机会和个人申请资格尚不能核验。这两项的存量设置暂不生效，即使取消保留待核实候选也不会据此排除；待核实不表示已经满足。其他筛选条件仍正常生效。';el('project-filter-hint').hidden=false;for(const id of ['mode-opportunity','mode-eligibility'])el(id).disabled=true;}

  if(incoming.has('group')){const value=incoming.get('group');if(!Array.from(el('intent-group').options).some(o=>o.value===value))el('intent-group').add(new Option(value+'（未知）',value));el('intent-group').value=value;}
  if(contextSchool){for(const o of el('intent-schools').options)o.selected=o.value===contextSchool;}
  const year=Number(incoming.get('year'));if(Number.isInteger(year)&&year>=2000&&year<=2100)el('intent-year').value=year;
  if(['master','phd'].includes(incoming.get('degree')))el('intent-degree').value=incoming.get('degree');
  if(['recommend','exam','assessment'].includes(incoming.get('route')))el('intent-route').value=incoming.get('route');
  if(contextSchool||contextDept){const p=DATA.find(p=>p.school===contextSchool&&(!contextDept||p.dept===contextDept));el('unit-context').textContent='来自学校政策的院系范围：'+(p?p.school_name+' · '+(contextDept?p.dept_name:'全校'):'未收录，暂无对应导师')+'。此临时范围不保存到私人条件。';el('unit-context').hidden=false;el('clear-unit-context').hidden=false;}
}
(async()=>{if(location.protocol==='http:'){el('discovery-restore').disabled=false;try{await initPrivate();}catch(e){message('无法读取私人条件，可继续筛选或恢复备份：'+e.message,true);}}incomingCriteria();await apply();window.DISCOVERY_READY=true;})().catch(e=>message(e.message,true));

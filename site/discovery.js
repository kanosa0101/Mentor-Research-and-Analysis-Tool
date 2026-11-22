const el=id=>document.getElementById(id),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const R=DiscoveryRules,incoming=new URLSearchParams(location.search),titleLabels={professor:'教授',associate_professor:'副教授',assistant_professor:'助理教授',lecturer:'讲师',researcher:'研究员',associate_researcher:'副研究员',assistant_researcher:'助理研究员',other:'其他职称',unknown:'未明确'},qualificationLabels={phd:'博导',master:'硕导'};
const batchSize=4;
let DATA=window.MENTOR_DATA||[],fullLoaded=!!window.MENTOR_DATA,publicAvailable=true,view=[],total=0,missingEmail=0,batchOffset=0,localRows=null,revision='',query='',serial=0,applied=null;
let contextSchool=incoming.get('school')||'',contextDept=incoming.get('dept')||'',appliedScope=null;
const viewKey='mentor-directory-v2:'+location.search;
const orderSeed=(()=>{try{let seed=sessionStorage.getItem('discovery-order-seed');if(!seed){seed=crypto.randomUUID();sessionStorage.setItem('discovery-order-seed',seed);}return seed;}catch(e){return String(Date.now());}})();
let returnAnchor='';
let compareSelection=[];try{compareSelection=[...new Set(JSON.parse(localStorage.getItem('compare_sel')||'[]'))].filter(id=>typeof id==='string'&&id.length<=256&&!/[\\/\u0000-\u001f]/.test(id)&&!id.includes('..')).slice(0,5);}catch(e){}
const catalogUnit=(s,d)=>window.SCHOOL_CATALOG?.units.find(u=>u.school===s&&u.dept===d);
const schoolName=id=>window.SCHOOL_CATALOG?.schools.find(s=>s.id===id)?.name||id;
function message(text,error=false){el('discovery-message').textContent=text;el('discovery-message').classList.toggle('error',error);}
function batchMessage(text,error=false){el('batch-status').textContent=text;el('batch-status').classList.toggle('error',error);}
function criteriaDirty(dirty=!applied||query!==publicQuery(readCriteria())){el('criteria-dirty').hidden=!dirty;el('filter-draft-status').hidden=!dirty;}
function checked(id){return [...el(id).querySelectorAll('input:checked')].map(x=>x.value);}
function readCriteria(){return {name:el('intent-name').value.trim(),topics:[...new Set(el('intent-topics').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean))],schools:checked('school-options'),qualifications:checked('qualification-options'),titles:checked('title-options'),group:el('intent-group').value,include_missing_email:el('include-missing-email').checked};}
function fillCriteria(p){el('intent-name').value=p.name||'';el('intent-topics').value=(p.topics||[]).join('，');for(const [id,key] of [['school-options','schools'],['qualification-options','qualifications'],['title-options','titles']])for(const box of el(id).querySelectorAll('input'))box.checked=(p[key]||[]).includes(box.value);el('intent-group').value=p.group||'';el('include-missing-email').checked=!!p.include_missing_email;syncFilters();}
function syncFilters(){const p=readCriteria();el('school-chips').innerHTML=p.schools.map(id=>`<button type="button" data-remove-school="${esc(id)}" aria-label="移除${esc(schoolName(id))}">${esc(schoolName(id))} ×</button>`).join('');el('filter-options-label').textContent=p.schools.length?'学校 · 已选 '+p.schools.length+' 所':'学校 · 不限';el('school-selected-count').textContent=p.schools.length?'已选 '+p.schools.length+' 所':'不限学校';el('clear-schools').disabled=!p.schools.length;const parts=[p.titles.length&&p.titles.map(x=>titleLabels[x]).join('、'),p.group&&el('intent-group').selectedOptions[0].textContent,p.include_missing_email&&'包含缺邮箱资料'].filter(Boolean);el('advanced-criteria-label').textContent='更多筛选'+(parts.length?' · '+parts.join(' / '):'');}
function scope(p){const q=new URLSearchParams();for(const k of ['year','degree','route'])if(incoming.get(k))q.set(k,incoming.get(k));const school=p?.school||(appliedScope?appliedScope.school:contextSchool)||(applied?.schools.length===1?applied.schools[0]:'');if(school)q.set('school',school);const dept=p?.dept||(appliedScope?appliedScope.dept:contextDept);if(dept)q.set('dept',dept);if(school===incoming.get('school')&&dept===(incoming.get('dept')||''))for(const k of ['track','program'])if(incoming.get(k))q.set(k,incoming.get(k));return q;}
function renderContext(){
  const unit=catalogUnit(contextSchool,contextDept);
  el('unit-context').hidden=!contextDept;
  el('clear-unit-context').hidden=!contextDept;
  el('unit-context').textContent=contextDept?'当前院系：'+schoolName(contextSchool)+' · '+(unit?.dept_name||contextDept):'';
  const goalKeys=['year','degree','route','track','program'];
  const project=incoming.get('project');
  const applicationScope=new URLSearchParams();
  if(project)applicationScope.set('project',project);
  else for(const key of ['school','dept',...goalKeys])if(incoming.get(key))applicationScope.set(key,incoming.get(key));
  const policyScope=scope();
  const applicationHref='applications.html'+(applicationScope.size?'?'+applicationScope:'');
  el('application-context').hidden=!project&&!goalKeys.some(key=>incoming.get(key));
  el('application-context-link').href=applicationHref;
  for(const link of document.querySelectorAll('.site-header nav a[href]')){
    const path=link.getAttribute('href').split('?')[0];
    if(path==='admissions.html')link.href=path+(policyScope.size?'?'+policyScope:'');
    if(path==='applications.html')link.href=applicationHref;
  }
}
function saveView(){if(!applied)return;try{sessionStorage.setItem(viewKey,JSON.stringify({criteria:applied,contextSchool:appliedScope?.school||'',contextDept:appliedScope?.dept||'',offset:batchOffset,revision,scroll:scrollY,anchor:returnAnchor}));}catch(e){}}
let restore=null;try{restore=JSON.parse(sessionStorage.getItem(viewKey)||'null');}catch(e){}
const lazy=new Map();function script(file){if(!lazy.has(file))lazy.set(file,new Promise((resolve,reject)=>{const s=document.createElement('script'),timer=setTimeout(()=>fail('筛选资料读取超时，请重试'),8000);function fail(message){clearTimeout(timer);lazy.delete(file);s.remove();reject(new Error(message));}s.src=file+'?v=directory-v2';s.onload=()=>{clearTimeout(timer);resolve();};s.onerror=()=>fail('无法加载筛选资料，请稍后重试');document.head.appendChild(s);}));return lazy.get(file);}
async function fullCatalog(){if(fullLoaded)return;await script('discovery-data.js');DATA=window.MENTOR_DATA||[];fullLoaded=true;}
async function corpusFor(p){if(!p.topics.length)return {};try{const q=new URLSearchParams({terms:JSON.stringify(p.topics)});for(const school of p.schools)q.append('school',school);const {response,data}=await OnlineAccount.readJSON('/api/mentor-search?'+q);if(!response.ok)throw new Error();return data.matches;}catch(e){if(e.timedOut)throw e;}await script('search.js');return window.MENTOR_SEARCH||{};}
function publicQuery(p){const q=new URLSearchParams({name:p.name,topics:JSON.stringify(p.topics),group:p.group,include_missing_email:p.include_missing_email?'1':'0',seed:orderSeed});for(const key of ['schools','qualifications','titles'])for(const value of p[key])q.append(key==='schools'?'school':key,value);if(contextSchool)q.set('context_school',contextSchool);if(contextDept)q.set('dept',contextDept);return q.toString();}
async function fetchPage(q,offset){const {response,data:result}=await OnlineAccount.readJSON('/api/mentor-candidates?'+q+'&offset='+offset+'&limit='+batchSize);if(response.status===400){throw Object.assign(new Error(result.error||'请检查筛选条件'),{invalidCriteria:true});}if(!response.ok)throw new Error('候选服务暂不可用');if(result.version!==2||!Array.isArray(result.rows)||result.rows.length>batchSize||!Number.isInteger(result.total)||typeof result.revision!=='string')throw new Error('候选服务版本尚未更新');return result;}
async function fetchBatch(q,offset,previousRevision){
  let result=await fetchPage(q,offset);
  if(offset&&(result.revision!==previousRevision||offset>=result.total)){
    offset=0;
    result=await fetchPage(q,offset);
  }
  const remaining=batchSize-result.rows.length;
  if(offset&&remaining>0){
    const first=await fetchPage(q,0);
    if(first.revision!==result.revision)return {...first,offset:0};
    result.rows=result.rows.concat(first.rows.slice(0,remaining));
  }
  return {...result,offset};
}
function localBatch(rows,offset){
  const batch=rows.slice(offset,offset+batchSize);
  return offset?batch.concat(rows.slice(0,batchSize-batch.length)):batch;
}
function setPublicBatch(result){
  view=result.rows.map(x=>x.p);
  total=result.total;
  missingEmail=result.missing_email||0;
  revision=result.revision;
  batchOffset=result.offset;
}
function validate(p){if(p.name.length>100||p.topics.length>20||p.topics.some(x=>x.length>100)||p.topics.join('').length>1000)throw new Error('姓名最多100字，研究词最多20个且合计不超过1000字。');}
async function apply(saved=null){
  const request=++serial,p=readCriteria(),nextScope={school:contextSchool,dept:contextDept};
  const nextQuery=publicQuery(p),savedOffset=Number.isInteger(saved?.offset)&&saved.offset>=0?saved.offset:0;
  const more=el('more-candidates');
  el('apply-criteria').disabled=true;
  more.disabled=true;
  more.removeAttribute('aria-disabled');
  batchMessage('');
  try{
    validate(p);
    let result,wasFallback=false;
    if(publicAvailable)try{
      result=await fetchBatch(nextQuery,saved?.revision==='local'?0:savedOffset,saved?.revision);
      if(request!==serial)return;
    }catch(e){
      if(request!==serial)return;
      if(e.invalidCriteria||e.timedOut)throw e;
      publicAvailable=false;
      wasFallback=true;
    }
    if(!publicAvailable){
      await fullCatalog();
      const corpus=await corpusFor(p);
      if(request!==serial)return;
      const scoped=DATA.filter(x=>(!p.schools.length||p.schools.includes(x.school))&&(!p.name||x.name.toLowerCase().includes(p.name.toLowerCase()))&&(!p.group||x.unit_groups?.includes(p.group))&&(!nextScope.school||x.school===nextScope.school)&&(!nextScope.dept||x.dept===nextScope.dept)&&R.directoryMatch(x,{...p,include_missing_email:true},corpus[x.page]||''));
      missingEmail=scoped.filter(x=>!R.contactable(x)).length;
      localRows=R.directoryRank(scoped.filter(x=>p.include_missing_email||R.contactable(x)),orderSeed);
      total=localRows.length;
      batchOffset=saved?.revision==='local'&&total>batchSize&&savedOffset<total?savedOffset:0;
      view=localBatch(localRows,batchOffset);
      revision='local';
    }else{
      setPublicBatch(result);
      localRows=null;
    }
    query=nextQuery;
    const restorePosition=saved?.revision===revision&&saved.offset===batchOffset;
    returnAnchor=restorePosition?saved.anchor||'':'';
    applied=p;
    appliedScope=nextScope;
    criteriaDirty(query!==publicQuery(readCriteria()));
    render();
    if(wasFallback)message('候选服务暂不可用，已使用网站公开资料在浏览器中筛选。');
    else if(saved?.revision&&saved.revision!==revision)batchMessage('公开资料已更新，已重新显示首批。');
    if(restorePosition)requestAnimationFrame(()=>requestAnimationFrame(()=>{
      if(request!==serial)return;
      const anchor=saved.anchor&&document.querySelector('[data-candidate="'+CSS.escape(saved.anchor)+'"]');
      if(anchor)anchor.scrollIntoView({block:'center'});
      else window.scrollTo(0,saved.scroll||0);
    }));
    saveView();
    return true;
  }catch(e){
    if(request===serial)message(e.message+(applied?'；已保留当前结果。':'；点击“查看候选”重新读取。'),true);
    return false;
  }finally{
    if(request===serial){
      el('apply-criteria').disabled=false;
      more.disabled=false;
    }
  }
}
async function moreCandidates(){
  const button=el('more-candidates');
  if(button.disabled||button.hidden||button.hasAttribute('aria-disabled'))return;
  const request=++serial,offset=(batchOffset+view.length)%total;
  button.setAttribute('aria-disabled','true');
  batchMessage('正在换一批…');
  try{
    const previousRevision=revision;
    if(localRows){
      view=localBatch(localRows,offset);
      batchOffset=offset;
    }else{
      const result=await fetchBatch(query,offset,revision);
      if(request!==serial)return;
      setPublicBatch(result);
    }
    returnAnchor='';
    render();
    saveView();
    batchMessage(revision!==previousRevision?'公开资料已更新，已重新显示首批。':'已显示新一批导师。');
  }catch(e){
    if(request===serial)batchMessage('下一批未能加载，已保留当前结果，请重试。',true);
  }finally{
    if(request===serial)button.removeAttribute('aria-disabled');
  }
}
function returnScope(p){const q=scope(p);q.set('discovery_return','discovery.html'+location.search);return q;}
function renderSelection(){const goal=returnScope();if(incoming.get('project')&&goal.get('school')===incoming.get('school')&&goal.get('dept')===incoming.get('dept'))goal.set('project',incoming.get('project'));el('compare-selection').hidden=!compareSelection.length;el('compare-count').textContent='已选 '+compareSelection.length+' 位导师';el('compare-open').href='compare.html?'+goal;el('compare-open').textContent=compareSelection.length===1?'查看已选导师':'查看对比';}
function safeSource(p){const value=p.email_source||p.provenance?.email?.source||p.profile_url||p.detail_url;try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:'';}catch(e){return '';}}
function render(){renderSelection();renderContext();el('discovery-count').textContent=total+' 位候选 · 当前显示 '+view.length+' 位';const p=applied;el('intent-overview').textContent=[p.name&&'姓名：'+p.name,p.topics.length&&p.topics.join('、'),p.schools.length&&p.schools.map(schoolName).join('、'),p.qualifications.length&&p.qualifications.map(x=>qualificationLabels[x]).join('或'),p.titles.length&&p.titles.map(x=>titleLabels[x]).join('、'),p.group&&[...el('intent-group').options].find(option=>option.value===p.group)?.textContent,p.include_missing_email?'包含缺邮箱资料':'有公开邮箱'].filter(Boolean).join(' · ');
el('candidate-list').innerHTML=view.map(m=>{
  const goal=returnScope(m),detailPath='p/'+encodeURIComponent(m.page)+'.html?',bookmarkUrl=detailPath+goal,project=incoming.get('project');
  if(project&&m.school===incoming.get('school')&&m.dept===incoming.get('dept'))goal.set('project',project);
  const detail=detailPath+goal;
  goal.set('mentor',m.page);
  const direction=R.researchText(m.research_direction_raw),preview=direction||m.bio_excerpt||'',source=safeSource(m),canContact=R.contactable(m),labels=(m.recruitment_labels||[]).filter(x=>typeof x==='string');return `<article class="results-card" data-candidate="${esc(m.page)}"><div class="candidate-header"><div class="candidate-heading"><h2><a href="${esc(detail)}">${esc(m.name)}</a></h2><span class="candidate-qualification">${esc(m.supervisor||'资格未明确')}</span></div><p class="candidate-unit">${esc(m.school_name||schoolName(m.school))} · ${esc(m.dept_name||m.dept)}</p><p class="candidate-title">${esc(m.title||'职称未明确')}</p></div><p class="research-preview"><span>${direction?'研究方向':preview?'官网简介':'研究资料'}</span> · ${esc(preview||'尚未整理，查看完整资料与官网。')}</p><div class="public-email">${canContact?`<span>公开邮箱</span><a href="mailto:${encodeURIComponent(m.email)}" title="${esc(m.email)}">${esc(m.email)}</a>`:'<span>公开邮箱未明确</span><span>请通过官网核对联系渠道</span>'}</div><div class="candidate-source">${source?`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">${esc(m.source_label||'公开资料来源')} ↗</a>`:'<span>来源待核对</span>'}<span>${labels.length?esc(labels.join(' · ')):m.email_source_date||m.source_date?'来源获取 '+esc(m.email_source_date||m.source_date):'来源时间未明确'}</span></div><div class="card-primary-actions"><a class="primary" href="${esc(detail)}">查看资料</a><a href="desk.html?${esc(goal)}">准备联系</a><button type="button" data-compare="${esc(m.page)}" aria-pressed="${compareSelection.includes(m.page)}">${compareSelection.includes(m.page)?'移出对比':'加入对比'}</button></div><div class="candidate-bookmark"><button type="button" data-browser-bookmark="mentor" data-bookmark-id="${esc(m.page)}" data-bookmark-url="${esc(bookmarkUrl)}">收藏到我的账号</button></div></article>`;}).join('')||`<div class="empty"><h2>当前条件下暂无可联系候选</h2><p>${missingEmail&&!p.include_missing_email?`有 ${missingEmail} 条匹配资料尚无格式有效且可追溯的邮箱。`:'可尝试减少关键词或调整学校、资格与职称；资料未命中不代表真实研究不适合。'}</p>${!p.include_missing_email?'<button type="button" id="empty-include-email">包含缺邮箱资料重新查找</button>':''}<p><a href="admissions.html?${esc(scope())}">查看学校与官方师资入口 →</a> · <a href="index.html">查看完整目录</a></p></div>`;el('more-candidates').hidden=total<=batchSize;}
const schools=window.SCHOOL_CATALOG?.schools||[];el('school-options').innerHTML=schools.map(s=>`<label class="school-option"><input type="checkbox" value="${esc(s.id)}"><span>${esc(s.name)}</span></label>`).join('');el('title-options').innerHTML=Object.entries(titleLabels).map(([id,label])=>`<label class="check"><input type="checkbox" value="${id}">${label}</label>`).join('');
const mobileFilters=matchMedia('(max-width:850px)');
el('criteria-panel').open=!mobileFilters.matches;
mobileFilters.addEventListener('change',event=>{if(!event.matches)el('criteria-panel').open=true;});
el('filter-options').open=!mobileFilters.matches;
el('criteria-form').addEventListener('input',e=>{if(e.target.id!=='school-search'){criteriaDirty();syncFilters();}});
el('criteria-form').addEventListener('change',e=>{if(e.target.closest('#school-options')&&contextSchool){contextSchool='';contextDept='';renderContext();}criteriaDirty();syncFilters();});
el('criteria-form').onsubmit=async e=>{
  e.preventDefault();
  message('');
  const request=serial+1,submittedQuery=publicQuery(readCriteria());
  const succeeded=await apply();
  if(request!==serial||submittedQuery!==publicQuery(readCriteria()))return;
  if(succeeded&&mobileFilters.matches)el('criteria-panel').open=false;
  const target=el(succeeded?'discovery-results':'discovery-message');
  const {top}=target.getBoundingClientRect();
  const headerBottom=document.querySelector('.site-header').getBoundingClientRect().bottom;
  if(!succeeded||matchMedia('(max-width:850px)').matches||top<headerBottom||top>=innerHeight){
    target.focus({preventScroll:true});
    target.scrollIntoView({block:'start'});
  }
};
el('school-search').oninput=()=>{const term=el('school-search').value.trim().toLowerCase();let count=0;for(const label of el('school-options').children){label.hidden=!label.textContent.toLowerCase().includes(term)&&!label.querySelector('input').value.toLowerCase().includes(term);if(!label.hidden)count++;}el('school-search-status').textContent=term?'找到 '+count+' 所学校；已有选择保持不变。':'';};el('school-search').onkeydown=e=>{if(e.key==='Enter')e.preventDefault();};
function schoolsChanged(){contextSchool='';contextDept='';renderContext();syncFilters();criteriaDirty();}
el('school-chips').onclick=e=>{const b=e.target.closest('[data-remove-school]');if(!b)return;for(const box of el('school-options').querySelectorAll('input'))if(box.value===b.dataset.removeSchool)box.checked=false;schoolsChanged();el('filter-options-label').focus();};el('clear-schools').onclick=()=>{for(const box of el('school-options').querySelectorAll('input'))box.checked=false;schoolsChanged();};el('select-visible-schools').onclick=()=>{for(const label of el('school-options').children)if(!label.hidden)label.querySelector('input').checked=true;schoolsChanged();};el('clear-unit-context').onclick=()=>{contextSchool='';contextDept='';renderContext();apply();};
el('more-candidates').onclick=moreCandidates;
el('candidate-list').onclick=async e=>{if(e.target.closest('#empty-include-email')){el('include-missing-email').checked=true;syncFilters();apply();return;}const b=e.target.closest('[data-compare]');if(b){const id=b.dataset.compare;returnAnchor=id;if(compareSelection.includes(id))compareSelection=compareSelection.filter(x=>x!==id);else if(compareSelection.length<5)compareSelection.push(id);else{message('最多对比5位导师，请先移出一位。');return;}try{localStorage.setItem('compare_sel',JSON.stringify(compareSelection));renderSelection();b.textContent=compareSelection.includes(id)?'移出对比':'加入对比';b.setAttribute('aria-pressed',String(compareSelection.includes(id)));}catch(e){message('浏览器无法保存对比选择。',true);}return;}const bookmark=e.target.closest('[data-bookmark-id]');if(bookmark){try{await BrowserLibrary.save({kind:'mentor',title:view.find(p=>p.page===bookmark.dataset.bookmarkId).name,url:bookmark.dataset.bookmarkUrl});bookmark.textContent='已收藏';message('已收藏到我的账号，可在申请导航查看。');}catch(e){message('收藏未保存：'+e.message,true);}}};
document.addEventListener('click',e=>{if(e.target.closest('a[href]')){const card=e.target.closest('[data-candidate]');if(card)returnAnchor=card.dataset.candidate;saveView();}},true);window.addEventListener('pagehide',saveView);window.addEventListener('pageshow',e=>{if(e.persisted)renderSelection();});
el('legacy-backup').onclick=async()=>{try{const response=await fetch('/api/discovery/backup');if(!response.ok)throw new Error('请登录后导出账号中的历史记录');const data=await response.json(),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='discovery-history-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('已导出历史筛选与核对记录；这些记录不参与当前导师排序。');}catch(e){message(e.message,true);}};
(async()=>{const base={name:incoming.get('name')||'',topics:(incoming.get('topics')||'').split(/[,，]/).filter(Boolean),schools:contextSchool?[contextSchool]:[],qualifications:incoming.getAll('qualifications').filter(x=>x in qualificationLabels),titles:incoming.getAll('titles').filter(x=>x in titleLabels),group:incoming.get('group')||'',include_missing_email:incoming.get('include_missing_email')==='1'};if(restore?.criteria){contextSchool=restore.contextSchool||'';contextDept=restore.contextDept||'';fillCriteria(restore.criteria);}else fillCriteria(base);renderContext();const initialRequest=serial+1,succeeded=await apply(restore);if(initialRequest===serial&&succeeded===false)el('criteria-panel').open=true;window.DISCOVERY_READY=true;})().catch(e=>message(e.message,true));

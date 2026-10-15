const el=id=>document.getElementById(id),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ADMISSIONS_DATA=window.ADMISSIONS_DATA,labels={school:'学校通用',dept:'院系要求',program:'专业要求'},degrees={master:'硕士',phd:'博士'},routes={recommend:'推免',exam:'统考',assessment:'申请考核'};
const fields={eligibility:'报名资格',materials:'所需材料',exams:'考核与科目',timeline:'时间安排',tuition:'学费与学制',funding:'奖助政策',quota:'招生计划',contact:'咨询与报名入口'};
let invalidYear=false,visibleUnits=[];
const schools=[...new Map(ADMISSIONS_DATA.units.map(u=>[u.school,u.school_name])).entries()];
function options(select,rows,label,value=''){select.innerHTML=`<option value="">${label}</option>`+rows.map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');if(value&&!rows.some(r=>r[0]===value))select.add(new Option(value+'（未收录）',value));select.value=value;}
function criteria(){return {school:el('policy-school').value,dept:el('policy-dept').value,year:el('policy-year').value,degree:el('policy-degree').value,route:el('policy-route').value,track:el('policy-track').value,group:el('policy-group').value,program:el('policy-program').value};}
function depts(value=''){options(el('policy-dept'),ADMISSIONS_DATA.units.filter(u=>u.school===el('policy-school').value&&(!el('policy-group').value||u.groups.includes(el('policy-group').value))).map(u=>[u.dept,u.dept_name]),'全部院系',value);}
function scopeQuery(prefs){const query=new URLSearchParams();for(const [key,value] of Object.entries(prefs))if(value)query.set(key,value);return query;}
function sourceLinks(policy,item){return AdmissionsRules.sourceReferences(policy,item,ADMISSIONS_DATA.sources).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>`).join(' · ');}
function policyTiming(policy){
  const states=(policy.events||[]).filter(e=>e.kind==='deadline').map(e=>AdmissionsRules.eventState(e));
  if(states.includes('future'))return {group:0,label:'有尚未过去的已登记截止时间；是否开放须查官网'};
  if(!states.length||states.includes('unknown'))return {group:1,label:'截止时间未完整整理，需查官方通知'};
  return {group:2,label:'已登记截止时间均已过；可能还有后续轮次，需查官网'};
}
function successfulSourceDate(policy){
  const ids=Object.keys(policy.review_hashes||{}),checks=ids.map(id=>ADMISSIONS_DATA.checks[id]);
  const days=checks.map(c=>c?.last_success).filter(day=>/^\d{4}-\d{2}-\d{2}$/.test(day||'')&&Number.isFinite(Date.parse(day+'T00:00:00Z'))&&new Date(day+'T00:00:00Z').toISOString().slice(0,10)===day&&day<=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'}));
  const failed=checks.some(c=>c?.status==='error'),missing=!ids.length||days.length!==ids.length||ids.some(id=>!ADMISSIONS_DATA.sources[id])||checks.some(c=>!c||!['ok','error'].includes(c.status));
  return (missing?'暂无完整成功记录':days.sort()[0])+(failed?'（最近来源检查失败，需复核）':missing?'（来源记录缺失或日期异常）':'');
}
function unitInfo(u,prefs){
  const c=u.coverage,d=c.source_dates,query=scopeQuery({...prefs,school:u.school,dept:u.dept});
  if(!u.count)return `<article class="unit-info" data-unit-info="${esc(u.school+'/'+u.dept)}"><h3>${esc(u.dept_name)}</h3><p>导师名单待补，暂不能统计联系信息。${esc(u.roster_pending)}</p><a href="${esc(u.roster_url)}" target="_blank" rel="noopener">核对官方师资入口 →</a></article>`;
  return `<article class="unit-info" data-unit-info="${esc(u.school+'/'+u.dept)}"><h3>${esc(u.dept_name)} · ${u.count} 条教师记录</h3>${u.roster_pending?`<p class="quality">采集范围待核对：${esc(u.roster_pending)}</p>`:''}<dl class="unit-metrics">${[['email','公开邮箱'],['research_direction_raw','明确研究方向'],['bio_raw','官网简介'],['supervisor','明确导师资格']].map(([key,label])=>`<div><dt>${label}</dt><dd>${c[key]}<small> / ${u.count} 已知 · ${u.count-c[key]} 待补</small></dd></div>`).join('')}</dl><p class="stats">来源抓取日期：${d.known?esc(d.earliest)+(d.earliest!==d.latest?' 至 '+esc(d.latest):''):'未知'}；${d.unknown} 条日期未知。抓取日期不表示官网内容更新日期。</p><p class="stats">方向未明确标注时可先查简介；导师资格不代表当年有名额。跨院系记录未按姓名合并。</p><a href="discovery.html?${query}">按当前申请目标找导师 →</a></article>`;
}
function checklistScope(row,prefs){
  const p=row.policy;
  return labels[p.level]+(p.program?' · '+p.program+' '+p.program_code:'')+(row.conditional?' · 专业适用待核对（条件性参考，不计当前目标覆盖）':'')+(prefs.track==='special'&&p.level==='school'?' · 专项适用性仍待核实':'');
}
function checklistItem(item,prefs){
  const known=item.rows.filter(row=>row.field),unknown=item.rows.filter(row=>!row.field);
  const warnings=[...new Map(item.rows.filter(row=>row.quality.state!=='checked').map(row=>[row.quality.state,row.quality])).values()];
  const preview=known.map(row=>`<p><span class="scope">${esc(checklistScope(row,prefs))}</span><br>${esc(row.field.text)}</p>`).join('');
  const pending=unknown.length?`<p class="muted">未整理，待查：${esc([...new Set(unknown.map(row=>labels[row.policy.level]+(row.policy.program?' · '+row.policy.program+' '+row.policy.program_code:'')+(row.conditional?'（适用待核对）':'')))].join('；'))}。不能认定没有要求。</p>`:!item.rows.length?'<p class="muted">未整理，待查官方招生规则。</p>':'';
  const status=warnings.map(q=>`<p class="checklist-status ${q.state}">需重新核对 · ${esc(q.label)}</p>`).join('')||(known.length?'<p class="checklist-status checked">有摘要，申请前核对原文</p>':'');
  const evidence=item.rows.map(row=>{const p=row.policy,f=row.field;return `<div class="checklist-row" data-checklist-policy="${esc(p.id)}"><p class="scope">${esc(checklistScope(row,prefs))} · <a href="#policy-${esc(p.id)}">查看政策摘要</a></p>${f?`<blockquote>原文短片段：${esc(f.quote)}<br>定位：${esc(f.locator)}</blockquote>`:'<p class="muted">本层未整理，待查原文。</p>'}${sourceLinks(p,f)}<p class="quality ${row.quality.state}">${esc(row.quality.label)}</p></div>`;}).join('');
  return `<section class="checklist-field" data-checklist-field="${item.key}"><h3>${fields[item.key]}</h3>${preview}${pending}${status}${evidence?`<details><summary>展开各层原文与来源</summary>${evidence}</details>`:''}</section>`;
}
function renderChecklist(prefs,valid){
  const result=AdmissionsRules.checklist(ADMISSIONS_DATA,prefs),names={school:'学校',dept:'院系',year:'入学年度',degree:'学位',route:'渠道',track:'招生范围（普通／专项）'};
  if(!valid||!result.ready){
    el('application-checklist').innerHTML=`<h2>申请前核对清单</h2><p id="checklist-prompt" class="stats">${result.missing.length?'请先补全目标：'+esc(result.missing.map(key=>names[key]).join('、'))+'。':'请修正学校、院系、年度、学位、渠道或招生范围。'}下方仍可浏览政策；目标完整后再生成对应清单。</p>`;
    return;
  }
  const unit=ADMISSIONS_DATA.units.find(u=>u.school===prefs.school&&u.dept===prefs.dept),query=scopeQuery(prefs);
  el('application-checklist').innerHTML=`<h2>申请前核对清单</h2><p class="checklist-target">${esc(unit.school_name)} · ${esc(unit.dept_name)} · ${esc(prefs.year)}入学 · ${degrees[prefs.degree]} · ${routes[prefs.route]} · ${prefs.track==='special'?'专项/特定项目':'普通招生'}${prefs.program?' · 专业 '+esc(prefs.program.replace('|',' · ')):' · 专业未指定'}</p><div class="actions"><a id="checklist-mentors" href="discovery.html?${query}">带目标找导师 →</a><a id="checklist-notices" href="notices.html?${query}">查院系招生通知 →</a><a id="checklist-project" href="applications.html?${query}">预填申请项目 →</a></div><p class="stats">项目仅预填公开目标信息，点击保存后才写入私人记录。</p><p class="stats">每类同时核对学校、院系与适用专业；清单帮助查证，不表示符合资格或完成申请。申请进度请在项目与材料中记录。${prefs.program?'所选专业没有摘要时仍须查当年目录。':'未指定专业/项目时，相关条款仅作条件性参考，不计当前目标覆盖；请确认代码及正式名称。'}已整理的摘要也不代表条款完整。</p>${!result.policies.length?'<p class="quality">该目标尚无规则摘要，8类要求均待查。请用本页官方招生入口核实；不能借用往年或其他渠道的要求。</p>':''}<div class="checklist-fields">${result.items.map(item=>checklistItem(item,prefs)).join('')}</div>${result.events.length?`<div id="checklist-events"><h3>已知轮次与时间</h3>${result.events.map(row=>`<p class="quality">${esc(checklistScope(row,prefs))} · ${esc(row.policy.title)}<br>${esc(row.event.label)} · ${esc(row.event.at)} · ${row.state==='past'?(row.event.kind==='deadline'?'该轮次已截止':'既往安排'):row.state==='unknown'?'日期待核实':'已知安排，报名是否开放仍须核实'}<br><small>原文：${esc(row.event.quote)} · ${esc(row.event.locator)} · ${sourceLinks(row.policy,row.event)}</small></p>`).join('')}</div>`:''}<section class="checklist-mentor"><h3>导师事项 · 待选择导师核验</h3><p>导师资格、当年招生机会与个人联系方式须分别核对导师及院系官方资料。院系招生计划不能推断为某位导师有名额，院系咨询邮箱不能当作导师邮箱。</p></section>`;
}
function render(){
  const prefs=criteria();visibleUnits=ADMISSIONS_DATA.units.filter(u=>!prefs.group||u.groups.includes(prefs.group));const units=visibleUnits.filter(u=>(!prefs.school||u.school===prefs.school)&&(!prefs.dept||u.dept===prefs.dept));
  const valid=!invalidYear&&(!prefs.group||Object.hasOwn(ADMISSIONS_DATA.groups,prefs.group))&&(!prefs.track||['ordinary','special'].includes(prefs.track))&&(!prefs.degree||Object.hasOwn(degrees,prefs.degree))&&(!prefs.route||Object.hasOwn(routes,prefs.route))&&(!prefs.school||schools.some(s=>s[0]===prefs.school))&&(!prefs.dept||units.length>0)&&(!prefs.year||Number.isInteger(Number(prefs.year))&&Number(prefs.year)>=2000&&Number(prefs.year)<=2100);
  const records=valid?AdmissionsRules.select(ADMISSIONS_DATA.policies,prefs).filter(p=>!prefs.group||visibleUnits.some(u=>u.school===p.school&&(!p.dept||u.dept===p.dept))).sort((a,b)=>policyTiming(a).group-policyTiming(b).group||b.year-a.year||String(b.reviewed_at||'').localeCompare(a.reviewed_at||'')||a.id.localeCompare(b.id)):[];
  options(el('policy-program'),[...new Map(records.filter(p=>p.level==='program'||p.track==='special'&&p.program).map(p=>[AdmissionsRules.programKey(p),p.program+' '+p.program_code])).entries()].sort((a,b)=>a[0].localeCompare(b[0],'zh-CN')),'未指定（专业要求待核对）',prefs.program);
  renderChecklist(prefs,valid);
  const schoolsCovered=new Set(ADMISSIONS_DATA.policies.map(p=>p.school)).size,unitsCovered=new Set(ADMISSIONS_DATA.policies.filter(p=>p.dept).map(p=>p.school+'/'+p.dept)).size;
  el('policy-coverage').textContent=`目录 ${schools.length} 校 / ${ADMISSIONS_DATA.units.length} 院系；规则样本 ${schoolsCovered} 校 / ${unitsCovered} 院系 / ${ADMISSIONS_DATA.policies.length} 条。两种覆盖范围不同；不表示全部招生政策已整理。`;
  el('school-directory').innerHTML=schools.filter(([id])=>visibleUnits.some(u=>u.school===id)).map(([id,name])=>{const rows=visibleUnits.filter(u=>u.school===id);return `<button data-school="${esc(id)}" ${prefs.school===id?'aria-current="true"':''}>${esc(name)}<br><small>${rows.length} 院系 · ${rows.reduce((n,u)=>n+u.count,0)} 位本库导师</small></button>`;}).join('');
  el('unit-directory-list').innerHTML=units.map(u=>`<button data-unit-school="${esc(u.school)}" data-unit-dept="${esc(u.dept)}">${esc(u.dept_name)}<br><small>导师记录 ${u.count||'待补'} · 通知${u.notice_url?'已接入':'待补'} · 人工规则 ${ADMISSIONS_DATA.policies.filter(p=>p.school===u.school&&p.dept===u.dept).length}</small></button>`).join('');
  el('unit-catalog').innerHTML=(prefs.school?units:[]).map(u=>`<a href="${esc(u.roster_url)}" target="_blank" rel="noopener">${esc(u.dept_name)}官方师资入口</a>`).join(' · ');
  el('unit-name').textContent=(schools.find(s=>s[0]===prefs.school)?.[1]||'学校与院系')+(prefs.dept?' · '+(units[0]?.dept_name||prefs.dept):'');
  el('unit-description').textContent=valid?`${units.length} 个院系在当前目录范围内。${units.filter(u=>!u.count).length?' 导师名单待补：'+units.filter(u=>!u.count).map(u=>u.roster_pending||u.dept_name).join('；'):''}学校通用规则与院系/专业附加要求须共同核对，不能只看一层。`:'学校/院系或年度未收录或无效；未借用其他单位的规则。';
  el('unit-readiness').innerHTML=valid&&prefs.school?units.map(u=>unitInfo(u,prefs)).join(''):'<p class="stats">选择学校或院系，查看邮箱、方向、简介及导师资格的信息覆盖，再决定从哪里开始找导师。</p>';
  const entries=[...new Map((prefs.school?units:[]).filter(u=>u.notice_url).map(u=>[u.notice_url,u.dept_name+'官网招生栏目'])).entries()];
  el('unit-entries').innerHTML=entries.map(([url,name])=>`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(name)}</a>`).join('')||(prefs.school?'<span class="muted">该范围尚未登记官方招生栏目；可从导师完整资料查院系官网，或使用研招网查招生单位。</span>':'<span class="muted">选择学校与院系，查看对应官方招生入口。</span>');
  el('unit-entries').innerHTML+='<a href="https://yz.chsi.com.cn/zsml/index.html" target="_blank" rel="noopener">研招网专业目录</a>';
  const query=scopeQuery(prefs);if(invalidYear)query.set('year',incoming.get('year'));history.replaceState(null,'',location.pathname+(query.size?'?'+query:'')+location.hash);for(const a of document.querySelectorAll('.site-header a[href]')){const path=a.getAttribute('href').split('?')[0];if(['discovery.html','compare.html','admissions.html','notices.html','desk.html','applications.html'].includes(path))a.href=path+'?'+query;}el('unit-mentors').href='discovery.html?'+query;el('unit-mentors').hidden=!valid;
  el('unit-notices').href='notices.html?'+query;el('unit-notices').hidden=!valid||!prefs.school||!prefs.dept;
  el('policy-count').textContent=`当前目标：${invalidYear?'无效年度，请重新填写':prefs.year||'全部年度'} · ${degrees[prefs.degree]||(prefs.degree?'未知学位':'全部学位')} · ${routes[prefs.route]||(prefs.route?'未知渠道':'全部渠道')}。${records.length} 条规则摘要，未计算个人符合率。优先展示有尚未过去的截止时间，其次截止未完整整理，最后已登记截止均已过的政策。`;
  el('policy-list').innerHTML=records.map(p=>{
    const source=ADMISSIONS_DATA.sources[p.source_id],quality=AdmissionsRules.quality(p,ADMISSIONS_DATA.checks),school=schools.find(s=>s[0]===p.school)?.[1]||p.school,unit=ADMISSIONS_DATA.units.find(u=>u.school===p.school&&u.dept===p.dept);
    const project=new URLSearchParams({policy:p.id});
    return `<article class="policy-card" id="policy-${esc(p.id)}" data-policy="${esc(p.id)}"><span class="scope">${labels[p.level]} · ${esc(school)} ${esc(unit?.dept_name||'')} · ${p.year} · ${degrees[p.degree]} · ${routes[p.route]}${p.program?' · '+esc(p.program)+' '+esc(p.program_code):''}</span><h2>${esc(p.title)}</h2><p class="policy-timing">${esc(policyTiming(p).label)}</p><p class="scope">范围：${p.track==='special'?(esc(p.program)||'专项（具体类型需核对）'):p.level==='school'?'学校通用，专项仍须核实适用':'普通招生'}</p>${(p.events||[]).map(e=>`<p class="quality">${esc(e.label)} · ${esc(e.at)} · ${AdmissionsRules.eventState(e)==='past'?(e.kind==='deadline'?'该轮次已截止':'既往安排'):'已知安排，申请前核实'}<br><small>原文：${esc(e.quote)} · ${esc(e.locator)} · ${sourceLinks(p,e)}</small></p>`).join('')}<p class="policy-age">官方发布 ${esc(p.published_at||'未知')} · 最近成功回源 ${esc(successfulSourceDate(p))} · 摘要核对 ${esc(p.reviewed_at||'未知')} · 已整理 ${Object.keys(p.fields).length}/8 类摘要；其余要求待查，不代表条款完整</p><div class="quality ${quality.state}">${quality.label}</div><details class="policy-body"><summary>查看八类要求与原文</summary><div class="policy-fields">${Object.entries(fields).map(([key,label])=>{const f=p.fields[key];return `<section class="policy-field"><h3>${label}</h3>${f?`<p>${esc(f.text)}</p><blockquote>原文短片段：${esc(f.quote)}<br>定位：${esc(f.locator)} · ${sourceLinks(p,f)}</blockquote>`:'<p class="muted">未整理，需查原文；不能认定没有要求。</p>'}</section>`;}).join('')}</div><p class="policy-age">${Object.keys(p.review_hashes).map(id=>{const s=ADMISSIONS_DATA.sources[id],c=ADMISSIONS_DATA.checks[id];return `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label||(s.format==='pdf'?'PDF原文':'通知正文/附件入口'))}</a> · 最近成功检查 ${esc(c?.last_success||'无')} · 最近尝试 ${esc(c?.last_attempt||'无')}${c?.cached?'（缓存读取）':''}`;}).join('<br>')}</p><div class="actions"><a href="applications.html?${project}">建立申请项目 →</a><a href="${esc(source.url)}" target="_blank" rel="noopener">核对完整政策</a></div></details></article>`;
  }).join('')||'<p class="empty">当前学校/院系、年度、学位或渠道的规则尚未覆盖。请从官网招生栏目和研招网核实；未覆盖不代表不招生，也不借用往年或其他渠道规则。</p>';
}
const incoming=new URLSearchParams(location.search);options(el('policy-school'),schools,'全部学校',incoming.get('school')||'');depts(incoming.get('dept')||'');
const rawYear=incoming.get('year')||'';invalidYear=!!rawYear&&(!/^\d{4}$/.test(rawYear)||Number(rawYear)<2000||Number(rawYear)>2100);el('policy-year').value=invalidYear?'':rawYear;
options(el('policy-group'),Object.entries(ADMISSIONS_DATA.groups),'全部相关院系',incoming.get('group')||'');options(el('policy-track'),[['ordinary','普通招生'],['special','专项/特定项目']],'全部范围',incoming.get('track')||'');depts(incoming.get('dept')||'');
options(el('policy-program'),[],'未指定（专业要求待核对）',incoming.get('program')||'');
for(const key of ['degree','route']){const select=el('policy-'+key),value=incoming.get(key)||'';if(value&&!Array.from(select.options).some(o=>o.value===value))select.add(new Option(value+'（未知）',value));select.value=value;}
function clearUnitProject(){el('policy-program').value='';if(el('policy-track').value==='special')el('policy-track').value='';}
el('policy-school').onchange=()=>{depts();clearUnitProject();render();};for(const id of ['policy-dept','policy-year','policy-degree','policy-route','policy-track','policy-program'])el(id).onchange=()=>{if(id==='policy-year')invalidYear=false;if(id!=='policy-program')el('policy-program').value='';if(id==='policy-dept')clearUnitProject();render();};
el('school-directory').onclick=event=>{const button=event.target.closest('[data-school]');if(button){el('policy-school').value=button.dataset.school;depts();clearUnitProject();render();}};
el('policy-group').onchange=()=>{el('policy-school').value='';depts();clearUnitProject();render();};el('unit-directory-list').onclick=event=>{const b=event.target.closest('[data-unit-school]');if(b){el('policy-school').value=b.dataset.unitSchool;depts(b.dataset.unitDept);clearUnitProject();render();}};
render();window.ADMISSIONS_READY=true;

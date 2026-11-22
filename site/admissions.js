const el=id=>document.getElementById(id),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ADMISSIONS_DATA=window.ADMISSIONS_DATA,labels={school:'学校通用',dept:'院系要求',program:'专业要求'},degrees={master:'硕士',phd:'博士'},routes={recommend:'推免',exam:'统考',assessment:'申请考核'};
const fields={eligibility:'报名资格',materials:'所需材料',exams:'考核与科目',timeline:'时间安排',tuition:'学费与学制',funding:'奖助政策',quota:'招生计划',contact:'咨询与报名入口'};
let invalidYear=false,visibleUnits=[];
const policyCatalog=ADMISSIONS_DATA.policies,schoolVersions=ADMISSIONS_DATA.school_versions,schoolRequests=new Map();
let currentSchool='',schoolRequest=0,waitingForSchool=false,revealPending=true;
const schools=Array.isArray(ADMISSIONS_DATA.schools)?ADMISSIONS_DATA.schools.map(s=>[s.id,s.name]):[...new Map(ADMISSIONS_DATA.units.map(u=>[u.school,u.school_name])).entries()];
function options(select,rows,label,value=''){select.innerHTML=`<option value="">${label}</option>`+rows.map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');if(value&&!rows.some(r=>r[0]===value))select.add(new Option(value+'（未收录）',value));select.value=value;}
function criteria(){return {school:el('policy-school').value,dept:el('policy-dept').value,year:el('policy-year').value,degree:el('policy-degree').value,route:el('policy-route').value,track:el('policy-track').value,group:el('policy-group').value,program:el('policy-program').value};}
function depts(value=''){options(el('policy-dept'),ADMISSIONS_DATA.units.filter(u=>u.school===el('policy-school').value&&(!el('policy-group').value||u.groups.includes(el('policy-group').value))).map(u=>[u.dept,u.dept_name]),'全部院系',value);}
function scopeQuery(prefs){const query=new URLSearchParams();for(const [key,value] of Object.entries(prefs))if(value)query.set(key,value);if(incoming.get('topics'))query.set('topics',incoming.get('topics'));return query;}
function projectQuery(policy,prefs){
  const query=new URLSearchParams({policy:policy.id,school:policy.school,year:policy.year,degree:policy.degree,route:policy.route});
  const unit=ADMISSIONS_DATA.units.find(u=>u.school===policy.school&&u.dept===prefs.dept);
  const same=prefs.school===policy.school&&unit&&(!policy.dept||policy.dept===prefs.dept)&&Number(prefs.year)===policy.year&&prefs.degree===policy.degree&&prefs.route===policy.route;
  const generic=!policy.track||policy.track==='general',track=generic?(same?prefs.track:''):policy.track;
  const dept=policy.dept||(prefs.school===policy.school&&unit?prefs.dept:'');
  if(dept)query.set('dept',dept);
  if(track&&track!=='general')query.set('track',track);
  const program=policy.program?AdmissionsRules.programKey(policy):same&&prefs.track===track?prefs.program:'';
  if(program)query.set('program',program);
  return query;
}
function sourceLinks(policy,item){return AdmissionsRules.sourceReferences(policy,item,ADMISSIONS_DATA.sources).map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label)}</a>`).join(' · ');}
function entryStatus(entry){
  const check=ADMISSIONS_DATA.checks[entry.source_id],today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
  const age=day=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(day||''))return NaN;const time=Date.parse(day+'T00:00:00Z');return Number.isFinite(time)&&new Date(time).toISOString().slice(0,10)===day?(Date.parse(today+'T00:00:00Z')-time)/86400000:NaN;};
  const success=Number.isFinite(age(check?.last_success))&&age(check?.last_success)>=0?check.last_success:'';
  if(check?.status==='error')return {state:'error',label:'最近回源失败，需查官网',success};
  if(check?.status!=='ok'||!check.hash||!success)return {state:'unknown',label:'尚未检查来源或无有效成功记录',success:''};
  if(age(success)>7)return {state:'stale',label:'来源超过7天未成功检查，需复核',success};
  if(!Number.isFinite(age(entry.reviewed_at))||age(entry.reviewed_at)<0||age(entry.reviewed_at)>30)return {state:'review',label:'入口超过30天未核对或日期异常',success};
  return {state:'checked',label:'近期回源及入口核对有效；申请前仍需查看',success};
}
function eventTiming(event,state=AdmissionsRules.eventState(event)){
  if(state==='unknown')return '日期待核实；不表示接受新报名';
  if(event.kind==='deadline')return state==='past'?'该事项已截止；不表示整轮招生结束':'该事项截止（报名/材料/准考证等）；不表示接受新报名';
  if(event.kind==='exam')return state==='past'?'既往考核安排；不代表新报名':'考核安排，仅适用已达本轮条件者；不代表新报名';
  return state==='past'?'既往安排；不代表新报名':'已登记安排；适用条件须核对，不表示接受新报名';
}
function entryScope(entry,prefs){
  const keys=['year','degree','route'];
  if(keys.some(k=>prefs[k]&&entry[k]!==undefined&&String(entry[k])!==String(prefs[k])))return 'other';
  return keys.every(k=>prefs[k]&&entry[k]!==undefined)?'matching':'unknown';
}
function conditionNotice(p){return p.applies_if?`<p class="quality policy-condition">${esc(AdmissionsRules.conditionLabel(p))}<br><small>适用条件原文：${esc(p.applies_if.quote)} · ${esc(p.applies_if.locator)} · ${sourceLinks(p,p.applies_if)}</small></p>`:'';}
function renderOfficialEntries(prefs,valid){
  if(!valid||!prefs.school)return '<span class="muted">'+(!valid?'请修正学校或院系后查看对应官方招生入口。':'选择学校与院系，查看对应官方招生入口。')+'</span>';
  const entries=(ADMISSIONS_DATA.entries||[]).filter(e=>e.school===prefs.school&&(!e.dept||e.dept===prefs.dept)).sort((a,b)=>Number(!!a.dept)-Number(!!b.dept)||a.source_id.localeCompare(b.source_id));
  const ready=!!(prefs.year&&prefs.degree&&prefs.route&&prefs.track);
  const policies=AdmissionsRules.select(ADMISSIONS_DATA.policies,prefs).filter(p=>(prefs.dept||!p.dept)&&(!(p.level==='program'||p.track==='special'&&p.program)||prefs.program&&AdmissionsRules.programKey(p)===prefs.program));
  const policySources=new Set(policies.map(p=>p.source_id));
  const originals=policies.map(p=>{const source=ADMISSIONS_DATA.sources[p.source_id];if(!source)return '';const status=AdmissionsRules.quality(p,ADMISSIONS_DATA.checks);return `<article class="admission-entry" data-policy-entry="${esc(p.id)}"><a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(p.title)} · 官方原文 →</a><p class="stats">${!ready?esc(p.year+'入学 · '+degrees[p.degree]+' · '+routes[p.route]+' · '+(p.track==='special'?'专项':p.level==='school'?'学校通用':'普通招生'))+'；候选范围待核对。':''}${esc(labels[p.level])}${prefs.track==='special'&&p.level==='school'?' · 学校通用条款对专项适用仍待核对':''}；学校总则不能替代院系与专业要求。</p>${conditionNotice(p)}<p class="checklist-status ${status.state}">${esc(status.label)}</p><p class="policy-age">最近成功回源 ${esc(successfulSourceDate(p))} · ${reviewLabel(p)} ${esc(p.reviewed_at)}${confirmationLabel(p)}</p></article>`;}).join('');
  const renderEntry=entry=>{
    const source=ADMISSIONS_DATA.sources[entry.source_id];if(!source)return '';
    const status=entryStatus(entry),check=ADMISSIONS_DATA.checks[entry.source_id],unit=ADMISSIONS_DATA.units.find(u=>u.school===entry.school&&u.dept===entry.dept);
    const scope=[entry.year&&entry.year+'入学',degrees[entry.degree],routes[entry.route]].filter(Boolean).join(' · ');
    return `<article class="admission-entry" data-entry-source="${esc(entry.source_id)}"><a href="${esc(source.url)}" target="_blank" rel="noopener">${entry.dept?esc(unit?.dept_name||entry.dept):'学校'} · ${esc(source.label||'官方招生入口')} →</a><p class="stats">${esc(scope||'年度、学位及渠道范围未标定')}${entryScope(entry,prefs)==='unknown'?' · 仅作导航，适用范围须核对':' · 仍须核对普通／专项与具体专业'}</p><p class="checklist-status ${status.state}">${esc(status.label)}</p><p class="policy-age">${status.success?(status.state==='error'?'历史最近成功 ':'最近成功回源 ')+esc(status.success)+' · ':''}最近尝试 ${esc(check?.last_attempt||'尚无记录')} · 入口核对 ${esc(entry.reviewed_at||'未知')}</p>${entry.note?`<p class="stats">${esc(entry.note)}</p>`:''}</article>`;
  };
  const group=state=>entries.filter(e=>entryScope(e,prefs)===state&&(!policySources.has(e.source_id)||state==='other')).map(renderEntry).join('');
  const matching=group('matching'),unknown=group('unknown'),other=group('other');
  const legacy=!Object.hasOwn(ADMISSIONS_DATA,'entries')?ADMISSIONS_DATA.units.filter(u=>u.school===prefs.school&&(!prefs.dept||u.dept===prefs.dept)&&u.notice_url).map(u=>`<article class="admission-entry"><a href="${esc(u.notice_url)}" target="_blank" rel="noopener">${esc(u.dept_name)}官网招生栏目 →</a><p class="stats">旧栏目入口，尚无独立来源检查记录；范围待核对，申请前请核对官网。</p></article>`).join(''):'';
  const catalogs=(prefs.degree!=='master'?'<a href="https://yz.chsi.com.cn/bsmlcx/" target="_blank" rel="noopener">研招网博士专业目录 →</a><p class="stats">博士目录官网所示年度须另行核对，不能视为所选入学年度已发布。</p>':'')+(prefs.degree!=='phd'?'<a href="https://yz.chsi.com.cn/zsml/index.html" target="_blank" rel="noopener">研招网硕士专业目录 →</a><p class="stats">硕士目录年度及渠道须核对官网。</p>':'');
  return (originals?'<h4>'+(ready?'本目标政策原文':'候选政策原文，补全目标后核对适用')+'</h4>'+originals:'<p class="stats">'+(ready?'该目标暂无匹配政策原文摘要；请继续核对官方栏目，未整理不代表不招生。':'目标条件未完整，入口仅供浏览；补全年份、学位、渠道与招生范围后再核对政策原文。')+'</p>')+(matching?'<h4>年度、学位、渠道相符的入口</h4>'+matching:'')+(unknown||legacy?'<h4>范围待核对的官方导航</h4>'+unknown+legacy:'')+(other?'<details id="other-scope-entries"><summary>其他年度、学位或渠道入口（已知与所选条件不匹配）</summary>'+other+'</details>':'')+(!entries.length&&!originals&&!legacy?'<p class="muted">该范围官方招生入口尚未登记；未登记不代表不招生。</p>':'')+'<div class="entry-catalogs">'+catalogs+'</div>';
}
function renderLayerCoverage(prefs,valid,records){
  const conditionalCount=records.filter(p=>p.applies_if).length;
  records=records.filter(p=>!p.applies_if);
  const box=el('policy-layer-coverage');if(!box)return;
  if(!valid){box.innerHTML='<h2>当前目标的规则覆盖</h2><p>学校、院系或目标条件未收录/无效；院系未收录时不借用学校规则。</p>';return;}
  if(!prefs.school||!prefs.year||!prefs.degree||!prefs.route||!prefs.track){box.innerHTML='<h2>当前目标的规则覆盖</h2><p class="stats">补全学校、年度、学位、渠道和招生范围后，分别核对学校、院系与专业。下方仍可浏览官方入口和规则。</p>';return;}
  const isProgram=p=>p.level==='program'||p.track==='special'&&!!p.program;
  const schoolRows=records.filter(p=>p.level==='school'&&!isProgram(p)),deptRows=records.filter(p=>p.level==='dept'&&!isProgram(p)&&prefs.dept&&p.dept===prefs.dept),programRows=records.filter(p=>isProgram(p)&&prefs.program&&AdmissionsRules.programKey(p)===prefs.program);
  const unitKnown=ADMISSIONS_DATA.units.some(u=>u.school===prefs.school),reviewDue=records.filter(p=>AdmissionsRules.quality(p,ADMISSIONS_DATA.checks).state!=='checked').length;
  box.innerHTML=`<h2>当前目标的规则覆盖</h2><div class="layer-coverage-grid"><section><h3>学校规则</h3><p>${schoolRows.length?'学校规则已整理 · '+schoolRows.length+' 条摘要':'学校规则未整理，需查官方章程'}</p></section><section><h3>院系附加要求</h3><p>${!unitKnown?'院系目录待接入，附加要求待查':!prefs.dept?'院系尚未选择，不能判断院系覆盖':deptRows.length?'院系附加规则已整理 · '+deptRows.length+' 条摘要':'院系附加要求未整理，学校总则不能替代'}</p></section><section><h3>专业专属条款</h3><p>${!prefs.program?'专业未指定，专属条款不计覆盖':programRows.length?'专业专属规则已整理 · '+programRows.length+' 条摘要':'所选专业专属条款未整理，需查当年目录'}</p></section></div><p class="stats">条件性参考 ${conditionalCount} 条，不计无条件层级覆盖。已有摘要不代表条款齐全；报考点材料须按实际考点另行核对。${reviewDue?' '+reviewDue+' 条摘要来源或核对记录需复核。':''}</p>${prefs.track==='special'&&schoolRows.length?'<p class="quality">学校通用规则对专项适用仍待核实，须同时核对专项专属条件。</p>':''}`;
}
function policyTiming(policy){
  if(AdmissionsRules.cycle(policy).state==='historical')return {group:3,label:'历史参考，不作为本届申请条件'};
  const states=(policy.events||[]).filter(e=>e.kind==='deadline').map(e=>AdmissionsRules.eventState(e));
  if(states.includes('future'))return {group:0,label:'有尚未过去的已登记事项截止；不表示接受新报名'};
  if(!states.length||states.includes('unknown'))return {group:1,label:'事项截止时间未完整整理，需查官方通知；不表示接受新报名'};
  return {group:2,label:'已登记事项截止均已过；不能据此判断整轮招生是否结束'};
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
  return labels[p.level]+(p.program?' · '+p.program+' '+p.program_code:'')+(row.conditional?' · '+AdmissionsRules.conditionLabel(p,true)+'（不计当前目标覆盖）':'')+(prefs.track==='special'&&p.level==='school'?' · 专项适用性仍待核实':'');
}
function qualityShort(q){return q.method==='unchanged_source'?'原核验版本已复检':q.state==='checked'?'摘要版本已核对':'摘要需复核';}
function reviewLabel(p){return p.review_method==='automatic_evidence'?'自动证据核验':'人工摘要核对';}
function confirmationLabel(p){const q=AdmissionsRules.quality(p,ADMISSIONS_DATA.checks);return q.confirmed_at?' · 系统版本复检 '+esc(q.confirmed_at):'';}
function requirementPreview(text){
  const clauses=String(text).split(/(?<=[。；])/u).map(value=>value.trim()).filter(Boolean);
  return clauses.length>1?'<ul class="checklist-preview checklist-clauses">'+clauses.map(value=>'<li>'+esc(value)+'</li>').join('')+'</ul>':'<p class="checklist-preview">'+esc(text)+'</p>';
}
function checklistItem(item,prefs,events=[]){
  const known=item.rows.filter(row=>row.field),unknown=item.rows.filter(row=>!row.field);
  const first=known.find(row=>!row.conditional)||known[0],warnings=item.rows.some(row=>row.quality.state!=='checked');
  const previewRows=item.key==='eligibility'?known:first?[first]:[];
  const preview=previewRows.length?previewRows.map(row=>`<p class="checklist-scope">${esc(checklistScope(row,prefs))}</p>${requirementPreview(row.field.text)}`).join('')+(item.key!=='eligibility'&&known.length>1?`<p class="checklist-scope">另有 ${known.length-1} 条相关要求，展开核对；不同材料阶段不可互代。</p>`:''):'<p class="checklist-preview muted">尚无明确摘要，请查官方原文。</p>';
  const pending=unknown.length?`<p class="checklist-scope">${unknown.length} 项政策未整理此项，不代表没有要求。</p>`:'';
  const evidence=item.rows.map(row=>{const p=row.policy,f=row.field;return `<div class="checklist-row" data-checklist-policy="${esc(p.id)}"><p class="scope">${esc(checklistScope(row,prefs))} · <a href="#policy-${esc(p.id)}">查看政策摘要</a></p>${f?`<p>${esc(f.text)}</p><blockquote>原文短片段：${esc(f.quote)}<br>定位：${esc(f.locator)}</blockquote>`:'<p class="muted">本层未整理，待查原文。</p>'}${sourceLinks(p,f)}<p class="checklist-status ${row.quality.state}">${esc(row.quality.label)}</p></div>`;}).join('');
  const ordered=[...events].sort((a,b)=>Number(a.state!=='future')-Number(b.state!=='future')||String(a.event.at).localeCompare(String(b.event.at)));
  const next=ordered.find(row=>!row.conditional&&row.state==='future'&&row.event.kind==='deadline')||ordered.find(row=>!row.conditional&&row.state==='future')||ordered.find(row=>!row.conditional)||ordered[0];
  const eventPreview=next?`<p class="checklist-date">${esc(next.event.at)}</p><p class="checklist-time-label">${esc(next.event.label)}</p><p class="checklist-scope">${esc(next.conditional?checklistScope(next,prefs)+'；':'')}${esc(eventTiming(next.event,next.state))}</p>`:'';
  const eventDetails=events.length?`<div id="checklist-events"><h4>已登记时间与原文</h4>${events.map(row=>`<div class="checklist-row"><p>${esc(checklistScope(row,prefs))} · ${esc(row.policy.title)}</p><p>${esc(row.event.label)} · ${esc(row.event.at)} · ${esc(eventTiming(row.event,row.state))}</p><blockquote>${esc(row.event.quote)} · ${esc(row.event.locator)}</blockquote>${sourceLinks(row.policy,row.event)}</div>`).join('')}</div>`:'';
  return `<section class="checklist-field" data-checklist-field="${item.key}"><h3>${item.key==='timeline'?'时间与截止':fields[item.key]}</h3>${eventPreview||preview}${warnings?'<p class="checklist-status">部分来源或摘要需重新核对</p>':''}${pending}${evidence||eventDetails?`<details><summary>展开完整要求与官方依据</summary>${evidence}${eventDetails}</details>`:'<a href="#official-entry-details">查官方招生入口 →</a>'}</section>`;
}
function renderChecklist(prefs,valid){
  const result=AdmissionsRules.checklist(ADMISSIONS_DATA,prefs),names={school:'学校',dept:'院系',year:'入学年度',degree:'学位',route:'渠道',track:'普通／专项范围'};
  if(!valid||!result.ready){
    el('application-checklist').innerHTML=`<div class="checklist-empty"><div><h2>核对你的申请要求</h2><p id="checklist-prompt">${result.missing.length?'再选择'+esc(result.missing.map(key=>names[key]).join('、'))+'，即可按目标核对条件、材料与时间。':'学校、院系或年度无效，请先修正申请目标。'}下方政策仍可按需浏览。</p></div><button type="button" data-configure-target>完善申请目标</button></div>`;
    return;
  }
  const query=scopeQuery(prefs),primary=new Set(['eligibility','materials','timeline']);
  el('application-checklist').innerHTML=`<div class="checklist-heading"><div><h2>申请前先核对这三项</h2><p class="checklist-target">${esc(prefs.year)}入学 · ${degrees[prefs.degree]} · ${routes[prefs.route]} · ${prefs.track==='special'?'专项/特定项目':'普通招生'}${prefs.program?' · '+esc(prefs.program.replace('|',' · ')):' · 专业尚未指定'}</p></div><div class="actions"><a id="checklist-project" class="primary" href="applications.html?${query}">准备申请 →</a><a id="checklist-mentors" href="discovery.html?${query}">带目标找导师</a></div></div><p class="checklist-help">${AdmissionsRules.cycle(prefs).state==='historical'?'当前所选为历史申请周期，仅供参考，不作为本届条件。':'以下为已整理的要求摘录，展开后核对完整条款与适用范围。'}</p>${!result.policies.length?'<p class="quality">平台尚无该目标的已核验政策摘要；这不表示学校尚未发布。请核对官方入口，不借用往年或其他渠道要求。</p>':''}<div class="checklist-fields">${result.items.filter(item=>primary.has(item.key)).map(item=>checklistItem(item,prefs,item.key==='timeline'?result.events:[])).join('')}</div><details class="checklist-extra"><summary>考核、学费、奖助、招生计划与咨询方式</summary><div class="checklist-fields">${result.items.filter(item=>!primary.has(item.key)).map(item=>checklistItem(item,prefs)).join('')}</div><p class="checklist-mentor">学校、院系与专业要求须一起核对；${prefs.program?'专业缺少摘要时仍须查当年目录。':'专业尚未指定，专业条款仅作参考。'}导师资格、个人联系方式和当年名额须另查导师及院系资料。</p><a id="checklist-notices" href="notices.html?${query}">查看院系招生通知 →</a><p class="stats">“准备申请”仅预填目标，明确保存后才写入私人记录。</p></details>`;
}
function revealTarget(hash=location.hash){
  if(waitingForSchool){revealPending=true;return;}
  let id;try{id=decodeURIComponent(hash.replace(/^#/,''));}catch{return;}
  const target=el(id);if(!target)return;
  for(let node=target;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;
  if(target.matches('.policy-card'))target.querySelector('.policy-body').open=true;
  requestAnimationFrame(()=>{target.scrollIntoView({block:'start'});target.tabIndex=-1;target.focus({preventScroll:true});});
}

function render(loaded=true){
  const prefs=criteria();
  el('policy-results').hidden=!loaded||!prefs.school;el('policy-welcome').hidden=!!prefs.school;
  const advanced=[prefs.track==='ordinary'?'普通招生':prefs.track==='special'?'专项/特定项目':'',prefs.program?prefs.program.replace('|',' · '):'',prefs.group?ADMISSIONS_DATA.groups[prefs.group]||prefs.group:''].filter(Boolean);
  el('policy-target-more-label').textContent=advanced.length?'已限定：'+advanced.join(' · '):'进一步限定：普通／专项、专业与相关院系';
  visibleUnits=ADMISSIONS_DATA.units.filter(u=>!prefs.group||u.groups.includes(prefs.group));const units=visibleUnits.filter(u=>(!prefs.school||u.school===prefs.school)&&(!prefs.dept||u.dept===prefs.dept));
  const valid=!invalidYear&&(!prefs.group||Object.hasOwn(ADMISSIONS_DATA.groups,prefs.group))&&(!prefs.track||['ordinary','special'].includes(prefs.track))&&(!prefs.degree||Object.hasOwn(degrees,prefs.degree))&&(!prefs.route||Object.hasOwn(routes,prefs.route))&&(!prefs.school||schools.some(s=>s[0]===prefs.school))&&(!prefs.dept||units.length>0)&&(!prefs.year||Number.isInteger(Number(prefs.year))&&Number(prefs.year)>=2000&&Number(prefs.year)<=2100);
  const isProgram=p=>p.level==='program'||p.track==='special'&&!!p.program;
  const matching=valid?AdmissionsRules.select(loaded?ADMISSIONS_DATA.policies:policyCatalog,prefs).filter(p=>!prefs.group||visibleUnits.some(u=>u.school===p.school&&(!p.dept||u.dept===p.dept))).sort((a,b)=>policyTiming(a).group-policyTiming(b).group||b.year-a.year||String(b.reviewed_at||'').localeCompare(a.reviewed_at||'')||a.id.localeCompare(b.id)):[];
  options(el('policy-program'),[...new Map(matching.filter(isProgram).map(p=>[AdmissionsRules.programKey(p),p.program+' '+p.program_code])).entries()].sort((a,b)=>a[0].localeCompare(b[0],'zh-CN')),'未指定（专业要求待核对）',prefs.program);
  const records=matching.filter(p=>!prefs.program||!isProgram(p)||AdmissionsRules.programKey(p)===prefs.program);
  const schoolsCovered=new Set(policyCatalog.map(p=>p.school)).size,unitsCovered=new Set(policyCatalog.filter(p=>p.dept).map(p=>p.school+'/'+p.dept)).size;
  el('policy-coverage').textContent=`配置目标 ${schools.length} 校，${new Set(ADMISSIONS_DATA.units.map(u=>u.school)).size} 校已接入 ${ADMISSIONS_DATA.units.length} 个院系；规则摘要 ${schoolsCovered} 校 / ${unitsCovered} 院系 / ${policyCatalog.length} 条。已接入单位、已整理规则与来源可用是不同范围，不表示招生政策完整。`;
  el('school-directory').innerHTML=schools.filter(([id])=>!prefs.group||visibleUnits.some(u=>u.school===id)).map(([id,name])=>{const rows=visibleUnits.filter(u=>u.school===id);return `<button data-school="${esc(id)}" ${prefs.school===id?'aria-current="true"':''}>${esc(name)}<br><small>${rows.length?rows.length+' 院系 · '+rows.reduce((n,u)=>n+(u.count||0),0)+' 位本库导师':'院系目录待接入'}</small></button>`;}).join('');
  el('unit-directory-list').innerHTML=units.map(u=>`<button data-unit-school="${esc(u.school)}" data-unit-dept="${esc(u.dept)}">${esc(u.dept_name)}<br><small>导师记录 ${u.count||'待补'} · 通知${u.notice_url?'已接入':'待补'} · 人工规则 ${policyCatalog.filter(p=>p.school===u.school&&p.dept===u.dept).length}</small></button>`).join('');
  const query=scopeQuery(prefs);if(invalidYear)query.set('year',incoming.get('year'));history.replaceState(null,'',location.pathname+(query.size?'?'+query:'')+location.hash);for(const a of document.querySelectorAll('.site-header a[href]')){const path=a.getAttribute('href').split('?')[0];if(['discovery.html','compare.html','admissions.html','notices.html','desk.html','applications.html'].includes(path))a.href=path+'?'+query;}el('unit-mentors').href='discovery.html?'+query;el('unit-mentors').hidden=!valid||!units.length;
  el('unit-notices').href='notices.html?'+query;el('unit-notices').hidden=!valid||!prefs.school||!prefs.dept;
  if(!loaded){
    for(const id of ['policy-list','application-checklist','unit-entries','policy-layer-coverage','unit-readiness','unit-catalog'])el(id).replaceChildren();
    return;
  }
  renderChecklist(prefs,valid);
  renderLayerCoverage(prefs,valid,records);
  el('unit-catalog').innerHTML=(prefs.school?units:[]).map(u=>`<a href="${esc(u.roster_url)}" target="_blank" rel="noopener">${esc(u.dept_name)}官方师资入口</a>`).join(' · ');
  el('unit-name').textContent=(schools.find(s=>s[0]===prefs.school)?.[1]||'学校与院系')+(prefs.dept?' · '+(units[0]?.dept_name||prefs.dept):'');
  el('unit-description').textContent=valid?(prefs.school&&!ADMISSIONS_DATA.units.some(u=>u.school===prefs.school)?'院系目录待补，请核对学校官方招生信息。':prefs.dept?'学校总则与院系、专业要求须一起核对。':`${units.length} 个相关院系可选；选定院系后可核对附加要求。`):'学校、院系或年度无效，请修正目标。';
  el('unit-readiness').innerHTML=valid&&prefs.school?units.map(u=>unitInfo(u,prefs)).join(''):'<p class="stats">选择学校或院系，查看邮箱、方向、简介及导师资格的信息覆盖，再决定从哪里开始找导师。</p>';
  el('unit-entries').innerHTML=renderOfficialEntries(prefs,valid);
  el('policy-count').textContent=`${records.length} 条相关政策 · ${invalidYear?'年度无效':prefs.year?prefs.year+'入学':'全部年度'} · ${routes[prefs.route]||'全部渠道'}`;
  el('policy-list').innerHTML=(prefs.school?records:[]).map(p=>{
    const source=ADMISSIONS_DATA.sources[p.source_id],quality=AdmissionsRules.quality(p,ADMISSIONS_DATA.checks),school=schools.find(s=>s[0]===p.school)?.[1]||p.school,unit=ADMISSIONS_DATA.units.find(u=>u.school===p.school&&u.dept===p.dept);
    const project=projectQuery(p,prefs);
    const cycle=AdmissionsRules.cycle(p),timing=policyTiming(p),brief=timing.group===0?'有未过事项截止':timing.group===2?'已登记事项截止已过':'事项截止待核对';
    return `<article class="policy-card" id="policy-${esc(p.id)}" data-policy="${esc(p.id)}"><p class="scope">${p.applies_if&&p.level==='school'?'学校层条件要求':labels[p.level]} · ${esc(school)} ${esc(unit?.dept_name||'')} · ${p.year}入学 · ${degrees[p.degree]} · ${routes[p.route]}${p.program?' · '+esc(p.program)+' '+esc(p.program_code):''}</p><h2>${esc(p.title)}</h2>${p.applies_if?`<p class="policy-condition">${esc(AdmissionsRules.conditionLabel(p))}</p>`:''}<p class="scope policy-cycle">${esc(cycle.label)}</p><div class="policy-card-meta"><span class="policy-quality ${quality.state}">${qualityShort(quality)}</span><span class="policy-age">${reviewLabel(p)} ${esc(p.reviewed_at||'未知')}${confirmationLabel(p)}</span>${cycle.state==='historical'?'':`<span class="policy-age">${brief}，不代表正在报名</span>`}</div><details class="policy-body"><summary>查看要求、材料与官方依据</summary><div class="policy-body-content"><p class="scope">适用范围：${p.applies_if?'须满足上列适用条件，不能作为该校所有考生的通用要求':p.track==='special'?(esc(p.program)||'专项（具体类型需核对）'):p.level==='school'?'学校通用，专项仍须核实适用':'普通招生'}</p>${conditionNotice(p)}<div class="quality ${quality.state}">${quality.label}</div>${window.MaterialPreparation?.publicActions(p,ADMISSIONS_DATA)||''}${p.material_actions?.length?`<div class="actions"><a class="primary" href="applications.html?${project}&section=preparation">按要求准备材料 →</a></div>`:''}<div class="policy-fields">${Object.entries(fields).map(([key,label])=>{const f=p.fields[key];return `<section class="policy-field"><h3>${label}</h3>${f?`<p>${esc(f.text)}</p><details><summary>官方原句与出处</summary><blockquote>${esc(f.quote)}<br>定位：${esc(f.locator)} · ${sourceLinks(p,f)}</blockquote></details>`:'<p class="muted">尚未整理，请核对原文。</p>'}</section>`;}).join('')}</div>${(p.events||[]).length?`<details class="policy-evidence"><summary>查看全部时间安排与依据</summary>${(p.events||[]).map(e=>`<p class="quality">${esc(e.label)} · ${esc(e.at)} · ${esc(eventTiming(e))}<br><small>原文：${esc(e.quote)} · ${esc(e.locator)} · ${sourceLinks(p,e)}</small></p>`).join('')}</details>`:''}<details class="policy-evidence"><summary>来源与更新时间 · ${Object.keys(p.fields).length}/8 类摘要</summary><p class="policy-age">官方发布 ${esc(p.published_at||'未知')} · 最近成功回源 ${esc(successfulSourceDate(p))} · ${reviewLabel(p)} ${esc(p.reviewed_at||'未知')}${confirmationLabel(p)}。已整理不代表条款完整。</p><p class="policy-age">${Object.keys(p.review_hashes).map(id=>{const s=ADMISSIONS_DATA.sources[id],c=ADMISSIONS_DATA.checks[id];return `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.label||(s.format==='pdf'?'PDF原文':'通知正文/附件入口'))}</a> · 最近成功检查 ${esc(c?.last_success||'无')} · 最近尝试 ${esc(c?.last_attempt||'无')}${c?.cached?'（缓存读取）':''}`;}).join('<br>')}</p></details><div class="actions"><a href="${esc(source.url)}" target="_blank" rel="noopener">核对完整政策 ↗</a><a href="applications.html?${project}">建立申请项目 →</a></div></div></details></article>`;
  }).join('')||'<p class="empty">平台尚无符合所选学校、院系、年度和渠道的已核验要求；这不表示学校尚未发布。请从官方招生入口核实，往年规则仅作参考。</p>';
}
function finishSchool(){
  waitingForSchool=false;
  el('policy-data-status').hidden=true;
  render();
  if(revealPending){revealPending=false;revealTarget();}
  window.ADMISSIONS_READY=true;
}
function readSchool(school){
  if(!schoolRequests.has(school)){
    const version=schoolVersions[school];
    const pending=OnlineAccount.readJSON(`admissions/${encodeURIComponent(school)}.json?v=${version}`).then(({response,data})=>{
      if(!response.ok||!data||data.school!==school)throw new Error('无法读取所选学校的政策');
      if(data.revision!==version)throw Object.assign(new Error('已发布新版本'),{updated:true});
      if(!Array.isArray(data.policies)||!Array.isArray(data.entries)||!data.sources||!data.checks)throw new Error('政策资料不完整');
      return data;
    }).catch(error=>{schoolRequests.delete(school);throw error;});
    schoolRequests.set(school,pending);
  }
  return schoolRequests.get(school);
}
async function applySchool(){
  const request=++schoolRequest,school=el('policy-school').value;
  if(!schoolVersions)return finishSchool();
  if(!Object.hasOwn(schoolVersions,school)){
    currentSchool='';
    Object.assign(ADMISSIONS_DATA,{policies:policyCatalog,entries:[],sources:{},checks:{}});
    return finishSchool();
  }
  if(school===currentSchool)return finishSchool();
  waitingForSchool=true;
  render(false);
  el('policy-data-status').hidden=false;
  el('policy-data-message').textContent='正在读取所选学校的申请要求…';
  const retry=el('policy-data-retry');retry.hidden=true;
  try{
    const {policies,entries,sources,checks}=await readSchool(school);
    if(request!==schoolRequest)return;
    Object.assign(ADMISSIONS_DATA,{policies,entries,sources,checks});
    currentSchool=school;
    finishSchool();
  }catch(error){
    if(request!==schoolRequest)return;
    waitingForSchool=false;
    el('policy-data-message').textContent=error.updated?'政策资料已更新，请刷新本页后核对。':error.timedOut?'读取所选学校的要求超时，请重试。':'暂时无法读取所选学校的要求，请重试。';
    retry.hidden=false;
    retry.textContent=error.updated?'刷新页面':'重新读取';
    retry.onclick=error.updated?()=>location.reload():applySchool;
  }
}
const incoming=new URLSearchParams(location.search);options(el('policy-school'),schools,'全部学校',incoming.get('school')||'');depts(incoming.get('dept')||'');
const rawYear=incoming.get('year')||'';invalidYear=!!rawYear&&(!/^\d{4}$/.test(rawYear)||Number(rawYear)<2000||Number(rawYear)>2100);el('policy-year').value=invalidYear?'':rawYear;
options(el('policy-group'),Object.entries(ADMISSIONS_DATA.groups),'全部相关院系',incoming.get('group')||'');options(el('policy-track'),[['ordinary','普通招生'],['special','专项/特定项目']],'全部范围',incoming.get('track')||'');depts(incoming.get('dept')||'');
options(el('policy-program'),[],'未指定（专业要求待核对）',incoming.get('program')||'');
for(const key of ['degree','route']){const select=el('policy-'+key),value=incoming.get(key)||'';if(value&&!Array.from(select.options).some(o=>o.value===value))select.add(new Option(value+'（未知）',value));select.value=value;}
function clearUnitProject(){el('policy-program').value='';if(el('policy-track').value==='special')el('policy-track').value='';}
el('policy-school').onchange=()=>{depts();clearUnitProject();applySchool();};for(const id of ['policy-dept','policy-year','policy-degree','policy-route','policy-track','policy-program'])el(id).onchange=()=>{if(id==='policy-year')invalidYear=false;if(id!=='policy-program')el('policy-program').value='';if(id==='policy-dept')clearUnitProject();applySchool();};
el('school-directory').onclick=event=>{const button=event.target.closest('[data-school]');if(button){el('policy-school').value=button.dataset.school;depts();clearUnitProject();applySchool();}};
el('policy-group').onchange=()=>{el('policy-school').value='';depts();clearUnitProject();applySchool();};el('unit-directory-list').onclick=event=>{const b=event.target.closest('[data-unit-school]');if(b){el('policy-school').value=b.dataset.unitSchool;depts(b.dataset.unitDept);clearUnitProject();applySchool();}};
el('school-shortcuts').innerHTML=schools.slice(0,8).map(([id,name])=>`<button type="button" data-school="${esc(id)}">${esc(name)}</button>`).join('');
el('school-shortcuts').onclick=el('school-directory').onclick;
el('application-checklist').addEventListener('click',event=>{if(event.target.closest('[data-configure-target]')){el('policy-target-more').open=true;const missing=['school','dept','year','degree','route','track'].find(key=>!el('policy-'+key).value);el('policy-'+(missing||'school')).focus();}});
document.addEventListener('click',event=>{const a=event.target.closest('a[href^="#"]');if(a){event.preventDefault();history.replaceState(null,'',location.pathname+location.search+a.getAttribute('href'));revealTarget(a.getAttribute('href'));}});
window.addEventListener('hashchange',()=>revealTarget());
applySchool();

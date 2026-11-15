const oe=id=>document.getElementById(id), ox=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let opportunityRows=window.OPPORTUNITIES.opportunities, savingOpportunity=null, savedOpportunities=new Map(), saveBusy=false, publicOpportunityMode=false, opportunityModeReady=false, opportunityCatalog=window.OPPORTUNITIES;
const opportunityTime=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未知';
const opportunityParams=new URLSearchParams(location.search), opportunityToday=OpportunityRules.dayOf(new Date().toISOString());
function opportunityFacts(o){return `<div class="opportunity-facts"><div><span class="muted">报名截止</span><strong>${ox(o.deadline||'具体日期待确认')}${o.deadline?.length===10?'（未注明时刻）':''}</strong></div>${o.graduation_year?`<div><span class="muted">面向届别</span><strong>${ox(o.graduation_year)} 届本科生</strong></div>`:''}${o.event_start||o.event_end?`<div><span class="muted">活动时间</span><strong>${ox(o.event_start||'开始日期待核对')}${o.event_end?' 至 '+ox(o.event_end):''}</strong></div>`:''}</div>`;}

function opportunityList(items,empty){return items.length?'<ul>'+items.map(s=>'<li>'+ox(s)+'</li>').join('')+'</ul>':'<p class="muted">'+empty+'</p>';}
function opportunityDirections(o,query=''){
  const directions=o.research_directions||[];if(!directions.length)return '';
  const q=query.trim().toLowerCase(),matching=directions.filter(r=>[r.department,r.direction,r.contact,r.email].join(' ').toLowerCase().includes(q));
  const rows=q&&matching.length?matching:directions;
  return `<details class="opportunity-details" ${q&&matching.length?'open':''}><summary>研究方向与联系 ${directions.length} 项${q&&matching.length?' · 命中 '+matching.length+' 项':''}</summary><p class="muted">以下为官方公布的部门联系人，不等于已确认导师名额。先核对项目条件，再联系对应方向。</p>`+rows.map(r=>`<section class="research-direction"><h3>${ox(r.direction)}</h3><p>${ox(r.department)} · ${ox(r.contact||'联系人姓名未公布')}</p>${r.email?`<a href="mailto:${encodeURIComponent(r.email)}?subject=${encodeURIComponent('咨询'+o.title+'：'+r.direction)}">写邮件给 ${ox(r.email)} ↗</a>`:'<p>未公布邮箱，请通过官方通知咨询。</p>'}<p><small><a href="${ox(r.source_url)}" target="_blank" rel="noopener">官方出处 ↗</a> · ${ox(r.source_locator)} · 核对 ${ox(r.verified_at)}</small></p></section>`).join('')+'</details>';
}
function opportunityDocuments(o){
  const names={eligibility:'申请条件',materials:'材料',deadline:'截止时间',registration_start:'报名开始',application_method:'报名方式',contact:'联系渠道'};
  return (o.source_documents||[]).map(doc=>`<p><a href="${ox(doc.url)}" target="_blank" rel="noopener">官方 PDF 原文 ↗</a> · ${ox(doc.page_count)} 页 · 核对 ${ox(doc.checked_at)}</p><ul>${Object.entries(doc.field_evidence).map(([field,evidence])=>`<li>${ox(names[field]||'原文依据')} · 第 ${evidence.pages.map(ox).join('、')} 页：${ox(evidence.quote)}</li>`).join('')}</ul>`).join('');
}
function renderOpportunities(){
  const filter={query:oe('opportunity-search').value,kind:oe('opportunity-kind').value,school:oe('opportunity-school').value,year:oe('opportunity-year').value,status:oe('opportunity-state').value};
  let rows=OpportunityRules.select(opportunityRows,filter);
  const focus=opportunityParams.get('id');if(focus)rows=rows.filter(o=>o.id===focus);
  oe('opportunity-count').textContent=`${rows.length} 条活动 · ${rows.filter(o=>OpportunityRules.state(o)==='open').length} 条已核对报名时间内`;
  oe('opportunity-list').innerHTML=(focus?'<p class="opportunity-back"><a href="opportunities.html">← 返回全部保研机会</a></p>':'')+(rows.length?rows.map(o=>{
    const state=OpportunityRules.state(o),saved=savedOpportunities.get(o.id);
    return `<article class="opportunity-card" data-opportunity="${ox(o.id)}"><div class="opportunity-meta"><span class="opportunity-state ${state}">${OpportunityRules.labels[state]}</span><span class="muted">${OpportunityRules.kinds[o.kind]} · ${ox(o.unit)}</span></div><h2>${ox(o.title)}</h2><p class="opportunity-cohort"><strong>${o.graduation_year?ox(o.graduation_year)+" 届本科生":"适用毕业届别未明确，请核对原文年级条件"}</strong>${o.camp_year?" · 活动举办于 "+ox(o.camp_year)+" 年":""}${o.admission_year?" · 研究生入学 "+ox(o.admission_year)+" 年":""}</p>${opportunityFacts(o)}${!o.deadline&&o.deadline_note?`<p class="hint">${ox(o.deadline_note)}</p>`:""}${o.source_state!=='verified'?'<p class="hint">当前资料待复核，报名状态未确认。请先核实官方原文及报名入口。</p>':state==='review'?'<p class="hint">来源检查或内容核验已超期；当前是否仍接受报名，需再查官方通知。</p>':''}<p>${ox(o.eligibility[0]||'申请条件尚未整理，请查看原文。')}</p>${filter.year?`<p class="muted">${o.graduation_year?'届别与选择一致，其他申请条件仍需逐项核对。':'原文未明确届别，暂保留供核对；不表示符合申请条件。'}</p>`:''}<div class="opportunity-actions"><a href="${ox(o.source_url)}" target="_blank" rel="noopener">查看官方通知 ↗</a>${publicOpportunityMode?`<a href="local.html?id=${encodeURIComponent(o.id)}">在本机准备申请 →</a>`:saved?`<a href="applications.html?project=${ox(saved)}">查看我的项目 →</a>`:`<button type="button" data-save-opportunity="${ox(o.id)}" ${opportunityModeReady?'':'disabled'}>${opportunityModeReady?(state==='closed'?'保存作准备参考':'加入我的申请'):'正在连接工作台…'}</button>`}</div>${opportunityDirections(o,filter.query)}<details class="opportunity-details"><summary>申请条件、材料与报名方式</summary><h3>申请条件</h3>${opportunityList(o.eligibility,'未整理完整条件，不代表没有限制。')}<h3>材料与提交阶段</h3>${opportunityList(o.materials,'本次未取得明确材料清单，请查原文。')}<p>${ox(o.application_method)}</p>${o.evidence.filter(v=>/^https?:\/\/[^\s]+\.(xlsx?|pdf|docx?)(?:\?.*)?$/i.test(v)).map(url=>`<p><a href="${ox(url)}" target="_blank" rel="noopener">查看官方附件（方向、联系人或申请材料） ↗</a></p>`).join('')}${o.source_state==='verified'&&o.application_url?`<p><a href="${ox(o.application_url)}" target="_blank" rel="noopener">前往官方通知指定的报名入口 ↗</a></p>`:''}<p>${ox(o.contact)}</p><p>${ox(o.admission_note)}</p><p class="muted">活动年份 ${o.camp_year||'未明确'} · 研究生入学年份 ${o.admission_year||'未确认，不由活动年份推断'}</p><details><summary>核对依据与来源时间</summary><p>发布：${ox(o.published_at||'未明确')} · 摘要核验：${ox(o.verified_at)} · 来源成功检查：${ox(o.checked_at||'尚未成功')}</p><p>${ox(o.source_note)}</p>${opportunityList(o.evidence,'未记录依据。')}${opportunityDocuments(o)}<p>${ox(o.deadline_note)}</p></details></details></article>`;
  }).join(''):'<div class="opportunity-empty">没有符合条件的活动。未收录不代表院校未发布。<p><button type="button" id="opportunity-reset">清除筛选，查看当前线索</button> <button type="button" id="opportunity-history">查看历史参考</button></p><a href="notices.html">查看官方招生通知栏目 →</a></div>');
  oe('opportunity-coverage').textContent=(opportunityCatalog.coverage_note||'当前来源范围待说明')+' 最近整理：'+(opportunityCatalog.checked_at||'未知')+'。';
}
function refreshOpportunityOptions(){
  for(const [key,values,label] of [['year',[...new Set(opportunityRows.map(o=>o.graduation_year).filter(Boolean))].sort(),'全部届别'],['school',[...new Set(opportunityRows.map(o=>o.school_name))].sort(),'全部学校']]){
    const select=oe('opportunity-'+key),old=select.value;
    select.replaceChildren(new Option(label,''));
    for(const value of values)select.add(new Option(key==='year'?value+' 届':value,value));
    if(old&&![...select.options].some(o=>o.value===old))select.add(new Option(old+'（当前目录未收录）',old));
    select.value=old;
  }
}
refreshOpportunityOptions();
for(const key of ['kind','school','year','state']){const value=opportunityParams.get(key)?.slice(0,100),select=oe('opportunity-'+key);if(value&&(key==='school'||key==='year')&&![...select.options].some(o=>o.value===value))select.add(new Option(value+'（当前目录未收录）',value));if(value&&[...select.options].some(o=>o.value===value))select.value=value;select.onchange=renderOpportunities;}
if(opportunityParams.has('id'))oe('opportunity-state').value='all';
if(opportunityParams.has('query'))oe('opportunity-search').value=opportunityParams.get('query').slice(0,200);
oe('opportunity-search').oninput=renderOpportunities;
document.addEventListener('click',e=>{
  if(e.target.id==='opportunity-reset'||e.target.id==='opportunity-history'){for(const key of ['kind','school','year','search'])oe('opportunity-'+key).value='';opportunityParams.delete('id');oe('opportunity-state').value=e.target.id==='opportunity-history'?'closed':'current';renderOpportunities();}
  const button=e.target.closest('[data-save-opportunity]');if(!button)return;
  if(publicOpportunityMode){oe('opportunity-result').textContent='这是公开浏览站点。私人项目、材料与提醒请在本机版保存；这里不会接收你的申请资料。';oe('opportunity-result').scrollIntoView({block:'center'});return;}
  if(!['http:','https:'].includes(location.protocol)){oe('opportunity-result').textContent='请启动本机服务后保存项目；现在仍可浏览官方通知。';return;}
  savingOpportunity=opportunityRows.find(o=>o.id===button.dataset.saveOpportunity);
  oe('opportunity-name').value=savingOpportunity.title;oe('opportunity-reminder').value='';oe('opportunity-reminder').min=opportunityToday;
  oe('opportunity-reminder').max=OpportunityRules.state(savingOpportunity)==='open'?savingOpportunity.deadline.slice(0,10):'';
  oe('opportunity-save-hint').textContent=OpportunityRules.state(savingOpportunity)==='open'?'报名截止：'+savingOpportunity.deadline+'。建议在截止前留出材料准备时间。':'当前不是已确认开放的报名机会。可保存作参考，并安排个人核对提醒。';oe('save-message').textContent='';oe('opportunity-save').showModal();
});
oe('opportunity-cancel').onclick=()=>{if(!saveBusy)oe('opportunity-save').close();};
oe('opportunity-save').addEventListener('cancel',e=>{if(saveBusy)e.preventDefault();});
oe('opportunity-form').onsubmit=async e=>{
  e.preventDefault();if(saveBusy)return;saveBusy=true;oe('opportunity-confirm').disabled=true;
  try{const r=await fetch('/api/workflow/opportunities',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opportunity_id:savingOpportunity.id,name:oe('opportunity-name').value,reminder_date:oe('opportunity-reminder').value})});const result=await r.json();if(!r.ok)throw new Error(result.error||'保存失败');savedOpportunities.set(savingOpportunity.id,result.project_id);oe('opportunity-save').close();renderOpportunities();oe('opportunity-result').innerHTML=(result.duplicate?'这项活动已经保存，未重复创建。':'项目已保存，条件、材料和日期快照已关联。')+` <a href="applications.html?project=${ox(result.project_id)}">打开项目，关联材料 →</a>`;oe('opportunity-result').scrollIntoView({block:'center'});}
  catch(error){oe('save-message').textContent=error.message+'。未确认保存成功，请重试；重复操作不会创建第二个项目。';}
  finally{saveBusy=false;oe('opportunity-confirm').disabled=false;}
};
renderOpportunities();
function loadSavedOpportunities(){return fetch('/api/workflow').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{for(const p of Object.values(data.projects||{}))if(p.opportunity)savedOpportunities.set(p.opportunity.id,p.id);renderOpportunities();}).catch(()=>{oe('opportunity-result').textContent='本机工作台暂不可读取；仍可查阅活动，保存失败时请重试。';});}
async function refreshOpportunityMonitor(){
  if(!['http:','https:'].includes(location.protocol)){oe('monitor-health').textContent='静态浏览模式：未连接监测服务，请启动本机服务查看更新状态。';return;}
  oe('monitor-refresh').disabled=true;
  try{
    const response=await fetch('/api/opportunities');if(!response.ok)throw new Error('读取失败');const data=await response.json();opportunityCatalog=data;opportunityRows=data.opportunities;publicOpportunityMode=data.mode==='public';opportunityModeReady=true;refreshOpportunityOptions();if(publicOpportunityMode)oe('opportunity-result').textContent='公开浏览模式：信息由服务器定时监测；私人项目、材料与提醒在本机版保存。';renderOpportunities();
    if(!publicOpportunityMode)await loadSavedOpportunities();
    if(data.feed_error)oe('opportunity-result').textContent=data.feed_error;
    const m=data.monitoring;
    if(!m){oe('monitor-health').textContent=publicOpportunityMode?'服务器尚无可用监测记录，当前页面不能确认信息已更新。请直接核对官方通知。':'尚无监测记录。运行“启动信息监测.cmd”后，每 6 小时检查已配置的官方栏目。电脑休眠或程序关闭期间不会更新。';oe('monitor-list').replaceChildren();oe('monitor-sources').replaceChildren();return;}
    const overdue=!m.next_check_at||Date.parse(m.next_check_at)<Date.now(),sum=m.summary||{};
    oe('monitor-health').textContent=(overdue?'监测已超出应检时间，请检查监测程序。':'最近一轮监测已完成；这不代表所有信息已核验。')+' 最近检查：'+opportunityTime(m.checked_at)+'；下次应检：'+opportunityTime(m.next_check_at)+'（北京时间）。成功栏目 '+(sum.sources_ok||0)+' / '+(sum.source_count||0)+'；失败 '+(sum.sources_error||0)+'。本轮新发现 '+(sum.new_count||0)+' 条。';
    oe('monitor-sources').innerHTML=Object.values(m.sources||{}).filter(s=>s.status!=='removed').map(s=>`<p><a href="${ox(s.url)}" target="_blank" rel="noopener">${ox(s.unit||'官方招生栏目')}</a> · ${s.status==='ok'?'最近检查成功':'暂时无法读取，请直接查官网'}<br><small>最近成功：${ox(opportunityTime(s.last_success))}</small></p>`).join('')||'<p>暂无来源记录。</p>';
    const candidate=opportunityParams.get('candidate');
    const rows=(m.candidates||[]).filter(c=>(!candidate||c.id===candidate)&&!opportunityRows.some(o=>o.source_url===c.url)).sort((a,b)=>(b.first_seen||'').localeCompare(a.first_seen||''));
    oe('monitor-list').innerHTML=rows.length?rows.map(c=>`<p><a href="${ox(c.url)}" target="_blank" rel="noopener">${ox(c.title)}</a><br><small>${ox(c.unit)} · 官网发布日期 ${ox(c.publication_date||'未明确')} · 首次发现 ${ox(opportunityTime(c.first_seen))} · ${c.discovery_status==='initial_snapshot'?'初次收录，非新发布证明':'后续新发现，待核验'}${c.source_state!=='ok'?' · 来源异常或已移出，须核对':''}</small></p>`).join(''):'<p>本轮没有额外活动线索；不代表其他院校未发布。</p>';
    if(candidate){oe('monitor-candidates').open=true;oe('monitor-candidates').scrollIntoView({block:'start'});}
  }catch(error){opportunityRows=opportunityRows.map(o=>({...o,source_state:'unavailable'}));renderOpportunities();oe('monitor-health').textContent='更新状态暂时无法读取，页面保留静态快照；不能判断当前是否为最新。';if(!opportunityModeReady)oe('opportunity-result').textContent='尚未连接申请工作台，保存功能暂不可用；可以继续查看官方通知。';}
  finally{oe('monitor-refresh').disabled=false;}
}
oe('monitor-refresh').onclick=refreshOpportunityMonitor;refreshOpportunityMonitor();

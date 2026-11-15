const oe=id=>document.getElementById(id), ox=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let opportunityRows=window.OPPORTUNITIES.opportunities, savingOpportunity=null, savedOpportunities=new Map(), saveBusy=false, publicOpportunityMode=false, opportunityModeReady=false, opportunityCatalog=window.OPPORTUNITIES;
const opportunityTime=value=>value?new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'未知';
const opportunityParams=new URLSearchParams(location.search), opportunityToday=OpportunityRules.dayOf(new Date().toISOString());
function opportunityFacts(o){
  const window=o.application_window,label=!o.deadline&&window?.mode==='rolling'?'官方受理方式':!o.deadline&&window?.mode==='month'?'截止月份':'报名截止';
  const value=OpportunityRules.formatDate(o.deadline)|| (window?.mode==='rolling'?'长期 / 滚动受理':window?.mode==='month'?OpportunityRules.formatDate(window.end_month)+'（具体日期未公布）':'具体日期待确认');
  return `<div class="opportunity-facts"><div><span class="muted">${label}</span><strong>${ox(value)}${o.deadline?.length===10?'（未注明时刻）':''}</strong></div>${o.graduation_year?`<div><span class="muted">面向届别</span><strong>${ox(o.graduation_year)} 届本科生</strong></div>`:''}${o.event_start||o.event_end?`<div><span class="muted">活动时间</span><strong>${ox(OpportunityRules.formatDate(o.event_start)||'开始日期待核对')}${o.event_end?' 至 '+ox(OpportunityRules.formatDate(o.event_end)):''}</strong></div>`:''}</div>`;
}
function opportunityWindow(o,state){
  const window=o.application_window;if(!window||o.deadline)return '';
  const hint=state==='rolling'?'长期或滚动受理不代表保证余位，请先联系官方确认当前接收安排。':state==='open_month'?'受理期内仅公布截止月份，请先确认具体日期，不要按月底安排。':state==='unknown'&&window.mode==='month'&&opportunityToday.slice(0,7)===window.end_month?'已到官方截止月份，具体截止日未公布，请确认是否仍在受理。':'';
  return `<p class="opportunity-window"><strong>官方受理说明：</strong>${ox(window.quote)}</p>${hint?`<p class="hint">${hint}</p>`:''}`;
}

function opportunityList(items,empty){return items.length?'<ul>'+items.map(s=>'<li>'+ox(s)+'</li>').join('')+'</ul>':'<p class="muted">'+empty+'</p>';}
function opportunityDirections(o,query=''){
  const directions=o.research_directions||[];if(!directions.length)return '';
  const q=query.trim().toLowerCase(),matching=directions.filter(r=>[r.department,r.direction,r.contact,r.email].join(' ').toLowerCase().includes(q));
  const rows=q&&matching.length?matching:directions;
  const row=r=>`<section class="research-direction"><h3>${ox(r.direction)}</h3><p>${ox(r.department)} · ${ox(r.contact||'联系人姓名未公布')}${r.email?` · <a href="mailto:${encodeURIComponent(r.email)}?subject=${encodeURIComponent('咨询'+o.title+'：'+r.direction)}">${ox(r.email)} ↗</a>`:' · 未公布邮箱，请通过官方通知咨询。'}</p><p><small><a href="${ox(r.source_url)}" target="_blank" rel="noopener">官方出处 ↗</a> · ${ox(r.source_locator)} · 核对 ${ox(r.verified_at)}</small></p></section>`;
  return `<div class="opportunity-directions"><h3>研究方向与联系${q&&matching.length?' · 命中 '+matching.length+' 项':''}</h3><p class="muted">官方公布的部门联系人，不等于已确认导师名额；先核对项目条件再联系。</p>${rows.slice(0,2).map(row).join('')}${rows.length>2?`<details class="opportunity-details"><summary>更多研究方向与联系 · 共 ${rows.length} 项</summary>${rows.slice(2).map(row).join('')}</details>`:''}</div>`;
}
function opportunityDocuments(o){
  const names={eligibility:'申请条件',materials:'材料',deadline:'截止时间',registration_start:'报名开始',application_method:'报名方式',contact:'联系渠道'};
  return (o.source_documents||[]).map(doc=>`<p><a href="${ox(doc.url)}" target="_blank" rel="noopener">官方 PDF 原文 ↗</a> · ${ox(doc.page_count)} 页 · 核对 ${ox(doc.checked_at)}</p><ul>${Object.entries(doc.field_evidence).map(([field,evidence])=>`<li>${ox(names[field]||'原文依据')} · 第 ${evidence.pages.map(ox).join('、')} 页：${ox(evidence.quote)}</li>`).join('')}</ul>`).join('');
}
function opportunityAttachments(o){
  const names={eligibility:'申请条件',materials:'材料要求',application_method:'报名方式',contact:'联系渠道',admission_note:'申请说明'};
  const seen=new Set();
  return (o.source_attachments||[]).filter(doc=>!seen.has(doc.url)&&seen.add(doc.url)).map(doc=>`<details class="opportunity-details"><summary>官方申请表与核验依据</summary><p><a href="${ox(doc.url)}" target="_blank" rel="noopener">下载官方申请表（DOCX） ↗</a> · 核对 ${ox(doc.checked_at)}</p><ul>${Object.entries(doc.field_evidence).map(([field,evidence])=>`<li><strong>${ox(names[field]||'原文依据')}</strong> · ${ox(evidence.locator)}：${ox(evidence.quote)}</li>`).join('')}</ul></details>`).join('');
}
function opportunitySource(o){
  let host='原文链接见下方';try{host=new URL(o.source_url).hostname;}catch(e){}
  return `<p class="opportunity-source"><span>来源：${ox(host)}</span><span>${o.source_state==='verified'?'内容核验':'整理记录'} ${ox(OpportunityRules.formatDate(o.verified_at)||'待核实')}</span></p>`;
}
function opportunityActions(o,state){
  const saved=savedOpportunities.get(o.id),urls=new Set([o.source_url]);
  const link=(url,label)=>{if(!url||urls.has(url))return '';urls.add(url);return `<a href="${ox(url)}" target="_blank" rel="noopener">${label} ↗</a>`;};
  return `<div class="opportunity-actions"><a class="primary opportunity-primary" href="${ox(o.source_url)}" target="_blank" rel="noopener">查看官方公告 ↗</a>${o.source_state==='verified'?link(o.application_url,state==='closed'?'原报名入口':'官方报名入口'):''}${publicOpportunityMode?`<a href="local.html?id=${encodeURIComponent(o.id)}">在本机准备申请</a>`:saved?`<a href="applications.html?project=${ox(saved)}">查看我的项目</a>`:`<button type="button" data-save-opportunity="${ox(o.id)}" ${opportunityModeReady?'':'disabled'}>${opportunityModeReady?(state==='closed'?'保存作参考':'加入我的申请'):'正在连接工作台…'}</button>`}</div>`;
}
function opportunityCard(o,filter){
  const state=OpportunityRules.state(o),organizer=o.content_classification.organizer_name;
  const research=o.research_directions||[];
  const attachmentUrls=new Set([o.source_url,o.application_url,...(o.source_documents||[]).map(d=>d.url),...(o.source_attachments||[]).map(d=>d.url)]);
  const extraAttachments=o.evidence.filter(url=>/^https?:\/\/[^\s]+\.(xlsx?|pdf|docx?)(?:\?.*)?$/i.test(url)&&!attachmentUrls.has(url)&&attachmentUrls.add(url));
  return `<article class="opportunity-card" data-opportunity="${ox(o.id)}">
    <div class="opportunity-meta"><span class="opportunity-state ${state}">${OpportunityRules.labels[state]}</span><span class="muted">${OpportunityRules.kinds[o.kind]}</span></div>
    <h2>${ox(o.title)}</h2><p class="opportunity-organizer">主办 / 组织：${ox(organizer)}</p>
    ${opportunityFacts(o)}
    <div class="opportunity-eligibility"><h3>适合谁申请</h3>${opportunityList(o.eligibility,'申请对象尚未明确，请先核对官方公告。')}</div>
    ${!o.graduation_year?`<p class="note opportunity-cohort">原文未明确毕业届别${filter.year?'，不代表已确认适用于 '+ox(filter.year)+' 届':''}；以以上年级和身份条件为准。</p>`:''}
    ${o.source_state!=='verified'||state==='review'?'<p class="hint">当前来源或内容需重新核验，不能据此确认报名仍开放。</p>':''}
    ${!o.deadline&&o.application_window?.mode==='month'?'<p class="note">仅公布截止月份，请先确认具体日期，不按月底安排。</p>':''}
    ${opportunitySource(o)}${opportunityActions(o,state)}
    <details class="opportunity-details"><summary>申请材料与报名步骤</summary><h3>材料与提交阶段</h3>${opportunityList(o.materials,'材料清单尚未整理，请查官方公告。')}<h3>报名方式</h3><p>${ox(o.application_method||'请查官方公告。')}</p>${o.contact?`<p><strong>官方咨询渠道：</strong>${ox(o.contact)}</p>`:''}${extraAttachments.map(url=>`<p><a href="${ox(url)}" target="_blank" rel="noopener">官方附件 · 方向或申请材料 ↗</a></p>`).join('')}${opportunityAttachments(o)}<p>${ox(o.admission_note)}</p></details>
    ${research.length?`<details class="opportunity-details"><summary>研究方向与部门联系人 · ${research.length} 项</summary>${opportunityDirections(o,filter.query)}</details>`:''}
    <details class="opportunity-details"><summary>时间、适用轮次与核验依据</summary>${opportunityWindow(o,state)}<p>${ox(o.deadline_note)}</p><p>活动年 ${ox(o.camp_year||'未明确')} · 毕业届别 ${ox(o.graduation_year||'未明确')} · 入学年 ${ox(o.admission_year||'未明确')}</p><p>官网发布 ${ox(OpportunityRules.formatDate(o.published_at)||'未明确')} · 内容核验 ${ox(OpportunityRules.formatDate(o.verified_at))} · 最近成功检查 ${ox(OpportunityRules.formatDate(o.checked_at)||'尚未成功')}</p><p>${ox(o.source_note)}</p>${opportunityList(o.evidence,'未记录更多依据。')}${opportunityDocuments(o)}</details>
  </article>`;
}
function movedOpportunity(o){
  const scope=OpportunityRules.classification(o),names={mentor_recruitment:'导师 / 课题组招募',admission_notice:'正式招生通知',pending:'内容待核验'};
  const explanation={mentor_recruitment:'这是一条导师或课题组的个人招募记录，已移出院校活动列表。它不代表院校统一项目或保研名额。',admission_notice:'这是一条正式招生通知，已移出冬夏令营与院校活动列表。请按原招生轮次查阅，不把历史通知当作当前报名。',pending:'这条记录的组织方、申请对象或正文证据尚不足，暂不进入活动列表，也不能确认可以报名。'};
  const mentors=(o.mentor_ids||[]).filter(id=>/^[a-z0-9][a-z0-9-]*$/.test(id));
  const next=scope==='mentor_recruitment'?(mentors.length?mentors.map(id=>`<a href="p/${encodeURIComponent(id)}.html">查看已核对的导师资料 →</a>`).join(' '):'<p class="note">导师身份尚待可靠关联，请从下方原文确认负责人，未绑定同名导师。</p>'):scope==='admission_notice'?`<a href="notices.html?notice_cycle=all&amp;q=${encodeURIComponent(o.title)}">查对应招生通知 →</a>`:'';
  return `<article class="opportunity-card opportunity-moved" data-other-content="${ox(o.id)}"><span class="opportunity-state">${names[scope]||names.pending}</span><h2>${ox(o.title)}</h2><p>${explanation[scope]||explanation.pending}</p>${next}<p class="note">原链接与已保存的申请快照保留。分类调整不会替你修改项目或创建新申请。</p>${opportunitySource(o)}<div class="opportunity-actions"><a class="primary opportunity-primary" href="${ox(o.source_url)}" target="_blank" rel="noopener">查看原官方记录 ↗</a><a href="opportunities.html">返回院校活动</a></div><details class="opportunity-details"><summary>查看保留的对象、时间与联系方式</summary>${opportunityFacts(o)}${opportunityList(o.eligibility,'对象需核实')}<p>${ox(o.contact)}</p><p>${ox(o.admission_note)}</p><p>${ox(o.deadline_note)}</p></details></article>`;
}
function renderOpportunities(){
  const filter={query:oe('opportunity-search').value,kind:oe('opportunity-kind').value,school:oe('opportunity-school').value,year:oe('opportunity-year').value,status:oe('opportunity-state').value};
  const focus=opportunityParams.get('id'),all=[...opportunityRows,...(opportunityCatalog.other_contents||[])],focused=focus&&all.find(o=>o.id===focus);
  const rows=focus?(focused&&OpportunityRules.classification(focused)==='institutional_activity'?[focused]:[]):OpportunityRules.select(opportunityRows,filter);
  oe('opportunity-count').textContent=focus?'当前记录':`${rows.length} 条院校活动${filter.status==='closed'?' · 历史参考':''}`;
  const back=focus?'<p class="opportunity-back"><a href="opportunities.html">← 返回全部院校活动</a></p>':'';
  const empty='<div class="opportunity-empty"><h2>当前条件下还没有已整理的院校活动</h2><p>个人招募、正式招生通知和待核验线索不计入活动数量；未收录不代表院校没有发布。</p><div class="opportunity-actions"><button type="button" id="opportunity-reset">清除筛选</button><button type="button" id="opportunity-history">查看历史活动</button><a href="notices.html">查官方招生通知 →</a></div></div>';
  oe('opportunity-list').innerHTML=back+(focus&&!focused?'<div class="opportunity-empty"><h2>当前目录未找到这条记录</h2><p>旧收藏或申请快照不会被删除。可返回活动列表，或从已保存项目中的官方出处核对。</p><a href="opportunities.html">返回活动列表 →</a></div>':focused&&OpportunityRules.classification(focused)!=='institutional_activity'?movedOpportunity(focused):rows.length?rows.map(o=>opportunityCard(o,filter)).join(''):empty);
  oe('pending-contents').innerHTML=(opportunityCatalog.other_contents||[]).filter(o=>OpportunityRules.classification(o)==='pending').map(o=>`<p><a href="opportunities.html?id=${encodeURIComponent(o.id)}">${ox(o.title)}</a> · 对象或来源尚待核验，不计入活动数量。</p>`).join('');
  oe('opportunity-coverage').textContent=(opportunityCatalog.coverage_note||'当前来源范围待说明')+' 最近整理：'+(opportunityCatalog.checked_at||'未知')+'。';
}

function refreshOpportunityOptions(){
  const activities=opportunityRows.filter(o=>OpportunityRules.classification(o)==='institutional_activity');
  for(const [key,values,label] of [['year',[...new Set(activities.map(o=>o.graduation_year).filter(Boolean))].sort(),'全部届别'],['school',[...new Set(activities.map(o=>o.school_name))].sort(),'全部学校']]){
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
  savingOpportunity=opportunityRows.find(o=>o.id===button.dataset.saveOpportunity&&OpportunityRules.classification(o)==='institutional_activity');
  if(!savingOpportunity)return;
  oe('opportunity-name').value=savingOpportunity.title;oe('opportunity-reminder').value='';oe('opportunity-reminder').min=opportunityToday;
  oe('opportunity-reminder').max=OpportunityRules.state(savingOpportunity)==='open'?savingOpportunity.deadline.slice(0,10):'';
  const state=OpportunityRules.state(savingOpportunity);
  oe('opportunity-save-hint').textContent=state==='open'?'报名截止：'+savingOpportunity.deadline+'。建议在截止前留出材料准备时间。':state==='rolling'?'官方说明长期或滚动受理，未公布具体截止。请先确认余位；下方日期仅为个人核对提醒。':state==='open_month'?'官方只公布受理至 '+savingOpportunity.application_window.end_month+'，未公布具体截止日。下方日期仅为个人提醒，不作为官方截止。':'当前不是已确认开放的报名机会。可保存作参考，并安排个人核对提醒。';oe('save-message').textContent='';oe('opportunity-save').showModal();
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
    const response=await fetch('/api/opportunities');if(!response.ok)throw new Error('读取失败');const data=await response.json();opportunityCatalog=data;opportunityRows=data.opportunities;publicOpportunityMode=data.mode==='public';opportunityModeReady=true;refreshOpportunityOptions();renderOpportunities();
    if(!publicOpportunityMode)await loadSavedOpportunities();
    if(data.feed_error)oe('opportunity-result').textContent=data.feed_error;
    const m=data.monitoring;
    if(!m){oe('monitor-health').textContent=publicOpportunityMode?'服务器尚无可用监测记录，当前页面不能确认信息已更新。请直接核对官方通知。':'尚无监测记录。运行“启动信息监测.cmd”后按来源优先级检查已配置的官方栏目。电脑休眠或程序关闭期间不会更新。';oe('monitor-list').replaceChildren();oe('monitor-sources').replaceChildren();return;}
    const overdue=!m.next_check_at||Date.parse(m.next_check_at)<Date.now(),sum=m.summary||{};
    oe('monitor-health').textContent=(overdue?'监测已超出应检时间，请检查监测程序。':'最近一轮监测已完成；这不代表所有信息已核验。')+' 最近实际回源：'+opportunityTime(m.last_fetch_at||m.checked_at)+'；下次应检：'+opportunityTime(m.next_check_at)+'（北京时间）。成功栏目 '+(sum.sources_ok||0)+' / '+(sum.source_count||0)+'；失败 '+(sum.sources_error||0)+'。本轮实际检查 '+(sum.sources_attempted??sum.source_count??0)+' 个，未到期跳过 '+(sum.sources_skipped||0)+' 个；超期 '+(sum.overdue_sources||0)+' 个。新发现 '+(sum.new_count||0)+' 条。';
    oe('monitor-sources').innerHTML=Object.values(m.sources||{}).filter(s=>s.status!=='removed').map(s=>`<p><a href="${ox(s.url)}" target="_blank" rel="noopener">${ox(s.unit||'官方招生栏目')}</a> · ${s.status==='ok'?'最近检查成功':'暂时无法读取，请直接查官网'}<br><small>最近成功：${ox(opportunityTime(s.last_success))}</small></p>`).join('')||'<p>暂无来源记录。</p>';
    const candidate=opportunityParams.get('candidate');
    const known=[...opportunityRows,...(opportunityCatalog.other_contents||[])];
    const rows=(m.candidates||[]).filter(c=>(!candidate||c.id===candidate)&&!known.some(o=>o.source_url===c.url)).sort((a,b)=>(b.first_seen||'').localeCompare(a.first_seen||''));
    oe('monitor-list').innerHTML=rows.length?rows.map(c=>`<p><a href="${ox(c.url)}" target="_blank" rel="noopener">${ox(c.title)}</a><br><small>${ox(c.unit)} · 官网发布日期 ${ox(c.publication_date||'未明确')} · 首次发现 ${ox(opportunityTime(c.first_seen))} · ${c.discovery_status==='initial_snapshot'?'初次收录，非新发布证明':'后续新发现，待核验'}${c.source_state!=='ok'?' · 来源异常或已移出，须核对':''}</small></p>`).join(''):'<p>本轮没有额外活动线索；不代表其他院校未发布。</p>';
    if(candidate){oe('monitor-details').open=true;oe('monitor-candidates').open=true;oe('monitor-candidates').scrollIntoView({block:'start'});}
  }catch(error){opportunityRows=opportunityRows.map(o=>({...o,source_state:'unavailable'}));renderOpportunities();oe('monitor-health').textContent='更新状态暂时无法读取，页面保留静态快照；不能判断当前是否为最新。';if(!opportunityModeReady)oe('opportunity-result').textContent='尚未连接申请工作台，保存功能暂不可用；可以继续查看官方通知。';}
  finally{oe('monitor-refresh').disabled=false;}
}
oe('monitor-refresh').onclick=refreshOpportunityMonitor;refreshOpportunityMonitor();

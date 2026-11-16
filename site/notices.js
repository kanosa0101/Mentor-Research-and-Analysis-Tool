
const incoming=new URLSearchParams(location.search),select=document.getElementById('school'),context=document.getElementById('notice-context');
const units=(window.SCHOOL_CATALOG||window.ADMISSIONS_DATA)?.units||[],scopeKeys=['year','degree','route','track','program','group'];
const noticeRows=JSON.parse(document.getElementById('notice-data').textContent),noticeById=new Map(noticeRows.map(n=>[n.id,n]));
const noticeControls={cycle:'notice-cycle',route:'notice-route',admission_year:'notice-admission-year',graduation_year:'notice-graduation-year',activity_year:'notice-activity-year'};
for(const key of ['admission_year','graduation_year','activity_year']){
  const control=document.getElementById(noticeControls[key]);
  for(const value of [...new Set(noticeRows.map(n=>n.classification?.[key]).filter(Boolean))].sort((a,b)=>b-a))control.add(new Option(value+(key==='graduation_year'?' 届':''),String(value)));
}
for(const [key,id] of Object.entries(noticeControls)){
  const value=incoming.get('notice_'+key)||(['route','admission_year'].includes(key)?incoming.get(key==='route'?'route':'year'):'');
  if(value&&[...document.getElementById(id).options].some(o=>o.value===value))document.getElementById(id).value=value;
}
document.getElementById('notice-more-years').open=!!(document.getElementById('notice-graduation-year').value||document.getElementById('notice-activity-year').value);
const asOf=noticeRows.map(n=>n.classification?.as_of).filter(Boolean).sort().pop();
const reference=asOf?new Date(asOf+'T12:00:00+08:00'):new Date(),y=reference.getFullYear(),m=reference.getMonth()+1;
document.getElementById('notice-cycle-guide').textContent=(asOf?'分类截至 '+asOf+'。':'分类日期待核验。')+(m>=11?`${y+1} 年入学推免已进入结果与历史参考；${y+1} 年入学统考属于当前周期（备考与后续安排）；${y+2} 届本科生可查看下一届推免准备。`:'请按通知明确的入学年、毕业届别和申请渠道判断周期。')+' 冬令营活动年份不等于毕业届别；“当前周期”不表示报名开放。';
const knownSchool=key=>!key.includes('/')&&units.some(u=>u.school===key);
const inScope=(unitKey,key)=>!key||unitKey===key||(knownSchool(key)&&unitKey.startsWith(key+'/'));
const nameFor=key=>{const u=units.find(u=>u.school+'/'+u.dept===key);return u?u.school_name+' · '+u.dept_name:units.find(u=>u.school===key)?.school_name||key;};
const rawSchool=incoming.get('school')||'',requested=rawSchool&&!rawSchool.includes('/')&&incoming.get('dept')?rawSchool+'/'+incoming.get('dept'):rawSchool;
if(requested&&!Array.from(select.options).some(o=>o.value===requested))select.add(new Option(nameFor(requested),requested));
for(const option of select.options)if(option.value)option.textContent=nameFor(option.value)+(knownSchool(option.value)?'（全校已接入院系）':document.querySelector('[data-source="'+CSS.escape(option.value)+'"]')?'':'（未接入）');
select.value=requested;
for(const source of document.querySelectorAll('[data-source]'))source.querySelector('a').textContent=nameFor(source.dataset.source)+' 官方栏目';
function officialLink(container,key){
  container.replaceChildren();
  if(knownSchool(key)){
    const sources=Array.from(document.querySelectorAll('[data-source]')).filter(e=>inScope(e.dataset.source,key));
    if(sources.length){for(const source of sources){const p=document.createElement('p');p.append(source.querySelector('a').cloneNode(true));container.append(p);}return;}
    container.textContent='该校尚未接入通知监测。请返回学校与要求页查看已登记的院系官方入口。';return;
  }
  const source=Array.from(document.querySelectorAll('[data-source]')).find(e=>e.dataset.source===key),unit=units.find(u=>u.school+'/'+u.dept===key);
  const url=source?.querySelector('a').href||unit?.notice_url||unit?.roster_url;
  if(url){const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener';a.textContent=nameFor(key)+(source||unit?.notice_url?' · 官方招生栏目 →':' · 官方院系师资入口 →');container.append(a);}
  else container.textContent=key?'该院系未登记官方入口。请返回学校与要求页核对目录。':'选择院系后可查看已登记的官方入口。';
  if(source?.classList.contains('error'))container.append(document.createTextNode(' 来源抓取失败，历史记录仍可查看；最新安排请查官网。'));
}
function filter(){
  const school=select.value,q=document.getElementById('search').value.trim().toLowerCase(),parts=school.split('/'),query=new URLSearchParams();
  const filters=Object.fromEntries(Object.entries(noticeControls).map(([key,id])=>[key,document.getElementById(id).value]));
  for(const key of scopeKeys)if(incoming.get(key))query.set(key,incoming.get(key));
  if(school)query.set('school',parts[0]);
  if(parts.length===2)query.set('dept',parts[1]);
  const pageQuery=new URLSearchParams(query);
  for(const [key,value] of Object.entries(filters))if(value)pageQuery.set('notice_'+key,value);
  if(q)pageQuery.set('q',document.getElementById('search').value.trim());
  history.replaceState(null,'',location.pathname+(pageQuery.size?'?'+pageQuery:'')+location.hash);
  document.getElementById('notice-policy-link').href='admissions.html'+(query.size?'?'+query:'');
  for(const a of document.querySelectorAll('.site-header a[href]')){const path=a.getAttribute('href').split('?')[0];if(['discovery.html','compare.html','admissions.html','notices.html','desk.html','applications.html'].includes(path))a.href=path+(query.size?'?'+query:'');}
  for(const warning of document.querySelectorAll('[data-source-error]')){warning.hidden=!inScope(warning.dataset.sourceError,school);warning.querySelector('span').textContent=nameFor(warning.dataset.sourceError);}
  const counts={current:0,preparation:0,historical:0,unknown:0};let n=0;
  document.querySelectorAll('article[data-notice-id]').forEach(a=>{
    const row=noticeById.get(a.dataset.noticeId),base=inScope(a.dataset.school,school)&&a.dataset.title.toLowerCase().includes(q);
    const show=base&&NoticeRules.matches(row,filters);a.hidden=!show;if(show)n++;
    if(base)for(const cycle of Object.keys(counts))if(NoticeRules.matches(row,{...filters,cycle}))counts[cycle]++;
  });
  document.getElementById('count').textContent=n+' 条通知 · 分类用于找资料，报名状态需另查原文';document.getElementById('notice-empty').hidden=n!==0;
  document.getElementById('notice-general-hint').hidden=!filters.route||filters.route==='unknown';
  const buckets=document.getElementById('notice-buckets');buckets.replaceChildren();
  for(const [cycle,label] of [['current','当前周期'],['preparation','下一届准备'],['historical','历史参考'],['unknown','待核验']]){const button=document.createElement('button');button.type='button';button.dataset.noticeCycle=cycle;button.textContent=label+' '+counts[cycle]+' 条';button.setAttribute('aria-pressed',String(filters.cycle===cycle));button.onclick=()=>{document.getElementById('notice-cycle').value=cycle;filter();};buckets.append(button);}
  const scope=[incoming.get('year')?incoming.get('year')+'入学':'',({master:'硕士',phd:'博士'})[incoming.get('degree')]||'',({recommend:'推免',exam:'统考',assessment:'申请考核'})[incoming.get('route')]||'',({ordinary:'普通招生',special:'专项/特定项目'})[incoming.get('track')]||'',incoming.get('program')?.replace('|',' · ')||''].filter(Boolean).join(' · ');
  const sourceCount=Array.from(document.querySelectorAll('[data-source]')).filter(e=>inScope(e.dataset.source,school)).length;
  const connected=sourceCount>0;
  context.textContent=(school?nameFor(school)+(knownSchool(school)?' · 全校已接入的 '+sourceCount+' 个院系栏目（不是全校全部通知）':connected?'':' · 尚未接入通知监测'):'全部已接入院系')+(scope?'。返回学校与要求时保留申请目标：'+scope+'。':'。')+'当前只展示所选周期与条件；未知届别和历史通知可通过上方切换查看。';
  officialLink(document.getElementById('current-source'),school);officialLink(document.getElementById('empty-source'),school);
}
select.addEventListener('change',()=>{incoming.delete('program');incoming.delete('group');if(incoming.get('track')==='special')incoming.delete('track');filter();});document.getElementById('search').addEventListener('input',filter);
for(const id of Object.values(noticeControls))document.getElementById(id).addEventListener('change',filter);
document.getElementById('search').value=incoming.get('q')||'';
document.getElementById('notice-general-policy').onclick=()=>{
  const admission=document.getElementById('notice-admission-year');
  if(!admission.value){const years=[...new Set([...document.querySelectorAll('article[data-notice-id]:not([hidden])')].map(a=>noticeById.get(a.dataset.noticeId)?.classification?.admission_year).filter(Boolean))];if(years.length===1)admission.value=String(years[0]);}
  document.getElementById('notice-route').value='unknown';filter();
};
document.getElementById('clear-search').onclick=()=>{document.getElementById('search').value='';filter();document.getElementById('search').focus();};filter();

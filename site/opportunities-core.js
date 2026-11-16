(function(root){
  const labels={open:'明确日期 · 报名时间内',open_month:'受理期内 · 截止仅公布月份',rolling:'长期 / 滚动受理',upcoming:'尚未开始',review:'待复核',unknown:'报名时间待核实',closed:'已截止 / 历史参考'};
  const kinds={winter_camp:'冬令营',summer_camp:'夏令营',recommend:'正式推免通知',research_program:'院所科研项目'};
  function classification(o,now=new Date().toISOString()){
    const c=o.content_classification;
    const keys=['scope','organizer_level','organizer_name','source_url','quote','verified_at'];
    if(!c||Object.keys(c).length!==keys.length||!keys.every(k=>typeof c[k]==='string'&&c[k].trim())||!['institutional_activity','mentor_recruitment','admission_notice','pending'].includes(c.scope)||c.source_url!==o.source_url||!/^https?:\/\//.test(c.source_url))return 'pending';
    const date=c.verified_at;if(!/^\d{4}-\d{2}-\d{2}$/.test(date||'')||!Number.isFinite(Date.parse(date))||new Date(date).toISOString().slice(0,10)!==date||date>dayOf(now))return 'pending';
    if(['institutional_activity','admission_notice'].includes(c.scope)&&!['school_department','research_institute','university_research_institute'].includes(c.organizer_level)||c.scope==='institutional_activity'&&o.kind==='recommend'||c.scope==='mentor_recruitment'&&!['individual_team','individual_lab'].includes(c.organizer_level))return 'pending';
    return c.scope;
  }
  const dayOf=now=>new Date(now).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
  function monitorOverdue(monitoring,now=new Date().toISOString()){
    const value=monitoring?.next_check_at,due=Date.parse(value),time=Date.parse(now);
    if(!Number.isFinite(due)||!Number.isFinite(time)||!/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value))return true;
    const day=value.slice(0,10),calendar=Date.parse(day+'T00:00:00Z');
    if(!Number.isFinite(calendar)||new Date(calendar).toISOString().slice(0,10)!==day)return true;
    return due+15*60*1000<time;
  }
  function formatDate(value){
    if(!value)return '';
    const day=String(value).match(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/);
    if(day)return `${day[1]}年${Number(day[2])}月${day[3]?Number(day[3])+'日':''}`;
    if(!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))return String(value);
    const parts=Object.fromEntries(new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).map(p=>[p.type,p.value]));
    return `${parts.year}年${parts.month}月${parts.day}日 ${parts.hour}:${parts.minute}（北京时间）`;
  }
  function state(o,now=new Date().toISOString()){
    if(o.cycle==='historical')return 'closed';
    const day=dayOf(now),deadline=o.deadline,window=o.application_window;
    if(deadline&&(deadline.length===10?deadline<day:Date.parse(deadline)<Date.parse(now)))return 'closed';
    if(o.event_end&&o.event_end<day)return 'closed';
    if(window?.mode==='month'&&window.end_month&&day.slice(0,7)>window.end_month)return 'closed';
    const age=(Date.parse(day+'T00:00:00Z')-Date.parse(o.checked_at+'T00:00:00Z'))/86400000,reviewAge=(Date.parse(day+'T00:00:00Z')-Date.parse(o.verified_at+'T00:00:00Z'))/86400000;
    if(o.source_state!=='verified'||!Number.isFinite(age)||age<0||age>7||!Number.isFinite(reviewAge)||reviewAge<0||reviewAge>30)return 'review';
    if(o.registration_start&&o.registration_start>day)return 'upcoming';
    if(!deadline&&window?.mode==='rolling')return 'rolling';
    if(!deadline&&window?.mode==='month'&&o.registration_start&&day.slice(0,7)<window.end_month)return 'open_month';
    return deadline&&o.registration_start?'open':'unknown';
  }
  function select(rows,filter,now=new Date().toISOString()){
    const q=(filter.query||'').trim().toLowerCase();
    return rows.filter(o=>classification(o,now)==='institutional_activity'&&(!filter.kind||o.kind===filter.kind)&&(!filter.school||o.school_name===filter.school)&&
      (!filter.year||(filter.year==='unknown'?!o.graduation_year:o.graduation_year===Number(filter.year)))&&
      (!q||[o.title,o.unit,o.school_name,...o.eligibility,...(o.research_directions||[]).flatMap(r=>[r.department,r.direction,r.contact,r.email])].join(' ').toLowerCase().includes(q))&&
      (filter.status==='all'||(filter.status==='current'?state(o,now)!=='closed':state(o,now)===filter.status)))
      .sort((a,b)=>({open:0,open_month:1,rolling:2,upcoming:3,unknown:4,review:5,closed:6}[state(a,now)]-{open:0,open_month:1,rolling:2,upcoming:3,unknown:4,review:5,closed:6}[state(b,now)])||
        (state(a,now)==='closed'?b.published_at.localeCompare(a.published_at):(a.deadline||'9999').localeCompare(b.deadline||'9999')));
  }
  function changes(saved,current){
    if(!current)return [];
    const fields={research_directions:'研究方向与联系人',graduation_year:'面向届别',registration_start:'报名开始',deadline:'报名截止',deadline_note:'截止说明',application_window:'受理方式与截止月份',event_start:'活动开始',event_end:'活动结束',eligibility:'申请条件',materials:'材料与提交阶段',application_method:'报名方式',application_url:'报名入口',contact:'联系方式',admission_note:'招生说明',source_url:'官方来源',source_attachments:'官方申请表与核验依据'};
    return Object.entries(fields).filter(([key])=>JSON.stringify(saved[key])!==JSON.stringify(current[key])).map(([key,label])=>({key,label,before:saved[key],after:current[key]}));
  }
  const api={state,select,kinds,labels,dayOf,changes,formatDate,classification,monitorOverdue};if(typeof module!=='undefined')module.exports=api;else root.OpportunityRules=api;
})(typeof window!=='undefined'?window:globalThis);

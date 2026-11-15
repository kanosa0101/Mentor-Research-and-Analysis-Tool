(function(root){
  const labels={open:'明确日期 · 报名时间内',open_month:'受理期内 · 截止仅公布月份',rolling:'长期 / 滚动受理',upcoming:'尚未开始',review:'待复核',unknown:'报名时间待核实',closed:'已截止 / 历史参考'};
  const kinds={winter_camp:'冬令营',summer_camp:'夏令营',recommend:'预推免',research_program:'科研实践'};
  const dayOf=now=>new Date(now).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});
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
    return rows.filter(o=>(!filter.kind||o.kind===filter.kind)&&(!filter.school||o.school_name===filter.school)&&
      (!filter.year||!o.graduation_year||o.graduation_year===Number(filter.year))&&
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
  const api={state,select,kinds,labels,dayOf,changes};if(typeof module!=='undefined')module.exports=api;else root.OpportunityRules=api;
})(typeof window!=='undefined'?window:globalThis);

(function(root){
  function cycle(policy,today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})){
    const [year,month]=today.split('-').map(Number),target=Number(policy.year);
    if(!Number.isInteger(target)||target<2000||target>2100)return {state:'unknown',label:'适用周期待核对'};
    const current=year+(policy.route==='recommend'?(month>=11?2:1):(month>=9?1:0));
    if(target<current)return {state:'historical',label:'历史参考 · 非本届要求'};
    if(target>current||policy.route==='recommend'&&month>=11)return {state:'preparation',label:'后续申请周期'};
    return {state:'current',label:'当前申请周期'};
  }
  function select(policies,prefs){return policies.filter(p=>
    (!prefs.school||p.school===prefs.school)&&(!prefs.dept||!p.dept||p.dept===prefs.dept)&&
    (!prefs.year||p.year===Number(prefs.year))&&(!prefs.degree||p.degree===prefs.degree)&&(!prefs.route||p.route===prefs.route)&&
    (!prefs.track||(p.track||(p.level==='school'?'general':'ordinary'))==='general'||(p.track||'ordinary')===prefs.track));}
  function eventState(event,now=new Date().toISOString()){const at=Date.parse(event.at),time=Date.parse(now);if(!Number.isFinite(at)||!Number.isFinite(time))return 'unknown';if(/^\d{4}-\d{2}-\d{2}$/.test(event.at)){const day=new Date(time).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'});return event.at<day?'past':'future';}return at<time?'past':'future';}
  function quality(p,observations,today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'})){
    const age=day=>(Date.parse(today+'T00:00:00Z')-Date.parse(day+'T00:00:00Z'))/86400000;
    const sources=Object.keys(p.review_hashes||{}).map(id=>({id,expected:p.review_hashes[id],observation:observations[id]}));
    if(!sources.length)return {state:'unknown',label:'尚无有效来源检查记录'};
    if(sources.some(s=>s.observation?.status==='error'))return {state:'error',label:'来源检查失败，需人工复核'};
    if(sources.some(s=>s.observation?.hash&&s.observation.hash!==s.expected))return {state:'changed',label:'原文或附件已变化，摘要待复核'};
    if(sources.some(s=>s.observation?.status!=='ok'||!s.observation.hash||!s.observation.last_success))return {state:'unknown',label:'尚无有效来源检查记录'};
    if(sources.some(s=>!Number.isFinite(age(s.observation.last_success))||age(s.observation.last_success)<0||age(s.observation.last_success)>7))return {state:'stale',label:'来源超过7天未成功检查，需复核'};
    if(p.revalidation_invalid)return {state:'review',label:'政策内容或来源配置已变化，原系统复检不再适用'};
    const confirmation=p.revalidation,confirmed=confirmation?.checked_at?new Date(confirmation.checked_at).toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'}):'';
    // Build-time public_policy validates the full policy fingerprint before projection.
    if(confirmation?.method==='unchanged-reviewed-policy-v1'&&confirmation.source_hashes&&
       Object.keys(confirmation.source_hashes).length===sources.length&&sources.every(s=>confirmation.source_hashes[s.id]===s.expected)&&
       Number.isFinite(age(confirmed))&&age(confirmed)>=0&&age(confirmed)<=30)
      return {state:'checked',label:'系统复检：原核验版本与逐项证据一致；未改写人工摘要或适用年度',method:'unchanged_source',confirmed_at:confirmed};
    if(!Number.isFinite(age(p.reviewed_at))||age(p.reviewed_at)<0||age(p.reviewed_at)>30)return {state:'review',label:'人工摘要超过30天且无有效系统复检，需复核'};
    return {state:'checked',label:'近期检查与核对版本一致；申请前仍需查看官网'};
  }
  function checklist(data,prefs,today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Shanghai'}),now=new Date().toISOString()){
    const required=['school','dept','year','degree','route','track'],missing=required.filter(key=>!prefs[key]);
    const valid=/^\d{4}$/.test(String(prefs.year))&&Number(prefs.year)>=2000&&Number(prefs.year)<=2100&&
      ['master','phd'].includes(prefs.degree)&&['recommend','exam','assessment'].includes(prefs.route)&&
      ['ordinary','special'].includes(prefs.track)&&data.units.some(u=>u.school===prefs.school&&u.dept===prefs.dept);
    if(missing.length||!valid)return {ready:false,missing,policies:[],items:[],events:[]};
    const isProgram=p=>p.level==='program'||p.track==='special'&&!!p.program;
    const policies=select(data.policies,prefs).filter(p=>!isProgram(p)||!prefs.program||programKey(p)===prefs.program);
    const rows=policies.map(policy=>({policy,quality:quality(policy,data.checks,today),conditional:!!policy.applies_if||isProgram(policy)&&!prefs.program}));
    const items=['eligibility','materials','exams','timeline','tuition','funding','quota','contact'].map(key=>({key,rows:rows.map(row=>({...row,field:row.policy.fields[key]}))}));
    const events=rows.flatMap(row=>(row.policy.events||[]).map(event=>({...row,event,state:eventState(event,now)})));
    return {ready:true,missing:[],policies,items,events};
  }
  function programKey(p){return (p.program_code||'')+'|'+(p.program||'');}
  function conditionLabel(policy,conditional=false){return policy.applies_if?'条件性参考：'+policy.applies_if.text+'，需本人确认':conditional?'条件性参考，未确认专业适用':'';}
  function sourceReferences(policy,item,sources){return (item?.source_ids||[policy.source_id]).map(id=>{const source=sources[id];return {...source,id,label:source.label||(source.format==='pdf'?'PDF原文':'官方原文')};});}
  const api={select,quality,eventState,checklist,programKey,conditionLabel,sourceReferences,cycle};if(typeof module!=='undefined')module.exports=api;else root.AdmissionsRules=api;
})(typeof window!=='undefined'?window:globalThis);

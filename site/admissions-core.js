(function(root){
  function select(policies,prefs){return policies.filter(p=>
    (!prefs.school||p.school===prefs.school)&&(!prefs.dept||!p.dept||p.dept===prefs.dept)&&
    (!prefs.year||p.year===Number(prefs.year))&&(!prefs.degree||p.degree===prefs.degree)&&(!prefs.route||p.route===prefs.route));}
  function quality(p,observations,today=new Date().toLocaleDateString('sv-SE')){
    const age=day=>(Date.parse(today+'T00:00:00Z')-Date.parse(day+'T00:00:00Z'))/86400000;
    const sources=Object.keys(p.review_hashes).map(id=>({id,expected:p.review_hashes[id],observation:observations[id]}));
    if(sources.some(s=>s.observation?.status==='error'))return {state:'error',label:'来源检查失败，需人工复核'};
    if(sources.some(s=>s.observation?.hash&&s.observation.hash!==s.expected))return {state:'changed',label:'原文或附件已变化，摘要待复核'};
    if(sources.some(s=>s.observation?.status!=='ok'||!s.observation.hash||!s.observation.last_success))return {state:'unknown',label:'尚无有效来源检查记录'};
    if(sources.some(s=>!Number.isFinite(age(s.observation.last_success))||age(s.observation.last_success)<0||age(s.observation.last_success)>7))return {state:'stale',label:'来源超过7天未成功检查，需复核'};
    if(!Number.isFinite(age(p.reviewed_at))||age(p.reviewed_at)<0||age(p.reviewed_at)>30)return {state:'review',label:'人工摘要超过30天或日期异常，需复核'};
    return {state:'checked',label:'近期检查与核对版本一致；申请前仍需查看官网'};
  }
  const api={select,quality};if(typeof module!=='undefined')module.exports=api;else root.AdmissionsRules=api;
})(typeof window!=='undefined'?window:globalThis);

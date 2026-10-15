(function(root){
  const modes={research:'研究关键词',qualification:'导师资格',email:'公开邮箱',opportunity:'本年度招生机会',eligibility:'我的申请资格'};
  const includes=(text,term)=>{
    if(/^[a-z0-9 ._-]+$/i.test(term))return new RegExp('(^|[^a-z0-9])'+term.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'($|[^a-z0-9])','i').test(text);
    return text.toLowerCase().includes(term.toLowerCase());
  };
  function evaluate(p,prefs,reviews,corpus='',today=new Date().toLocaleDateString('sv-SE')){
    const checks=[],evidence=[];
    const add=(key,state,detail)=>checks.push({key,state,detail,mode:prefs.modes[key],label:modes[key]});
    if(prefs.schools.length&&!prefs.schools.includes(p.school))return {visible:false,checks:[{key:'school',state:'fail',detail:'不在允许院校内'}],score:0,evidence};
    if(prefs.topics.length){
      const direction=p.research_direction_raw||'',text=direction+' '+corpus;
      const hits=prefs.topics.filter(term=>includes(direction,term)||includes(corpus,term));
      add('research',hits.length?'pass':text.trim()?'fail':'unknown',hits.length?'关键词任一命中：'+hits.join('、'):text.trim()?'资料文字未命中所选关键词，不代表真实研究不适合':'缺少可检索研究材料');
      for(const term of hits){const field=includes(direction,term)?'research_direction_raw':'bio_raw',raw=field==='bio_raw'?corpus:direction,index=raw.toLowerCase().indexOf(term.toLowerCase());evidence.push({field,term,snippet:raw.slice(Math.max(0,index-25),index+term.length+70)});}
    }
    if(prefs.degree!=='any'){
      const value=p.supervisor||'',wanted=prefs.degree==='phd'?'博':'硕';
      const found=value.includes(wanted)&&!/(无|非|不|未具备)/.test(value);
      add('qualification',found?'pass':'unknown',found?'官网导师资格：'+value:'该学位导师资格未明确；其他学位资格不自动推断');
    }
    add('email',p.email?'pass':'unknown',p.email?'官网提供邮箱，使用前仍需核对':'官网库未提供邮箱，需查主页或咨询院系');
    const scoped=projectScoped(prefs);
    let review=scoped?undefined:Object.values(reviews).find(r=>r.mentor_id===p.page&&r.year===prefs.year&&r.degree===prefs.degree&&r.route===prefs.route);
    const age=review?(Date.parse(today+'T00:00:00Z')-Date.parse(review.checked_at+'T00:00:00Z'))/86400000:Infinity;
    const valid=review&&age>=0&&age<=30;
    for(const key of ['opportunity','eligibility'])add(key,valid?review[key]:'unknown',scoped?'核验尚未区分该项目，需对照原文':valid?'人工核验于 '+review.checked_at:review?'核验超过30天或日期异常，请复核':'没有对应年度/学位/渠道的核验记录');
    const active=checks.filter(c=>c.mode!=='off');
    return {visible:!active.some(c=>c.mode==='hard'&&(c.state==='fail'||(!prefs.keep_unknown&&c.state==='unknown'&&!(scoped&&['opportunity','eligibility'].includes(c.key))))),
      checks,evidence,review,score:active.filter(c=>c.state==='pass').length,unknown:active.filter(c=>c.state==='unknown').length};
  }
  function projectScoped(prefs){return !!prefs.program||prefs.track==='special';}
  function completeness(p,extra={}){
    const present=value=>typeof value==='string'&&value.trim()&&!/(未知|待补充|未整理)/.test(value);
    const direction=extra.research_direction_raw||p.research_direction_raw;
    const field=present(direction)?'research_direction_raw':'bio_raw',source=extra.provenance?.[field];
    return [present(direction)?2:present(extra.bio_excerpt)?1:0,Number(!!present(p.email)),Number(!!present(p.title)),Number(!!present(p.supervisor)),Number(!!source?.source&&/^https?:/.test(source.source)&&/^\d{4}-\d{2}-\d{2}/.test(source.fetched_at||''))];
  }
  function randomKey(id,seed){let hash=2166136261;for(const char of seed+'|'+id){hash^=char.charCodeAt(0);hash=Math.imul(hash,16777619);}hash^=hash>>>16;hash=Math.imul(hash,0x85ebca6b);hash^=hash>>>13;return hash>>>0;}
  function rankCandidates(rows,prefs,extra={},seed=''){
    const matched=!!(prefs.topics.length&&prefs.modes.research!=='off'||prefs.degree!=='any'&&prefs.modes.qualification!=='off'||prefs.year||prefs.route&&prefs.route!=='unknown'||['email','opportunity','eligibility'].some(key=>prefs.modes[key]==='hard')||rows.some(row=>row.result.review));
    const ranked=rows.map(row=>({...row,completeness:completeness(row.p,extra[row.p.page]),random:randomKey(row.p.page,seed)}));
    ranked.sort((a,b)=>{
      if(matched){const match=b.result.score-a.result.score||a.result.unknown-b.result.unknown;if(match)return match;}
      for(let i=0;i<a.completeness.length;i++){const diff=b.completeness[i]-a.completeness[i];if(diff)return diff;}
      return a.random-b.random||a.p.page.localeCompare(b.p.page);
    });
    return {rows:ranked,matched};
  }
  const api={evaluate,projectScoped,completeness,rankCandidates};if(typeof module!=='undefined')module.exports=api;else root.DiscoveryRules=api;
})(typeof window!=='undefined'?window:globalThis);

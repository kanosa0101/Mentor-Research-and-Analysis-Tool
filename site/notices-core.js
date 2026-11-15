(function(root){
  function tracks(row,route){return (row.classification?.tracks||[{route:'unknown',cycle:'unknown'}]).filter(t=>!route||t.route===route);}
  function matches(row,filter){
    const c=row.classification||{},selected=tracks(row,filter.route);
    if(!selected.length)return false;
    if(filter.cycle&&filter.cycle!=='all'&&!selected.some(t=>filter.cycle==='current'?['current','preparation'].includes(t.cycle):t.cycle===filter.cycle))return false;
    for(const key of ['admission_year','graduation_year','activity_year']){
      if(filter[key]&&(filter[key]==='unknown'?!!c[key]:String(c[key]||'')!==filter[key]))return false;
    }
    return true;
  }
  const api={matches};if(typeof module!=='undefined')module.exports=api;else root.NoticeRules=api;
})(typeof window!=='undefined'?window:globalThis);

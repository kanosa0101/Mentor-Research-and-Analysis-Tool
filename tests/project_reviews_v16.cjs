const assert=require('node:assert/strict');
const core=require('../site/discovery-core');
const goal={school_id:'s',dept_id:'d',year:2027,degree:'master',route:'exam',track:'special',program_code:'0812',program_name:'计算机'};
const p={page:'m',school:'s',dept:'d',email:'a@b.edu',supervisor:'硕士生导师'};
const prefs={year:2027,degree:'master',route:'exam',track:'special',program:'0812|计算机',schools:['s'],topics:[],keep_unknown:false,modes:{research:'off',qualification:'off',email:'off',opportunity:'hard',eligibility:'off'}};
const project={id:'a',complete:true,goal_snapshot:goal};
const row={id:'r',project_id:'a',mentor_id:'m',goal_snapshot:goal,applicable:true,opportunity_status:'pass',eligibility_status:'unknown',checked_at:'2026-10-15',reasons:[]};
const evaluate=(r=row,pr=project,ps=prefs)=>core.evaluate(p,ps,{generic:{mentor_id:'m',year:2027,degree:'master',route:'exam',opportunity:'fail',checked_at:'2026-10-15'}},'','2026-10-15',{project:pr,project_reviews:{r}});
assert.equal(evaluate().checks.find(c=>c.key==='opportunity').state,'pass','valid precise project review replaces generic protection');
assert.equal(evaluate({...row,project_id:'b'}).checks.find(c=>c.key==='opportunity').state,'unknown','other project cannot apply');
assert.equal(evaluate({...row,opportunity_status:'fail'}).visible,false,'project hard fail excludes');
assert.equal(evaluate({...row,opportunity_status:'unknown',reasons:['expired']}).visible,false,'valid project permits exclude unknown');
assert.equal(evaluate({...row,goal_snapshot:{...goal,program_name:'其他'}}).checks.find(c=>c.key==='opportunity').state,'unknown');
assert.equal(evaluate(row,project,{...prefs,year:2028}).visible,true,'changed browsing scope suspends project filters');
assert.equal(evaluate(row,project,{...prefs,schools:['s','other']}).visible,true,'multiple schools do not silently use project context');
assert.equal(evaluate({...row,applicable:false,opportunity_status:'pass',reasons:['evidence_changed']}).checks.find(c=>c.key==='opportunity').state,'unknown');
assert.equal(core.evaluate(p,prefs,{},'','2026-10-15').visible,true,'no project retains special protection');
console.log('PASS project review isolation, exact goal, hard/unknown and scope conflict');

const ordinary={...prefs,track:'ordinary',program:''};
assert.equal(core.evaluate(p,ordinary,{old:{mentor_id:'m',year:2027,degree:'master',route:'exam',opportunity:'pass',checked_at:'2026-10-15'}},'','2026-10-15',{projectIntent:true}).checks.find(c=>c.key==='opportunity').state,'unknown');

assert.equal(evaluate(row,project,{...prefs,goal_snapshot:{...goal,program_name:'旧专业'}}).checks.find(c=>c.key==='opportunity').state,'unknown','external program change requires explicit reselect');
assert.equal(evaluate({...row,eligibility_status:'unknown',eligibility_reasons:['evidence_missing']}).checks.find(c=>c.key==='opportunity').state,'pass','one invalid source does not erase the other judgment');
assert.equal(evaluate({...row,checked_at:'2026-08-01',opportunity_status:'pass'}).checks.find(c=>c.key==='opportunity').state,'unknown','expired client state cannot retain pass');
assert.equal(evaluate({...row,mentor_id:'other'}).checks.find(c=>c.key==='opportunity').state,'unknown');
assert.equal(core.reviewReason('source_unavailable'),'登记来源当前不可用或检查已过期');

const assert=require('node:assert/strict'),test=require('node:test'),core=require('../site/discovery-core.js');
const p={page:'fixture-cs-a',school:'fixture',supervisor:'硕士生导师',email:'mentor@example.edu'};
const prefs={year:2027,degree:'master',route:'exam',topics:[],schools:[],keep_unknown:true,modes:{research:'off',qualification:'soft',email:'soft',opportunity:'hard',eligibility:'hard'}};
const review=state=>({mentor_id:p.page,year:2027,degree:'master',route:'exam',checked_at:'2026-10-14',opportunity:state,eligibility:state,quote:'旧范围核验'});
const evaluate=(context,state)=>core.evaluate(p,{...prefs,...context},{old:review(state)},'','2026-10-14');
test('specific programmes and special scope never gain score from legacy pass',()=>{
  for(const context of [{track:'special'},{track:'ordinary',program:'085400|工程专项'},{track:'special',program:'085400|菁英班'}]){
    const result=evaluate(context,'pass');assert.equal(result.score,2);assert.equal(result.review,undefined);
    for(const key of ['opportunity','eligibility'])assert.equal(result.checks.find(c=>c.key===key).state,'unknown');
  }
});
test('legacy fail cannot exclude unsupported programme/special scope candidates',()=>{
  for(const context of [{track:'special'},{program:'085400|工程专项'},{program:'085400|菁英班',keep_unknown:false}])assert.equal(evaluate(context,'fail').visible,true);
});
test('ordinary unspecified scope retains legacy judgement and other checks remain normal',()=>{
  assert.equal(evaluate({track:'ordinary'},'pass').score,4);
  assert.equal(evaluate({track:'ordinary'},'fail').visible,false);
  const result=core.evaluate({...p,email:''},{...prefs,track:'special'}, {old:review('pass')},'','2026-10-14');
  assert.equal(result.checks.find(c=>c.key==='email').state,'unknown');assert.equal(result.checks.find(c=>c.key==='qualification').state,'pass');
});

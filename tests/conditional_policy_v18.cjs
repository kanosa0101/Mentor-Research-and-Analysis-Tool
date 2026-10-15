const assert=require('node:assert/strict'),test=require('node:test'),rules=require('../site/admissions-core.js');
const prefs={school:'nwpu',dept:'cs',year:'2027',degree:'master',route:'exam',track:'ordinary',program:'081200|计算机科学与技术'};
const base={id:'school',school:'nwpu',dept:'',level:'school',year:2027,degree:'master',route:'exam',track:'ordinary',fields:{materials:{text:'一般材料'}},review_hashes:{s:'hash'},source_id:'s',reviewed_at:'2026-10-15',events:[{label:'普通报名',at:'2026-10-24',kind:'deadline'}]};
const condition={text:'仅适用于6112报考点考生',quote:'考点接收考生范围',locator:'二（二）',source_ids:['s']};
const data={units:[{school:'nwpu',dept:'cs'}],policies:[base,{...base,id:'point',applies_if:condition,events:[{label:'考点补充材料',at:'2026-10-31',kind:'deadline'}]},{...base,id:'program',level:'program',dept:'cs',program_code:'081200',program:'计算机科学与技术'}],checks:{s:{status:'ok',hash:'hash',last_success:'2026-10-15'}}};
test('explicit applies_if remains conditional even with a selected program; general and selected-program events remain usable',()=>{
 const result=rules.checklist(data,prefs,'2026-10-15');
 assert.equal(result.items.find(x=>x.key==='materials').rows.find(x=>x.policy.id==='point').conditional,true);
 assert.deepEqual(result.events.filter(x=>!x.conditional).map(x=>x.policy.id),['school','program']);
 assert.equal(result.events.find(x=>x.policy.id==='point').policy.applies_if,condition);
});
test('unspecified program protection remains alongside explicit conditions',()=>{
 const result=rules.checklist(data,{...prefs,program:''},'2026-10-15');
 assert.deepEqual(result.events.filter(x=>!x.conditional).map(x=>x.policy.id),['school']);
});

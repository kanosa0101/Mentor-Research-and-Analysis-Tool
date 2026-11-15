const assert=require('node:assert/strict'),rules=require('../site/opportunities-core.js');
const now='2026-11-15T12:00:00+08:00';
const base={id:'fixture',kind:'research_program',title:'科研实践',unit:'校内项目',school_name:'学校',eligibility:['仅限本校学生'],cycle:'current',source_state:'verified',checked_at:'2026-11-15',verified_at:'2026-11-15',registration_start:'2026-11-01',deadline:'',published_at:'2026-11-01'};
const rolling={...base,application_window:{mode:'rolling',end_month:'',quote:'长期接受申请'}};
const month={...base,application_window:{mode:'month',end_month:'2026-12',quote:'受理申请至2026年12月'}};
const cases=[
  [rolling,now,'rolling'],
  [{...rolling,registration_start:''},now,'rolling'],
  [{...rolling,registration_start:'2026-12-01'},now,'upcoming'],
  [{...rolling,source_state:'unavailable'},now,'review'],
  [{...rolling,checked_at:'2026-11-07'},now,'review'],
  [{...rolling,verified_at:'2026-10-15'},now,'review'],
  [{...rolling,checked_at:'2026-11-08',verified_at:'2026-10-16'},now,'rolling'],
  [{...rolling,cycle:'historical'},now,'closed'],
  [{...rolling,deadline:'2026-11-14'},now,'closed'],
  [{...rolling,deadline:'2026-11-16'},now,'open'],
  [{...rolling,event_end:'2026-11-14',deadline:'2026-11-16'},now,'closed'],
  [month,now,'open_month'],
  [{...month,registration_start:''},now,'unknown'],
  [{...month,registration_start:'2026-11-20'},now,'upcoming'],
  [{...month,source_state:'unavailable'},now,'review'],
  [{...month,checked_at:'2026-12-01',verified_at:'2026-12-01'},'2026-12-01T00:00:00+08:00','unknown'],
  [{...month,checked_at:'2026-12-31',verified_at:'2026-12-31'},'2026-12-31T23:59:59+08:00','unknown'],
  [{...month,source_state:'unavailable'},'2026-12-31T16:00:00Z','closed'],
  [{...month,deadline:'2026-12-20',checked_at:'2026-12-01',verified_at:'2026-12-01'},'2026-12-01T00:00:00+08:00','open'],
  [{...month,event_end:'2026-11-14'},now,'closed'],
];
for(const [item,date,expected] of cases)assert.equal(rules.state(item,date),expected,JSON.stringify({item,date}));
const fixed={...base,id:'fixed',deadline:'2026-11-30'};
assert.deepEqual(rules.select([rolling,month,fixed],{status:'current'},now).map(o=>rules.state(o,now)),['open','open_month','rolling']);
assert.deepEqual(rules.select([rolling,month,fixed],{status:'rolling'},now),[rolling]);
assert.deepEqual(rules.select([rolling,month,fixed],{status:'open_month'},now),[month]);
assert.deepEqual(rules.select([rolling,month,fixed],{status:'open'},now),[fixed]);
assert.equal(rules.select([rolling],{year:'2028',status:'current'},now).length,1);
assert.deepEqual(rules.changes(month,{...month,application_window:{...month.application_window,end_month:'2027-01'}}).map(x=>x.key),['application_window']);
assert.deepEqual(rules.changes(base,{...base,source_attachments:[{url:'https://example.edu/apply.docx',sha256:'a'.repeat(64),checked_at:'2026-11-15',field_evidence:{materials:{quote:'不得使用AI代写',locator:'申请表第2段'}}}]}).map(x=>x.key),['source_attachments']);
assert.equal(month.deadline,'');
assert.equal(rolling.deadline,'');
console.log(`${cases.length} opportunity window date cases plus filters/order/change boundaries passed`);

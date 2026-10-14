const assert=require('node:assert/strict'),test=require('node:test'),rules=require('../site/admissions-core.js');
const prefs={school:'test',dept:'cs',year:'2027',degree:'master',route:'exam',track:'ordinary'};
const base={school:'test',dept:'',level:'school',year:2027,degree:'master',route:'exam',reviewed_at:'2026-10-14',review_hashes:{source:'old'},source_id:'source',fields:{eligibility:{text:'学校资格',quote:'资格',locator:'第一条'}}};
const school={...base,id:'school'},dept={...base,id:'dept',dept:'cs',level:'dept',track:'ordinary',fields:{eligibility:{text:'院系资格',quote:'院系',locator:'第二条'}}};
const program={...dept,id:'program',level:'program',program:'电子信息',program_code:'085400',fields:{exams:{text:'408',quote:'408',locator:'第三条'}},events:[{kind:'deadline',at:'2026-09-12',label:'报名截止',quote:'9月12日',locator:'第四条'}]};
const data={policies:[school,dept,program,{...dept,id:'special',track:'special'},{...dept,id:'last-year',year:2026},{...dept,id:'recommend',route:'recommend'},{...dept,id:'other',dept:'ai'}],units:[{school:'test',dept:'cs'}],sources:{source:{url:'https://example.edu/policy'}},checks:{source:{status:'ok',hash:'old',last_success:'2026-10-14'}}};
const checklist=(d=data,p=prefs)=>{assert.equal(typeof rules.checklist,'function','checklist API must exist');return rules.checklist(d,p,'2026-10-14','2026-10-14T00:00:00Z');};
test('complete target retains all school, department and program requirements',()=>{
  const result=checklist();assert.equal(result.ready,true);assert.deepEqual(result.policies.map(p=>p.id),['school','dept','program']);assert.equal(result.items.length,8);
  assert.deepEqual(result.items.find(i=>i.key==='eligibility').rows.map(r=>r.field?.text),['学校资格','院系资格',undefined]);
  assert.equal(result.items.find(i=>i.key==='funding').rows.every(r=>!r.field),true);
  assert.equal(result.items.find(i=>i.key==='exams').rows[2].policy.source_id,'source');
  assert.equal(result.items.find(i=>i.key==='exams').rows[2].conditional,true,'未选专业仅作条件性参考');
  assert.equal(result.events[0].state,'past');
});
test('a selected program cannot borrow another program while retaining general layers',()=>{
  const d={...data,policies:[...data.policies,{...program,id:'program-081200',program_code:'081200',program:'计算机科学与技术'}]};
  assert.deepEqual(checklist(d,{...prefs,program:'085400|电子信息'}).policies.map(p=>p.id),['school','dept','program']);
  assert.equal(checklist(d,{...prefs,program:'085400|电子信息'}).items.find(i=>i.key==='exams').rows[2].conditional,false);
  assert.deepEqual(checklist(d,{...prefs,program:'other'}).policies.map(p=>p.id),['school','dept']);
});
test('special programmes never borrow another project rules',()=>{
  const d={...data,policies:[school,{...dept,id:'engineering',track:'special',program:'工程硕博士专项',program_code:'085400'},{...dept,id:'elite',track:'special',program:'菁英班',program_code:'085400'}]};
  assert.deepEqual(checklist(d,{...prefs,track:'special',program:'085400|菁英班'}).policies.map(p=>p.id),['school','elite']);
  assert.deepEqual(checklist(d,{...prefs,track:'special',program:'085400'}).policies.map(p=>p.id),['school']);
  assert.equal(checklist(d,{...prefs,track:'special'}).items[0].rows[1].conditional,true);
});
test('blank scope and invalid values request a complete target',()=>{
  for(const key of Object.keys(prefs)){const result=checklist(data,{...prefs,[key]:''});assert.equal(result.ready,false);assert.ok(result.missing.includes(key));assert.equal(result.items.length,0);}
  for(const [key,value] of [['year','unknown'],['route','other'],['degree','other'],['track','general'],['dept','missing'],['school','missing']])assert.equal(checklist(data,{...prefs,[key]:value}).ready,false);
});
test('year, channel and ordinary/special scopes never borrow other requirements',()=>{
  assert.deepEqual(checklist(data,{...prefs,track:'special'}).policies.map(p=>p.id),['school','special']);
  assert.deepEqual(checklist(data,{...prefs,year:'2028'}).policies,[]);
  assert.deepEqual(checklist(data,{...prefs,route:'assessment'}).policies,[]);
  assert.equal(checklist(data,{...prefs,year:'2028'}).items.length,8);
});
test('changed, failed, stale and missing checks remain recheck states per requirement',()=>{
  for(const [state,checks] of [['changed',{source:{...data.checks.source,hash:'new'}}],['error',{source:{...data.checks.source,status:'error'}}],['stale',{source:{...data.checks.source,last_success:'2026-10-01'}}],['unknown',{}]]){
    assert.equal(checklist({...data,checks}).items[0].rows[0].quality.state,state);
  }
});
test('field and event references use their actual sources while legacy fields retain primary',()=>{
  assert.equal(typeof rules.sourceReferences,'function');
  const sources={source:{url:'https://example.edu/formal.pdf',format:'pdf',label:'正式报名通知'},secondary:{url:'https://example.edu/pre-registration.pdf',format:'pdf',label:'预报名材料PDF'}};
  const material={text:'仅在预报名PDF',source_ids:['secondary']};
  assert.deepEqual(rules.sourceReferences(school,material,sources),[{id:'secondary',...sources.secondary}]);
  assert.deepEqual(rules.sourceReferences(school,{source_ids:['source','secondary']},sources).map(s=>s.label),['正式报名通知','预报名材料PDF']);
  assert.deepEqual(rules.sourceReferences(school,school.fields.eligibility,sources).map(s=>s.url),['https://example.edu/formal.pdf']);
  assert.equal(rules.sourceReferences(school,undefined,{source:{url:'https://example.edu/old.pdf',format:'pdf'}})[0].label,'PDF原文');
});

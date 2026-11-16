const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {spawnSync}=require('node:child_process'),rules=require('../site/admissions-core.js');
const root=path.resolve(__dirname,'..');
const result=spawnSync(process.env.PYTHON||'python',['-c',`
import json
from pathlib import Path
from scripts.build_site import application_payload
def read(name):
    return json.loads((Path('site')/name).read_text(encoding='utf8').split('=',1)[1].strip().removesuffix(';'))
admissions=read('admissions-data.js')
print(json.dumps({'full':admissions,'script':application_payload(read('contact-data.js'),admissions)},ensure_ascii=True))
`],{cwd:root,encoding:'utf8',maxBuffer:32*1024*1024});
assert.equal(result.status,0,result.stderr);
const {full,script}=JSON.parse(result.stdout),context={window:{}};vm.runInNewContext(script,context);
const compact=JSON.parse(JSON.stringify(context.window.ADMISSIONS_DATA));
function snapshot(data,prefs,today){
  const r=rules.checklist(data,prefs,today,today+'T08:00:00Z');
  return {ready:r.ready,missing:r.missing,policies:r.policies.map(p=>p.id),
    items:r.items.map(i=>({key:i.key,rows:i.rows.map(v=>({id:v.policy.id,quality:v.quality,conditional:v.conditional,field:v.field}))})),
    events:r.events.map(v=>({id:v.policy.id,quality:v.quality,conditional:v.conditional,event:v.event,state:v.state}))};
}
let targets=0;
for(const p of full.policies){
  const unit=full.units.find(u=>u.school===p.school&&(!p.dept||u.dept===p.dept));
  assert.ok(unit,p.id);
  for(const program of ['',rules.programKey(p)])for(const track of ['ordinary','special'])for(const today of ['2026-11-16','2027-01-01']){
    const prefs={school:p.school,dept:unit.dept,year:p.year,degree:p.degree,route:p.route,track,program};
    assert.deepEqual(snapshot(compact,prefs,today),snapshot(full,prefs,today),JSON.stringify({id:p.id,prefs,today}));targets++;
  }
  const c=compact.policies.find(v=>v.id===p.id);
  assert.deepEqual(c.applies_if,p.applies_if,p.id+' conditions');
  for(const item of [...Object.values(p.fields),...(p.events||[]),p.applies_if].filter(Boolean))
    assert.deepEqual(rules.sourceReferences(c,item,compact.sources),rules.sourceReferences(p,item,full.sources),p.id+' official references');
}
assert.ok(targets>0);
assert.equal(compact.policies.some(p=>'material_actions' in p),false);
assert.match(fs.readFileSync(path.join(root,'site/templates/applications.html.j2'),'utf8'),/application-entry\.js/);
console.log('PASS: '+targets+' application target/time combinations preserve policy scope, conditions, events, source evidence and quality');

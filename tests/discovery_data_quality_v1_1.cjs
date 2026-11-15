const assert=require('node:assert/strict');
const R=require('../site/discovery-core.js');
const prefs={schools:[],topics:[],year:null,degree:'any',route:'unknown',keep_unknown:true,modes:{research:'hard',qualification:'soft',email:'hard',opportunity:'off',eligibility:'off'}};
for(const email of ['a@hnu.edu.cn13873160076','a@hnu.edu.cn0731-88821513','x@example.com,other@example.com','unknown@邮箱']){
  assert.equal(R.validEmail(email),false,email);
  assert.deepEqual(R.completeness({email}),[0]);
  const result=R.evaluate({page:'x',email},prefs,{});
  assert.equal(result.checks.find(c=>c.key==='email').state,'unknown');
  assert.equal(R.evaluate({page:'x',email},{...prefs,keep_unknown:false},{}).visible,false);
}
assert.equal(R.validEmail('name.surname+research@lab.example.edu.cn'),true);
assert.equal(R.validEmail('13755199943@139.com'),true,'a numeric local part is legitimate');
const empty='研究方向、Research Focus、社会兼职、Social Affiliations、暂无内容、暂无内容';
assert.equal(R.researchText(empty),'');
assert.deepEqual(R.completeness({research_direction_raw:empty}),[0]);
assert.equal(R.researchText('研究方向、Research Focus、图学习、社会兼职、Social Affiliations、暂无内容'),'图学习');
assert.equal(R.researchText('社会兼职推荐系统、Research Focus 学习算法'),'社会兼职推荐系统、Research Focus 学习算法','only whole placeholder tokens are removed');
const result=R.evaluate({page:'x',research_direction_raw:empty},{...prefs,topics:['graph']},{});
assert.equal(result.checks.find(c=>c.key==='research').state,'unknown');
console.log('discovery v1.1: contact validation, placeholder cleaning and unknown filtering passed');

const assert=require('node:assert/strict'),rules=require('../site/admissions-core.js');
const policy={reviewed_at:'2026-10-01',review_hashes:{official:'a'.repeat(64)},revalidation:{method:'unchanged-reviewed-policy-v1',checked_at:'2026-11-15T20:00:00+00:00',source_hashes:{official:'a'.repeat(64)}}};
const checks={official:{status:'ok',hash:'a'.repeat(64),last_success:'2026-11-16'}};
assert.equal(rules.quality(policy,checks,'2026-11-16').state,'checked');
assert.equal(rules.quality(policy,checks,'2026-11-16').confirmed_at,'2026-11-16');
assert.equal(policy.reviewed_at,'2026-10-01');
assert.equal(rules.quality({...policy,revalidation_invalid:true},checks,'2026-11-16').state,'review');
assert.equal(rules.quality({...policy,revalidation:null},checks,'2026-11-16').state,'review');
assert.equal(rules.quality({...policy,revalidation:{...policy.revalidation,source_hashes:{official:'b'.repeat(64)}}},checks,'2026-11-16').state,'review');
for(const [observation,expected] of [[{status:'error'},'error'],[{hash:'b'.repeat(64)},'changed'],[{last_success:'2026-10-01'},'stale']]){
  assert.equal(rules.quality(policy,{official:{...checks.official,...observation}},'2026-11-16').state,expected);
}
assert.equal(rules.quality(policy,{official:{...checks.official,last_success:'2026-12-17'}},'2026-12-17').state,'review');
console.log('Policy system reconfirmation preserves manual date, China timezone and source/version freshness gates.');

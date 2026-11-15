const assert=require('node:assert/strict'),{formatDate}=require('../site/opportunities-core.js');
assert.equal(formatDate('2026-11-30T17:00:00+08:00'),'2026年11月30日 17:00（北京时间）');
assert.equal(formatDate('2026-11-30T17:00:00Z'),'2026年12月1日 01:00（北京时间）');
assert.equal(formatDate('2026-11-30'),'2026年11月30日');
assert.equal(formatDate('2027-01'),'2027年1月');
assert.equal(formatDate(''), '');
assert.equal(formatDate('待官方通知'), '待官方通知');
console.log('Precise, date-only and month-only opportunity dates preserve their meaning.');

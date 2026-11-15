"""Storage and import boundaries; Node executes the same pure module as the browser."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PRELUDE = """
const c=require('./site/browser-library-core.js'),assert=require('node:assert/strict');
const target={id:'target_one',path:'recommend',year:2028,schools:[{id:'pku',name:'北京大学'}],interest:'安全',created_at:'2026-11-15'};
const todo={id:'todo_one',title:'核对材料',done:false,due_date:'2026-12-01',target_id:'target_one',created_at:'2026-11-15'};
const sample=()=>({version:1,targets:[structuredClone(target)],bookmarks:[],todos:[structuredClone(todo)]});
"""


@unittest.skipUnless(shutil.which('node'), 'Node required')
class BrowserLibraryTests(unittest.TestCase):
    def run_js(self, body):
        result = subprocess.run(['node', '-e', PRELUDE + body], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reading_new_browser_never_writes(self):
        self.run_js("const storage={getItem:()=>null,setItem:()=>assert.fail('unexpected write')};assert.deepEqual(c.read(storage),c.empty());")

    def test_roundtrip_preserves_independent_path_year(self):
        self.run_js("const data=sample();assert.deepEqual(c.parse(JSON.stringify(data)),data);assert.equal(data.targets[0].path,'recommend');assert.equal(data.targets[0].year,2028);assert.equal(data.targets[0].admission_year,undefined);")

    def test_backup_rejects_external_active_and_traversal_urls(self):
        urls = ['javascript:alert(1)', 'data:text/html,hi', 'file:///secret', 'https://evil.test/notices.html',
                '//evil.test/start.html', r'\\evil.test\x', '/api/workflow', 'p/../secret.html',
                '/p/%2e%2e/desk.html', 'https://user@browser-library.invalid/start.html', 'start.html\n']
        self.run_js("for(const url of " + json.dumps(urls) + "){assert.throws(()=>c.safeUrl(url),undefined,url);}")

    def test_safe_internal_links_are_canonical(self):
        self.run_js("for(const url of ['p/pku-cs-test.html','opportunities.html?id=camp','notices.html?notice_cycle=all&q=%E6%B5%8B%E8%AF%95','start.html#library'])assert.equal(c.safeUrl(url),url);")

    def test_encoded_unicode_mentor_names_work_but_encoded_separators_do_not(self):
        self.run_js("const url='p/'+encodeURIComponent('tsinghua-cs-yang（兼职）')+'.html';assert.equal(c.safeUrl(url),url);for(const bad of ['p/a%2fb.html','p/%252e%252e.html','p/a%5cb.html'])assert.throws(()=>c.safeUrl(bad));")

    def test_import_validates_every_entry_before_writing(self):
        self.run_js("let stored='original';const storage={setItem:(k,v)=>stored=v};const data=sample();data.bookmarks.push({id:'b',kind:'notice',title:'bad',url:'javascript:alert(1)',created_at:'2026-11-15'});assert.throws(()=>c.write(storage,data));assert.equal(stored,'original');")

    def test_unknown_fields_and_wrong_library_are_rejected(self):
        self.run_js("for(const data of [{version:2,targets:[],bookmarks:[],todos:[]},{...sample(),private_materials:['cv']},(()=>{const d=sample();d.targets[0].admission_year=2028;return d;})()])assert.throws(()=>c.validate(data));")

    def test_invalid_dates_duplicates_or_missing_target_are_rejected(self):
        self.run_js("for(const change of [d=>d.todos[0].due_date='2026-02-30',d=>d.todos[0].target_id='missing',d=>d.todos[0].done='yes',d=>d.todos[0].id='target_one',d=>d.targets[0].schools.push({...d.targets[0].schools[0]})]){const d=sample();change(d);assert.throws(()=>c.validate(d));}")

    def test_size_limits_prevent_unbounded_import(self):
        self.run_js("assert.throws(()=>c.parse('x'.repeat(2000001)));const d=c.empty();d.bookmarks=Array(501).fill({});assert.throws(()=>c.validate(d));")

    def test_bookmark_save_deduplicates_kind_and_url(self):
        self.run_js("const item={kind:'mentor',title:'导师',url:'p/pku-cs-test.html'};const first=c.bookmark(c.empty(),item),again=c.bookmark(first.data,item);assert.equal(first.duplicate,false);assert.equal(again.duplicate,true);assert.equal(again.data.bookmarks.length,1);")

    def test_merge_keeps_existing_records_and_adds_new_only(self):
        self.run_js("const original=sample(),backup=sample();backup.todos[0].done=true;backup.todos.push({...todo,id:'todo_two',title:'新的待办'});const merged=c.merge(original,backup);assert.equal(merged.todos.length,2);assert.equal(merged.todos[0].done,false);assert.equal(original.todos.length,1);")

    def test_removing_target_preserves_todos_as_independent(self):
        self.run_js("const original=sample(),after=c.remove(original,'targets','target_one');assert.equal(after.targets.length,0);assert.equal(after.todos.length,1);assert.equal(after.todos[0].target_id,'');assert.equal(original.targets.length,1);")

    def test_storage_failure_is_not_reported_as_success(self):
        self.run_js("assert.throws(()=>c.write({setItem:()=>{throw new Error('quota');}},sample()),/quota/);assert.throws(()=>c.read({getItem:()=>'{broken'}));")


if __name__ == '__main__':
    unittest.main()

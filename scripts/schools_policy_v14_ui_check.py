"""v14 school picker, stable discovery ranking and policy recency; isolated private files."""
import copy
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.serve import create_server

def main():
    out=ROOT/'cache/ux_v14/schools-policy'
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);site=root/'site';(site/'p').mkdir(parents=True)
        rows=[dict(page=f'{school}-cs-{i}',name=f'导师{i}',school=school,school_name={'a':'甲大学','b':'乙大学','c':'丙大学'}[school],dept='cs',dept_name='计算机学院',title='教授',supervisor='博导',email='public@example.edu',research_direction_raw='图学习',unit_groups=['computer']) for i in range(66) for school in ['abc'[i%3]]]
        compare={p['page']:{'research_direction_raw':p['research_direction_raw'],'provenance':{'research_direction_raw':{'source':'https://example.edu/profile','fetched_at':'2026-09-05'}}} for p in rows}
        for p in rows:(site/'p'/(p['page']+'.html')).write_text('<p>临时导师</p>',encoding='utf-8')
        for filename,variable,data in [('data.js','MENTOR_DATA',rows),('compare-data.js','MENTOR_COMPARE',compare),('search.js','MENTOR_SEARCH',{})]:
            (site/filename).write_text('window.'+variable+'='+json.dumps(data,ensure_ascii=False),encoding='utf-8')
        for filename in ('discovery.js','discovery-core.js','admissions.js','admissions-core.js','ui.css'):shutil.copyfile(ROOT/'site'/filename,site/filename)
        env=Environment(loader=FileSystemLoader(ROOT/'site/templates'))
        for name in ('discovery','admissions'):(site/(name+'.html')).write_text(env.get_template(name+'.html.j2').render(),encoding='utf-8')
        data=json.loads((ROOT/'site/admissions-data.js').read_text(encoding='utf-8').split('=',1)[1].strip().rstrip(';'))
        sample=next(p for p in data['policies'] if p.get('events'))
        policies=[]
        for id,at,kind,review in [('past','2026-10-14','deadline','2026-10-15'),('unknown','2026-10-16','exam','2026-10-15'),('today','2026-10-15','deadline','2026-10-14'),('future','2026-10-16','deadline','2026-10-15')]:
            p=copy.deepcopy(sample);p.update(id=id,title=id,reviewed_at=review)
            event=copy.deepcopy(p['events'][0]);event.update(at=at,kind=kind,label=id);p['events']=[event];policies.append(p)
        data['policies']=policies
        for c in data['checks'].values():c.update(status='ok',last_success='2026-10-10',last_attempt='2026-10-15')
        first_source=next(iter(policies[0]['review_hashes']))
        data['checks'][first_source].update(status='error')
        (site/'admissions-data.js').write_text('window.ADMISSIONS_DATA='+json.dumps(data,ensure_ascii=False),encoding='utf-8')
        server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0)
        threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.add_init_script("sessionStorage.setItem('discovery-order-seed','fixed');const NativeDate=Date;window.Date=class extends NativeDate{constructor(...a){super(...(a.length?a:['2026-10-15T04:00:00Z']));}static now(){return new NativeDate('2026-10-15T04:00:00Z').getTime();}}")
                def visit(path,ready='DISCOVERY_READY'):
                    page.goto(base+path);page.wait_for_function('window.'+ready)
                def selected():return page.evaluate('readCriteria().schools')
                def checkbox(id):return page.locator(f'#school-options input[value="{id}"]')
                def apply():page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                visit('/discovery.html')
                first=page.locator('[data-candidate]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.candidate)')
                assert first!=[r['page'] for r in rows[:20]], 'not source-order first page'
                assert len(set(id.split('-')[0] for id in first))==3
                assert not page.locator('#intent-schools').is_visible()
                assert page.locator('#school-search').is_visible(), 'schools available without expanding advanced rules'
                checkbox('a').check();checkbox('b').check()
                assert selected()==['b','a'] or set(selected())=={'a','b'}
                assert page.locator('#criteria-dirty').is_visible()
                assert page.locator('[data-candidate]').count()==20
                page.fill('#school-search','丙')
                assert page.locator('#school-options label:visible').count()==1
                assert set(selected())=={'a','b'}
                page.locator('[data-remove-school="a"]').click()
                assert selected()==['b']
                page.click('#clear-schools');assert selected()==[]
                page.fill('#school-search','');checkbox('a').focus();page.keyboard.press('Space');checkbox('b').check()
                apply();assert page.locator('[data-candidate]').count()==20
                assert page.evaluate('view.every(r=>["a","b"].includes(r.p.school))')
                stable=page.evaluate('view.map(r=>r.p.page)');page.click('#more-candidates')
                displayed=page.locator('[data-candidate]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.candidate)')
                assert len(displayed)==40 and len(set(displayed))==40 and displayed==stable[:40]
                apply();assert page.evaluate('view.map(r=>r.p.page)')==stable
                page.click('#save-criteria');page.wait_for_function('document.querySelector("#discovery-message").textContent.includes("已保存")')
                with page.expect_download() as dl:page.click('#discovery-backup')
                backup=root/'backup.json';dl.value.save_as(str(backup))
                visit('/discovery.html');assert set(selected())=={'a','b'}
                page.click('#clear-schools');page.click('#save-criteria');page.wait_for_function('document.querySelector("#discovery-message").textContent.includes("已保存")')
                page.once('dialog',lambda dialog:dialog.accept());page.set_input_files('#discovery-file',str(backup));page.wait_for_function('document.querySelector("#discovery-message").textContent.includes("已恢复")');assert set(selected())=={'a','b'}
                visit('/discovery.html?school=c&dept=cs&track=special&program=0854%7Ctest')
                assert selected()==['c'];page.click('#clear-unit-context');assert set(selected())=={'a','b'}
                assert page.evaluate('view.every(r=>r.result.checks.filter(c=>["opportunity","eligibility"].includes(c.key)).every(c=>c.state==="unknown"))')
                visit('/discovery.html?school=c&dept=cs')
                apply();assert page.evaluate('contextSchool==="c"&&contextDept==="cs"'), 'same-school selection keeps its department'
                checkbox('a').check();assert set(selected())=={'a','c'}
                assert page.evaluate('contextSchool===""&&contextDept===""')
                assert not page.locator('#unit-context').is_visible() and 'school=' not in page.url and 'dept=' not in page.url
                apply();assert page.evaluate('view.some(r=>r.p.school==="a")&&view.some(r=>r.p.school==="c")')
                visit('/discovery.html?school=c&dept=cs');page.click('#clear-schools');apply()
                assert selected()==[] and len(page.evaluate('view.map(r=>r.p.page)'))==66, 'clear means all schools, no hidden department restriction'
                assert '学校不限' in page.locator('#intent-overview').inner_text()
                visit('/discovery.html?school=c&dept=cs&track=special&program=0854%7Ctest')
                checkbox('a').check();checkbox('c').uncheck();apply()
                assert selected()==['a'] and page.evaluate('view.every(r=>r.p.school==="a")')
                assert page.evaluate('projectScoped&&contextSchool===""&&contextDept===""')
                assert 'track=special' in page.url and 'program=0854%7Ctest' in page.url
                assert '核验保护保留' in page.locator('#project-context').inner_text()
                assert page.evaluate('view.every(r=>r.result.checks.filter(c=>["opportunity","eligibility"].includes(c.key)).every(c=>c.state==="unknown"))')
                assert page.locator('#mode-opportunity').is_disabled() and page.locator('#mode-eligibility').is_disabled()
                page.reload();page.wait_for_function('window.DISCOVERY_READY')
                assert page.evaluate('projectScoped') and page.locator('#mode-eligibility').is_disabled(), 'refresh preserves the special-program protection'
                for width in [1440,390]:
                    page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(out/f'schools-{width}.png'),full_page=True)
                    page.screenshot(path=str(out/f'schools-{width}-viewport.png'))
                visit('/admissions.html','ADMISSIONS_READY')
                assert page.locator('[data-policy]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.policy)')==['future','today','unknown','past']
                assert page.locator('#policy-today .policy-timing').inner_text().startswith('有尚未过去')
                assert '截止时间未完整整理' in page.locator('#policy-unknown .policy-timing').inner_text()
                age=page.locator('#policy-past > .policy-age').inner_text()
                assert '官方发布' in age and '最近成功回源 2026-10-10' in age and '检查失败' in age and '摘要核对 2026-10-15' in age
                assert '最近成功回源 2026-10-15' not in age
                assert page.locator('#policy-past .quality.error').count()>0
                dates=page.evaluate("""()=>{const p={review_hashes:{testA:'a',testB:'b'}};for(const id of ['testA','testB'])ADMISSIONS_DATA.sources[id]={url:'https://example.edu'};ADMISSIONS_DATA.checks.testA={status:'ok',last_success:'2026-10-10'};ADMISSIONS_DATA.checks.testB={status:'ok',last_success:'2026-10-09'};const oldest=successfulSourceDate(p);ADMISSIONS_DATA.checks.testB.last_success='2026-02-30';const invalid=successfulSourceDate(p);delete ADMISSIONS_DATA.checks.testB;const missing=successfulSourceDate(p);return {oldest,invalid,missing};}""")
                assert dates['oldest']=='2026-10-09'
                assert '暂无完整成功记录' in dates['invalid'] and '日期异常' in dates['invalid']
                assert '暂无完整成功记录' in dates['missing']
                for width in [1440,390]:
                    page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(out/f'policy-{width}.png'),full_page=True)
                    page.locator('#policy-list').scroll_into_view_if_needed()
                    page.screenshot(path=str(out/f'policy-{width}-viewport.png'))
                assert not errors,errors
                browser.close()
        finally:server.shutdown();server.server_close()
    print('v14 schools / stable ranking / policy recency UI passed; private files isolated')
if __name__=='__main__':main()

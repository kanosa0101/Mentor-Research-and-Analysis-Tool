"""Public scope navigation regressions; isolated public fixtures and private files only."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
SOURCE=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT
sys.path.insert(0,str(ROOT))
from crawler.discovery_util import empty
from scripts.serve import create_server


def main():
    out=ROOT/'cache/system_v13/public'
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);site=root/'site';(site/'p').mkdir(parents=True)
        for name in ['discovery.js','discovery-core.js','admissions.js','admissions-core.js','admissions-data.js','ui.css']:
            shutil.copyfile(SOURCE/'site'/name,site/name)
        rows=[dict(page=pid,name=name,school=school,school_name=school,dept='cs',dept_name='计算机',title='教授',supervisor='硕导',email='test@example.edu',research_direction_raw='图学习',unit_groups=['computer'],facets=[],provenance={}) for pid,name,school in [('bit-cs-a','甲导师','bit'),('pku-cs-b','乙导师','pku')]]
        for name,var,data in [('data.js','MENTOR_DATA',rows),('compare-data.js','MENTOR_COMPARE',{r['page']:r for r in rows}),('search.js','MENTOR_SEARCH',{})]:
            (site/name).write_text('window.'+var+'='+json.dumps(data,ensure_ascii=False),encoding='utf8')
        env=Environment(loader=FileSystemLoader(SOURCE/'site/templates'))
        for name in ['discovery','compare','admissions']:(site/(name+'.html')).write_text(env.get_template(name+'.html.j2').render(),encoding='utf8')
        sources={key:dict(url='https://example.edu/'+key,fetched_at='2026-10-01',error='') for key in ['bit/cs','pku/cs']}
        (site/'notices.html').write_text(env.get_template('notices.html.j2').render(sources=sources,notices=[]),encoding='utf8')
        for row in rows:(site/'p'/(row['page']+'.html')).write_text(env.get_template('detail.html.j2').render(p=row),encoding='utf8')
        (site/'desk.html').write_text('contact destination',encoding='utf8');(site/'applications.html').write_text('project destination',encoding='utf8')
        private=root/'private';private.mkdir();data=empty();data['preferences']['schools']=['pku']
        (private/'discovery.yaml').write_text(yaml.safe_dump(data,allow_unicode=True),encoding='utf8');before=(private/'discovery.yaml').read_bytes()
        server=create_server(site=site,outreach=private/'outreach.yaml',port=0)
        threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
        scope='school=bit&dept=cs&year=2027&degree=master&route=recommend&track=special&program=0854%7Ctest&project=secret&target=secret&notes=secret'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                for width in [1440,390]:
                    page=browser.new_page(viewport={'width':width,'height':900});errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else r.fulfill(status=200,body=''))
                    def visit(path,ready=None):
                        page.goto(base+path,wait_until='domcontentloaded')
                        if ready:page.wait_for_function(ready)
                    def q(selector):return parse_qs(urlparse(page.locator(selector).first.get_attribute('href')).query)
                    def nav_scope(expected):
                        for dest in ['discovery','admissions','notices','desk']:
                            value=q('.site-header nav a[href*="'+dest+'.html"]')
                            assert all(value.get(k)==[v] for k,v in expected.items()),(dest,value,expected)
                            assert not {'project','target','notes'}&value.keys(),value
                    visit('/discovery.html?'+scope,'window.DISCOVERY_READY')
                    page.click('#clear-unit-context');page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                    assert page.locator('#intent-schools').evaluate('(s)=>[...s.selectedOptions].map(o=>o.value)')==['pku'],'clear must restore original private school filter'
                    assert page.locator('[data-candidate="pku-cs-b"]').count()==1
                    assert not {'school','dept','program','track'}&parse_qs(urlparse(page.url).query).keys(),'clear must update URL'
                    assert page.locator('#review-save').is_disabled(),'existing project review protection must remain in current session'
                    nav_scope({'year':'2027','degree':'master','route':'recommend'})
                    assert 'program' not in q('.site-header nav a[href*="admissions.html"]')
                    page.reload(wait_until='networkidle');page.wait_for_function('window.DISCOVERY_READY');assert page.locator('[data-candidate="pku-cs-b"]').count()==1
                    visit('/discovery.html?'+scope,'window.DISCOVERY_READY');page.locator('#advanced-criteria summary').click();page.locator('#school-options input[value="bit"]').check();page.locator('#school-options input[value="pku"]').check()
                    assert page.locator('#clear-unit-context').is_hidden(), 'explicit multi-school selection exits the old unit scope'
                    assert set(page.evaluate('readCriteria().schools')) == {'bit','pku'}
                    assert parse_qs(urlparse(page.url).query).get('track') == ['special'], 'special protection must survive school selection'
                    page.click('#apply-criteria')
                    page.wait_for_function('!document.querySelector("#apply-criteria").disabled');assert page.locator('[data-candidate]').count()==2,'clear must keep user edited school filters'
                    visit('/discovery.html','window.DISCOVERY_READY');nav_scope({'school':'pku'});page.locator('#advanced-criteria summary').click();page.locator('#school-options input[value="pku"]').uncheck();page.locator('#school-options input[value="bit"]').check();nav_scope({'school':'pku'});page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled');nav_scope({'school':'bit'});page.locator('#school-options input[value="bit"]').check();page.locator('#school-options input[value="pku"]').check();page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled');assert 'school' not in q('.site-header nav a[href*="admissions.html"]')
                    visit('/discovery.html?'+scope,'window.DISCOVERY_READY');page.locator('#advanced-criteria summary').click();page.fill('#intent-year','2028')
                    nav_scope({'school':'bit','dept':'cs','year':'2027','degree':'master','route':'recommend','track':'special','program':'0854|test'})
                    page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled');nav_scope({'year':'2028'})
                    page.click('[data-compare="bit-cs-a"]');page.click('#compare-open');page.wait_for_load_state('domcontentloaded');nav_scope({'school':'bit','dept':'cs','year':'2028'})
                    page.locator('.pcol .pn a').click();page.wait_for_load_state('domcontentloaded');nav_scope({'school':'bit','dept':'cs','year':'2028'})
                    visit('/p/pku-cs-b.html?'+scope);nav_scope({'school':'pku','dept':'cs','year':'2027'});assert 'program' not in q('.site-header nav a[href*="notices.html"]')
                    visit('/admissions.html?'+scope,'window.ADMISSIONS_READY');nav_scope({'school':'bit','dept':'cs','year':'2027','track':'special'})
                    assert '尚未覆盖' in page.locator('#policy-list').inner_text()
                    page.select_option('#policy-school','pku');nav_scope({'school':'pku','year':'2027'});assert 'program' not in q('.site-header nav a[href*="notices.html"]');assert 'track' not in q('.site-header nav a[href*="notices.html"]');page.reload(wait_until='domcontentloaded');page.wait_for_function('window.ADMISSIONS_READY');assert page.locator('#policy-school').input_value()=='pku' and page.locator('#policy-track').input_value()==''
                    visit('/notices.html?'+scope);page.wait_for_function('document.querySelector("#count").textContent.includes("条候选通知")');nav_scope({'school':'bit','dept':'cs','year':'2027','track':'special'});page.select_option('#school','pku/cs');nav_scope({'school':'pku','dept':'cs','year':'2027'});assert 'track' not in q('#notice-policy-link') and 'program' not in q('#notice-policy-link');page.reload(wait_until='domcontentloaded');page.wait_for_function('document.querySelector("#count").textContent.includes("条候选通知")');assert page.locator('#school').input_value()=='pku/cs' and 'track' not in q('#notice-policy-link')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                    visit('/admissions.html?school=bit&dept=cs&year=invalid#policy-list','window.ADMISSIONS_READY');assert parse_qs(urlparse(page.url).query).get('year')==['invalid'] and urlparse(page.url).fragment=='policy-list';page.reload(wait_until='domcontentloaded');page.wait_for_function('window.ADMISSIONS_READY');assert '无效年度' in page.locator('#policy-count').inner_text()
                    page.screenshot(path=str(out/f'public-flow-{width}.png'),full_page=True)
                    assert not errors,errors
                    page.close()
                browser.close()
            assert (private/'discovery.yaml').read_bytes()==before,'private filter changed'
            print('PASS: public clear/restored and edited schools/refresh/applied scope/navigation/cross-unit special/privacy/empty/mobile')
        finally:server.shutdown();server.server_close()

if __name__=='__main__':main()

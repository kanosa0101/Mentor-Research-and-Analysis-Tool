"""Policy return links: real local applications UI, intercepted API and target page only."""
import copy
import json
import shutil
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'cache/policy_v20/material_policy_return'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base_goal = dict(school_id='fudan', dept_id='cs', year=2027, degree='master',
                     route='exam', track='ordinary', program_code='', program_name='')
    projects = {}
    cases = {
        'empty': {},
        'normal': dict(school_id='tsinghua', program_code='085400', program_name='电子信息'),
        'special': dict(school_id='tsinghua', year=2026, degree='phd', route='assessment',
                        track='special', program_code='081200', program_name='计算机科学与技术'),
        'unknown-dept': dict(dept_id='unknown-dept'),
        'missing-dept': dict(dept_id=''),
        'missing-goal': dict(school_id='', dept_id='', year=None, degree='', route='', track=''),
        'code-only': dict(program_code='085400'),
        'name-only': dict(program_name='电子信息'),
    }
    for pid, change in cases.items():
        projects[pid] = dict(id=pid, name='临时项目 ' + pid, status='planned', mentor_ids=[],
                             notes='', deadlines=[], **(base_goal | change))
    workflow = dict(version=3, projects=projects, materials={}, communications={}, reminders={})
    action = dict(id='fixture-upload', label='合成材料动作', stage='application',
                  instruction=dict(text='合成测试材料要求', quote='测试原文', locator='合成测试'))
    data = dict(actions={'normal': [dict(policy_id='fixture', policy_title='合成测试政策',
                action_id=action['id'], action=action, action_fingerprint='fixture',
                conditions=[], program_pending=False, quality=dict(state='checked', label='合成来源'),
                events=[], latest_record_id=None)]}, records={})
    writes, errors, seen = [], [], []

    def api(route):
        req = route.request
        if req.method != 'GET':
            writes.append(dict(url=req.url, method=req.method))
            route.fulfill(status=400, json={'error': 'Unexpected write'})
            return
        result = data if '/material-tasks' in req.url else workflow
        route.fulfill(json=copy.deepcopy(result))

    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp)
        for name in ['workflow.js', 'material-actions.js', 'data.js', 'admissions-data.js',
                     'admissions-core.js', 'ui.css']:
            shutil.copyfile(ROOT / 'site' / name, site / name)
        env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'))
        (site / 'applications.html').write_text(env.get_template('applications.html.j2').render(), encoding='utf-8')
        (site / 'admissions.html').write_text('<!doctype html><title>Local target stub</title><p>Scope URL target only</p>', encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=tmp))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        origin = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                for width in [1440, 390]:
                    page = browser.new_page(viewport={'width': width, 'height': 1000})
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.route('**/api/workflow**', api)
                    # Empty first: this assertion must fail before implementation.
                    for pid in cases:
                        page.goto(origin + '/applications.html?section=preparation&project=' + pid)
                        page.wait_for_function('window.WORKFLOW_READY')
                        page.wait_for_function('(pid)=>document.querySelector("#preparation-list").textContent.includes("临时项目 "+pid)', arg=pid)
                        link = page.locator('#preparation-list a').filter(has_text='核对本项目政策与材料要求')
                        count = link.count()
                        if count != 1:
                            (OUT / 'red.json').write_text(json.dumps(dict(case=pid, width=width,
                                policy_links=count, text=page.inner_text('#preparation-list')), ensure_ascii=False, indent=2), encoding='utf-8')
                        assert count == 1, f'{pid}: expected policy return link, found {count}'
                        p = projects[pid]
                        expected = {k: str(v) for k, v in dict(school=p['school_id'], dept=p['dept_id'],
                            year=p['year'], degree=p['degree'], route=p['route'], track=p['track'],
                            program=((p['program_code'] or '') + '|' + p['program_name']) if p['program_name'] else '').items() if v}
                        href = link.get_attribute('href')
                        assert urlsplit(href).path == 'admissions.html'
                        assert parse_qs(urlsplit(href).query) == {k:[v] for k,v in expected.items()}, (pid, href)
                        if pid in ['unknown-dept', 'missing-dept', 'missing-goal']:
                            assert '编辑项目' in page.inner_text('#preparation-list')
                            button = page.locator('#preparation-list [data-edit-project]')
                            assert button.get_attribute('data-edit-project') == pid
                            button.click()
                            assert page.locator('#section-project').is_visible()
                            assert page.input_value('#project-name') == p['name']
                            page.click('[data-section="preparation"]')
                        if pid == 'code-only':
                            assert '专业' in page.inner_text('#preparation-list') and '编辑项目' in page.inner_text('#preparation-list')
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (pid,width)
                        if pid in ['empty', 'normal']:
                            page.screenshot(path=str(OUT / f'{pid}-{width}.png'), full_page=True)
                        link.click()
                        page.wait_for_url('**/admissions.html*')
                        assert parse_qs(urlsplit(page.url).query) == {k:[v] for k,v in expected.items()}
                        seen.append(dict(case=pid, width=width, query=expected))
                    # In-place project changes must replace the link scope, including after normal actions.
                    page.goto(origin + '/applications.html?section=preparation&project=normal')
                    page.wait_for_function('window.WORKFLOW_READY')
                    for pid in ['empty', 'special', 'normal']:
                        page.select_option('#filter-project', pid)
                        page.wait_for_function('(pid)=>document.querySelector("#preparation-list").textContent.includes("临时项目 "+pid)', arg=pid)
                        href=page.locator('#preparation-list a').filter(has_text='核对本项目政策与材料要求').get_attribute('href')
                        query=parse_qs(urlsplit(href).query)
                        assert query['school']==[projects[pid]['school_id']]
                        assert query['track']==[projects[pid]['track']]
                    # The new edit shortcut must participate in the existing dirty-input guard.
                    data['actions']['code-only']=copy.deepcopy(data['actions']['normal'])
                    page.select_option('#filter-project','code-only')
                    page.wait_for_selector('[data-material-action]',state='attached')
                    form=page.locator('[data-material-action]').first
                    form.locator('xpath=..').locator(':scope > summary').click()
                    form.locator('[name="notes"]').fill('保留未保存的准备备注')
                    page.once('dialog',lambda dialog:dialog.dismiss())
                    page.locator('#preparation-list [data-edit-project]').click()
                    assert page.locator('#section-preparation').is_visible()
                    assert form.locator('[name="notes"]').input_value()=='保留未保存的准备备注'
                    page.once('dialog',lambda dialog:dialog.accept())
                    page.locator('#preparation-list [data-edit-project]').click()
                    assert page.locator('#section-project').is_visible()
                    assert page.input_value('#project-name')==projects['code-only']['name']
                    data['actions'].pop('code-only')
                    page.close()
                assert not writes, writes
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    result=dict(status='pass', clicked_scopes=seen, writes=writes, browser_errors=errors,
                target='local stub; verifies actual navigation query only', viewport_widths=[1440,390])
    (OUT/'green.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS policy-return: empty/actions, exact scope/unknown/code-only, project switches, no POST, real clicks, 1440/390 no overflow')


if __name__ == '__main__':
    main()

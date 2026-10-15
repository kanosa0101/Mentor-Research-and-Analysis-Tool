"""Reminder actions retain their own scope, using temporary private records only."""
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site


def main():
    out = ROOT / 'cache/ux_v11/desk-actions'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        server = create_server(site=render_test_site(root), outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base + '/desk.html')
                page.wait_for_function('window.CONTACT_READY')
                mentors = page.evaluate('MENTOR_DATA.slice(0,2).map(p=>p.page)')
                a = page.evaluate('api("/projects",{name:"临时 A 申请",year:2027},"POST")')
                b = page.evaluate('api("/projects",{name:"临时 B 申请",year:2027},"POST")')
                target = page.evaluate('(x)=>api("/targets",x,"POST")', {'project_id': a['id'], 'mentor_id': mentors[0]})
                rows = [
                    {'title': 'B 项目事项', 'project_id': b['id']},
                    {'title': '全局事项', 'mentor_id': mentors[1]},
                    {'title': 'B 导师事项', 'project_id': b['id'], 'mentor_id': mentors[1]},
                    {'title': 'A 导师事项', 'project_id': a['id'], 'mentor_id': mentors[0]},
                ]
                for row in rows:
                    page.evaluate('(x)=>api("/reminders",x,"POST")', dict(row, due_date='2099-01-01'))
                desk = base + '/desk.html?' + urlencode({'project': a['id'], 'target': target['id'], 'view': 'today'})
                page.goto(desk)
                page.wait_for_function('window.CONTACT_READY')
                card = lambda title: page.locator('#future-task-list article').filter(has=page.get_by_role('heading', name=title, exact=True))
                href = card('B 项目事项').get_by_role('link', name='管理任务').get_attribute('href')
                q = parse_qs(urlsplit(href).query)
                assert q.get('project') == [b['id']], 'B reminder must not inherit current A target/project'
                assert q.get('section') == ['reminder'] and 'target' not in q and 'mentor' not in q
                for width, height in ((1440, 1000), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.screenshot(path=str(out / f'desk-reminders-{width}.png'), full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                for title, project, mentor in [('B 项目事项', b['id'], ''), ('全局事项', '', mentors[1]), ('B 导师事项', b['id'], mentors[1])]:
                    page.goto(desk)
                    page.wait_for_function('window.CONTACT_READY')
                    link = card(title).get_by_role('link', name='管理任务')
                    q = parse_qs(urlsplit(link.get_attribute('href')).query)
                    assert q.get('project', [''])[0] == project
                    assert q.get('mentor', [''])[0] == mentor
                    assert q.get('section') == ['reminder'] and 'target' not in q
                    awaitable = page.evaluate('api()')
                    link.click()
                    page.wait_for_function('window.WORKFLOW_READY')
                    assert page.input_value('#filter-project') == project
                    assert page.input_value('#reminder-project') == project
                    assert page.locator('#reminder-form').is_visible()
                    assert page.evaluate('contextMentor') == mentor
                    assert title in page.inner_text('#reminder-list')
                    assert page.evaluate('api()') == awaitable, 'navigation must not mutate workflow'
                    for public in page.locator('a[href*="admissions.html"],a[href*="discovery.html"],a[href^="p/"]').evaluate_all('(links)=>links.map(a=>a.href)'):
                        query = parse_qs(urlsplit(public).query)
                        assert not {'project', 'target'} & query.keys()
                    if title == 'B 项目事项':
                        page.screenshot(path=str(out / 'applications-b-reminders-390.png'), full_page=True)
                page.goto(desk)
                page.wait_for_function('window.CONTACT_READY')
                button = card('A 导师事项').get_by_role('button', name='继续该导师')
                assert button.get_attribute('data-continue-target') == target['id']
                button.click()
                assert page.evaluate('currentTarget') == target['id']
                assert page.locator('#prepare-detail').is_visible()
                assert not errors, errors
                browser.close()
                print('desk_actions_v11_ui_check: PASS (project, global, mentor scope; navigation read-only; continue target; 390/1440)')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

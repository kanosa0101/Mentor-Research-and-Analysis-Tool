"""Workflow regression checks against rendered temporary pages and private records."""
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server


def render_test_site(root):
    site = root / 'site'
    site.mkdir()
    for name in ('data.js', 'admissions-data.js', 'admissions-core.js', 'ui.css', 'desk.js', 'workflow.js'):
        shutil.copyfile(ROOT / 'site' / name, site / name)
    env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'))
    for name in ('desk', 'applications'):
        (site / (name + '.html')).write_text(env.get_template(name + '.html.j2').render(), encoding='utf-8')
    (site / "p").mkdir()
    for page in (ROOT / "site/p").glob("*.html"):
        (site / "p" / page.name).write_text("fixture", encoding="utf-8")
    return site


def main():
    out = ROOT / 'cache/ux_v8/workflow/after'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = render_test_site(root)
        server = create_server(site=site, outreach=root / 'private/outreach.yaml', port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/applications.html', wait_until='networkidle')
                page.wait_for_function('window.WORKFLOW_READY')
                pid = page.evaluate('MENTOR_DATA[0].page')
                other_pid = page.evaluate('MENTOR_DATA[1].page')
                mentor_scope = page.evaluate('({school: MENTOR_DATA[0].school, dept: MENTOR_DATA[0].dept})')
                page.goto(base + '/desk.html?' + urlencode(dict(mentor=pid, track='special', program='0854|test', **mentor_scope)), wait_until='networkidle')
                page.wait_for_function('window.CONTACT_READY')
                assert page.locator('#prepare-empty a').count() == 1
                scope_query = parse_qs(urlsplit(page.locator('#prepare-empty a').get_attribute('href')).query)
                assert scope_query['program'] == ['0854|test'] and scope_query['track'] == ['special']
                assert scope_query['school'] == [mentor_scope['school']] and scope_query['dept'] == [mentor_scope['dept']]
                page.click('#prepare-empty a')
                page.wait_for_function('window.WORKFLOW_READY')
                project = page.evaluate('(pid)=>api("/projects", {name:"2027 回归项目",year:2027,mentor_ids:[pid]}, "POST")', pid)
                flow = page.evaluate('api()')
                target = next(iter(flow['targets']))
                page.goto(base + '/applications.html?mentor=' + other_pid + '&target=' + target + '&year=2099&section=reminder', wait_until='networkidle')
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.input_value('#filter-project') == project['id'], 'target project context must be selected'
                assert page.input_value('#reminder-project') == project['id']
                assert page.evaluate('chosen.reminder[0]') == pid, 'actual target mentor overrides contradictory URL'
                assert page.input_value('#project-year') == '', 'stale URL must not prefill another project'
                assert page.locator('#reminder-form').is_visible()
                assert not page.locator('#project-form').is_visible()
                for count, title in enumerate(('核对截止', '补充材料'), 1):
                    page.fill('#reminder-title', title)
                    page.fill('#reminder-due', '2027-01-01')
                    page.click('#reminder-save')
                    page.wait_for_function('(n)=>Object.keys(WORKFLOW.reminders).length===n', arg=count)
                    assert page.input_value('#reminder-project') == project['id']
                assert page.locator('#reminder-list article').count() == 2
                page.route('**/api/workflow/reminders', lambda route: route.fulfill(status=400, content_type='application/json', body='{"error":"测试保存失败"}') if route.request.method == 'POST' else route.continue_())
                page.fill('#reminder-title', '失败后保留')
                page.fill('#reminder-due', '2027-01-03')
                page.click('#reminder-save')
                page.wait_for_function('document.querySelector("#reminder-feedback").textContent.includes("测试保存失败")')
                assert page.input_value('#reminder-title') == '失败后保留'
                assert page.input_value('#reminder-project') == project['id']
                page.unroute('**/api/workflow/reminders')
                page.fill('#reminder-title', '不能丢失')
                page.once('dialog', lambda d: d.dismiss())
                page.click('[data-section="project"]')
                assert page.input_value('#reminder-title') == '不能丢失'
                assert page.locator('#reminder-form').is_visible()
                page.once('dialog', lambda d: d.accept())
                page.click('#reminder-reset')
                page.screenshot(path=str(out / 'applications-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(out / 'applications-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.click('#back-desk')
                page.wait_for_function('window.CONTACT_READY')
                assert page.locator('#draft-form').is_visible()
                assert not page.locator('#task-form').is_visible(), 'mail is the only default prepare panel'
                page.fill('#draft-body', '未保存邮件')
                page.once('dialog', lambda d: d.dismiss())
                page.click('[data-panel="tasks"]')
                assert page.locator('#draft-form').is_visible()
                assert page.input_value('#draft-body') == '未保存邮件'
                assert 'panel=mail' in page.url
                page.once('dialog', lambda d: d.dismiss())
                page.click('#draft-manage')
                assert '/desk.html' in page.url
                assert page.input_value('#draft-body') == '未保存邮件'
                page.once('dialog', lambda d: d.accept())
                page.click('#draft-new')
                page.click('[data-panel="tasks"]')
                page.reload(wait_until='networkidle')
                page.wait_for_function('window.CONTACT_READY')
                assert page.locator('#task-form').is_visible()
                assert not page.locator('#draft-form').is_visible()
                page.locator('.site-tools summary').click()
                page.click('#manage-link')
                page.wait_for_function('window.WORKFLOW_READY')
                assert 'panel=tasks' in page.locator('#back-desk').get_attribute('href')
                page.click('#back-desk')
                page.wait_for_function('window.CONTACT_READY')
                assert page.locator('#task-form').is_visible()
                for count, title in enumerate(('独立提醒一', '独立提醒二'), 3):
                    page.fill('#task-title', title)
                    page.fill('#task-due', '2027-02-01')
                    page.click('#task-save')
                    page.wait_for_function('(n)=>Object.keys(FLOW.reminders).length===n', arg=count)
                    assert page.locator('#task-form').is_visible(), 'save retains current panel'
                assert page.locator('#target-task-list article').count() == 4
                page.locator('[data-task-edit]').first.click()
                page.fill('#task-due', '2027-03-01')
                page.click('#task-save')
                page.wait_for_function('Object.values(FLOW.reminders).some(r=>r.due_date==="2027-03-01")')
                page.locator('[data-task-toggle]').first.click()
                page.wait_for_function('Object.values(FLOW.reminders).some(r=>r.completed)')
                page.locator('[data-task-toggle]').last.click()
                page.wait_for_function('Object.values(FLOW.reminders).every(r=>!r.completed)')
                page.fill('#task-title', '保留输入')
                page.once('dialog', lambda d: d.dismiss())
                page.click('[data-panel="reply"]')
                assert page.locator('#task-form').is_visible()
                assert page.input_value('#task-title') == '保留输入'
                page.once('dialog', lambda d: d.dismiss())
                page.click('[data-view="today"]')
                assert page.locator('#task-form').is_visible()
                assert page.input_value('#task-title') == '保留输入'
                page.once('dialog', lambda d: d.accept())
                page.click('[data-view="today"]')
                assert page.locator('#task-list article').count() == 0
                assert page.locator('#future-task-list article').count() == 4
                page.screenshot(path=str(out / 'today-mobile.png'), full_page=True)
                page.click('[data-view="prepare"]')
                page.click('[data-panel="mail"]')
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(out / 'prepare-mobile-viewport.png'))
                page.screenshot(path=str(out / 'prepare-mobile-full.png'), full_page=True)
                for panel in ('tasks', 'reply', 'history'):
                    page.click('[data-panel="' + panel + '"]')
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(out / ('prepare-' + panel + '-mobile.png')))
                page.click('[data-panel="mail"]')
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(out / 'prepare-desktop-viewport.png'))
                assert not errors, errors
                browser.close()
                print('PASS: project context, repeated reminders, section and view guards, standalone tasks, due/future split, mobile')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    main()

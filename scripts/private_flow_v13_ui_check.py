"""Private project navigation regression, using only a temporary service and fixtures."""
import json
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site


def main():
    out = ROOT / 'cache/system_v13/private'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        root = Path(tmp)
        server = create_server(site=render_test_site(root), outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + '/applications.html')
                page.wait_for_function('window.WORKFLOW_READY')
                assert '学校与招生目标可以随后补充' in page.inner_text('#project-list')
                assert not page.locator('#project-feedback').is_visible()
                mentor = page.evaluate('MENTOR_DATA[0].page')
                a = page.evaluate('p=>api("/projects",p,"POST")', {'name': '合成项目 A', 'mentor_ids': [mentor]})['id']
                b = page.evaluate('p=>api("/projects",p,"POST")', {'name': '合成项目 B', 'mentor_ids': [mentor]})['id']
                data = page.evaluate('api()')
                ta = next(t['id'] for t in data['targets'].values() if t['project_id'] == a)
                tb = next(t['id'] for t in data['targets'].values() if t['project_id'] == b)
                page.goto(base + f'/applications.html?project={a}&target={ta}&mentor={mentor}&year=2099&section=reminder')
                page.wait_for_function('window.WORKFLOW_READY')
                page.fill('#reminder-title', '未保存的 A 提醒')
                old_url = page.url
                old_back = page.locator('#back-desk').get_attribute('href')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.select_option('#filter-project', b)
                assert page.input_value('#filter-project') == a
                assert page.url == old_url
                assert page.locator('#back-desk').get_attribute('href') == old_back
                assert page.input_value('#reminder-title') == '未保存的 A 提醒'
                assert page.locator('#section-reminder').is_visible()
                page.once('dialog', lambda dialog: dialog.accept())
                page.select_option('#filter-project', b)
                query = parse_qs(urlsplit(page.url).query)
                assert query['project'] == [b] and query['section'] == ['reminder']
                assert 'target' not in query and 'year' not in query
                assert page.input_value('#reminder-project') == b
                page.evaluate('refresh()')
                assert page.input_value('#filter-project') == b
                page.reload()
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.input_value('#filter-project') == b
                back = parse_qs(urlsplit(page.locator('#back-desk').get_attribute('href')).query)
                assert back['project'] == [b] and 'target' not in back
                page.click('#back-desk')
                page.wait_for_function('window.CONTACT_READY')
                assert page.evaluate('currentTarget') == tb
                assert page.evaluate('target().project_id') == b
                assert page.evaluate('currentTarget') != ta
                page.goto(base + f'/applications.html?project={b}&target={tb}&mentor={mentor}&section=reminder')
                page.wait_for_function('window.WORKFLOW_READY')
                page.select_option('#filter-project', '')
                query = parse_qs(urlsplit(page.url).query)
                assert not any(key in query for key in ('project', 'target', 'mentor'))
                assert page.locator('#back-desk').get_attribute('href') == 'desk.html?view=today'
                page.reload()
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.input_value('#filter-project') == ''
                assert page.evaluate('contextMentor') == ''
                # Empty feedback hides no actionable errors.
                page.evaluate('message("合成错误提示",true)')
                assert page.locator('#reminder-feedback').is_visible()
                assert page.inner_text('#reminder-feedback') == '合成错误提示'
                for width, height in ((1440, 1000), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(out / f'context-fixed-{width}.png'))
                assert not errors, errors
                # The same instant must have one application calendar day in every browser timezone.
                dated = browser.new_page(timezone_id='America/Los_Angeles')
                dated.clock.install(time=datetime(2026, 10, 15, 17, 0, tzinfo=timezone.utc))
                dated.goto(base + f'/desk.html?target={tb}&view=prepare')
                dated.wait_for_function('window.CONTACT_READY')
                assert dated.evaluate('today()') == '2026-10-16'
                assert dated.input_value('#sent-date') == '2026-10-16'
                assert dated.input_value('#reply-date') == '2026-10-16'
                dated.evaluate('p=>api("/reminders",p,"POST")', {'title': '上海今天', 'project_id': b, 'due_date': '2026-10-16'})
                dated.evaluate('refresh()')
                assert dated.inner_text('#stat-due') == '1'
                dated.goto(base + f'/applications.html?project={b}&section=communication')
                dated.wait_for_function('window.WORKFLOW_READY')
                assert dated.input_value('#communication-date') == '2026-10-16'
                dated.click('[data-section="project"]')
                assert '今天' in dated.inner_text('#project-list')
                assert '上海今天' in dated.inner_text('#project-list')
                dated.close()
                browser.close()
                print('private_flow_v13_ui_check: PASS (dirty cancel, B refresh/reload/back, same mentor B target, global clear, feedback, Shanghai day in LA browser, 1440/390)')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

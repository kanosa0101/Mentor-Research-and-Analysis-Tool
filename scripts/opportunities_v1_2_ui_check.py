"""Exercise public handoff and local activity updates without real private writes."""
import copy
import json
import shutil
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import opportunity_util
from scripts import serve, serve_public
from scripts.release_page_v1_ui_check import signatures

ACTIVITY = 'iscas-research-2026'


def render(root, catalog):
    site = root / 'site'
    site.mkdir()
    for name in ['ui.css', 'data.js', 'admissions-data.js', 'admissions-core.js',
                 'material-actions.js', 'workflow.js', 'opportunities-core.js', 'opportunities.js']:
        shutil.copyfile(ROOT / 'site' / name, site / name)
    env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'), autoescape=True)
    for name in ['opportunities', 'applications', 'local']:
        (site / (name + '.html')).write_text(env.get_template(name + '.html.j2').render(), encoding='utf-8')
    payload = json.dumps(catalog, ensure_ascii=False).replace('<', '\\u003c')
    (site / 'opportunities-data.js').write_text('window.OPPORTUNITIES=' + payload + ';', encoding='utf-8')
    return site


def start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{server.server_port}'


def page_for(browser, width, base, errors, writes):
    page = browser.new_page(viewport={'width': width, 'height': 900})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD') else None)
    page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
    return page


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


def main():
    out = ROOT / 'cache/opportunities_v12_ui'
    out.mkdir(parents=True, exist_ok=True)
    before = signatures()
    original = opportunity_util.load(ROOT)
    assert any(item['id'] == ACTIVITY for item in original['opportunities'])
    current = copy.deepcopy(original)
    results = []
    with patch.object(opportunity_util, 'observed', side_effect=lambda root: copy.deepcopy(current)):
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (1440, 390):
                with tempfile.TemporaryDirectory(prefix='opportunities-v12-public-') as tmp:
                    root = Path(tmp)
                    render(root, original)
                    server = serve_public.create_server(root, '127.0.0.1', 0)
                    base = start(server)
                    errors, writes = [], []
                    page = page_for(browser, width, base, errors, writes)
                    try:
                        page.goto(base + '/opportunities.html', wait_until='networkidle')
                        card = page.locator(f'[data-opportunity="{ACTIVITY}"]')
                        action = card.get_by_role('link', name='在本机准备申请')
                        assert action.is_visible()
                        assert page.locator('[data-save-opportunity]').count() == 0
                        health = page.locator('#monitor-health').inner_text()
                        assert '服务器尚无可用监测记录' in health
                        assert '启动信息监测' not in health and '电脑休眠' not in health
                        no_overflow(page)
                        page.screenshot(path=str(out / f'public-{width}.png'), full_page=True)
                        action.click()
                        assert parse_qs(urlsplit(page.url).query)['id'] == [ACTIVITY]
                        local = urlsplit(page.locator('#open-local').get_attribute('href'))
                        assert local.hostname == '127.0.0.1' and local.port == 8000
                        assert local.path == '/opportunities.html'
                        assert parse_qs(local.query)['id'] == [ACTIVITY]
                        no_overflow(page)
                        # A known-public session must lose its open claim when refresh fails.
                        open_item = copy.deepcopy(next(item for item in original['opportunities'] if item['id'] == ACTIVITY))
                        today = opportunity_util.today()
                        open_item.update(id='ui-open-fixture', title='验收用报名中活动',
                                         registration_start=(today - timedelta(days=1)).isoformat(),
                                         deadline=(today + timedelta(days=7)).isoformat(),
                                         verified_at=today.isoformat(), checked_at=today.isoformat())
                        current['opportunities'].append(open_item)
                        page.goto(base + '/opportunities.html', wait_until='networkidle')
                        assert page.locator('.opportunity-state.open').count() == 1
                        page.route('**/api/opportunities', lambda route: route.fulfill(
                            status=503, content_type='application/json', body='{"error":"UI failure fixture"}'))
                        page.locator('#monitor-refresh').click()
                        page.wait_for_function("document.querySelector('#monitor-health').textContent.includes('暂时无法读取')")
                        assert page.locator('.opportunity-state.open').count() == 0
                        assert page.locator('[data-save-opportunity]').count() == 0
                        assert not page.locator('#opportunity-save').is_visible()
                        assert page.locator('[data-opportunity="ui-open-fixture"] .opportunity-state.review').count() == 1
                        no_overflow(page)
                        page.screenshot(path=str(out / f'public-api-failure-{width}.png'), full_page=True)
                        assert not errors and not writes, (errors, writes)
                        results.append(dict(mode='public', width=width, passed=True, handoff_id=ACTIVITY,
                                            public_empty_monitor_copy=True, api_failure_downgraded=True,
                                            write_requests=writes, page_errors=errors))
                    finally:
                        page.close()
                        server.shutdown()
                        server.server_close()
                current = copy.deepcopy(original)
                with tempfile.TemporaryDirectory(prefix='opportunities-v12-local-') as tmp:
                    root = Path(tmp)
                    site = render(root, original)
                    private = root / 'private'
                    server = serve.create_server(site=site, outreach=private / 'outreach.yaml', port=0)
                    base = start(server)
                    errors, writes = [], []
                    page = page_for(browser, width, base, errors, writes)
                    try:
                        page.goto(base + '/opportunities.html?id=' + ACTIVITY, wait_until='networkidle')
                        page.locator(f'[data-save-opportunity="{ACTIVITY}"]').click()
                        assert page.locator('#opportunity-save').is_visible()
                        page.locator('#opportunity-name').fill('科创计划申请验收')
                        page.locator('#opportunity-reminder').fill(page.locator('#opportunity-reminder').get_attribute('min'))
                        page.locator('#opportunity-confirm').click()
                        page.wait_for_function("!document.querySelector('#opportunity-save').open")
                        saved = page.request.get(base + '/api/workflow').json()
                        assert len(saved['projects']) == len(saved['reminders']) == 1
                        project = next(iter(saved['projects'].values()))
                        expected = next(item for item in original['opportunities'] if item['id'] == ACTIVITY)
                        assert project['opportunity'] == expected
                        stored = (private / 'workflow.yaml').read_bytes()
                        page.locator('#opportunity-result a').click()
                        page.wait_for_function('window.WORKFLOW_READY')
                        change = page.locator('[data-opportunity-changes]')
                        page.wait_for_function("document.querySelector('[data-opportunity-changes]').textContent.includes('未发现差异')")
                        page.wait_for_load_state('networkidle')
                        assert page.get_by_text('邮件初选：个人简历', exact=True).is_visible()
                        changed = next(item for item in current['opportunities'] if item['id'] == ACTIVITY)
                        changed['deadline'] = '2027-01-20'
                        changed['materials'] = [*changed['materials'], '验收模拟变更：补充研究计划']
                        page.reload(wait_until='networkidle')
                        page.wait_for_function('window.WORKFLOW_READY')
                        page.wait_for_function("document.querySelector('[data-opportunity-changes]').textContent.includes('查看变更')")
                        page.wait_for_load_state('networkidle')
                        text = change.inner_text()
                        assert '2027-01-20' in text and '验收模拟变更：补充研究计划' in text
                        assert '保存时：' in text and '当前记录：' in text
                        assert '个人准备进度和提醒日期未自动修改' in text
                        assert (private / 'workflow.yaml').read_bytes() == stored
                        after = page.request.get(base + '/api/workflow').json()
                        assert after['projects'] == saved['projects'] and after['reminders'] == saved['reminders']
                        no_overflow(page)
                        page.screenshot(path=str(out / f'project-changes-{width}.png'), full_page=True)
                        page.goto(base + '/opportunities.html', wait_until='networkidle')
                        page.locator('#opportunity-school').select_option('中国科学院大学')
                        page.locator('#opportunity-year').select_option('2028')
                        new = copy.deepcopy(changed)
                        new.update(id='ui-new-school', school_id='', dept_id='', school_name='验收新增学校',
                                   unit='验收新增院系', graduation_year=2029)
                        current['opportunities'].append(new)
                        page.locator('#monitor-refresh').click()
                        page.wait_for_function("[...document.querySelector('#opportunity-school').options].some(o=>o.value==='验收新增学校')")
                        page.wait_for_function("!document.querySelector('#monitor-refresh').disabled")
                        assert page.locator('#opportunity-year option[value="2029"]').count() == 1
                        assert page.locator('#opportunity-school').input_value() == '中国科学院大学'
                        assert page.locator('#opportunity-year').input_value() == '2028'
                        assert page.locator(f'[data-opportunity="{ACTIVITY}"]').is_visible(), 'Unknown graduation year should remain visible'
                        no_overflow(page)
                        assert not errors, errors
                        assert writes == [base + '/api/workflow/opportunities'], writes
                        results.append(dict(mode='local', width=width, passed=True, snapshot_preserved=True,
                                            reminders_preserved=True, differences_visible=True, new_filters_loaded=True,
                                            selections_preserved=True, page_errors=errors))
                    finally:
                        page.close()
                        server.shutdown()
                        server.server_close()
                current = copy.deepcopy(original)
            browser.close()
    assert signatures() == before, 'Real private data changed'
    (out / 'results.json').write_text(json.dumps(dict(passed=True, private_unchanged=True, results=results),
                                                ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS public handoff, local project snapshots, changed requirements, dynamic filters: 1440/390')


if __name__ == '__main__':
    main()

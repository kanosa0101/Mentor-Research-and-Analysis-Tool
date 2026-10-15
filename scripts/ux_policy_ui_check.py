"""Read-only policy UX checks using rendered templates in a temporary static site."""
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

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    output = ROOT / 'cache/ux_v8/policy/after'
    output.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'), autoescape=True)
    notices = json.loads((ROOT / 'data/notices.json').read_text(encoding='utf8'))
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp)
        for name in ['admissions.js', 'admissions-core.js', 'admissions-data.js', 'ui.css']:
            shutil.copy2(ROOT / 'site' / name, site / name)
        (site / 'admissions.html').write_text(env.get_template('admissions.html.j2').render(), encoding='utf8')
        (site / 'notices.html').write_text(env.get_template('notices.html.j2').render(**notices), encoding='utf8')
        failed_notices = copy.deepcopy(notices)
        failed_notices['sources']['tsinghua/cs']['error'] = 'simulated failure'
        (site / 'notices-errors.html').write_text(env.get_template('notices.html.j2').render(**failed_notices), encoding='utf8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(site)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}/'
        target = 'school=tsinghua&dept=cs&year=2027&degree=master&route=exam&track=ordinary'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for width in [1440, 390]:
                    page.set_viewport_size({'width': width, 'height': 900})
                    for name, url in [('admissions-empty', 'admissions.html'), ('admissions-target', 'admissions.html?' + target), ('notices-target', 'notices.html?' + target)]:
                        page.goto(base + url, wait_until='networkidle')
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        page.screenshot(path=str(output / f'{name}-{width}-viewport.png'))
                        page.screenshot(path=str(output / f'{name}-{width}-full.png'), full_page=True)
                        if name == 'admissions-empty':
                            assert page.locator('.policy-body[open]').count() == 0
                            assert page.locator('[data-policy]').count() == 13
                            assert '选择学校与院系' in page.locator('#unit-entries').inner_text()
                        if name == 'admissions-target':
                            assert page.locator('[data-checklist-field]').count() == 8
                            actions_y = page.locator('#checklist-mentors').bounding_box()['y']
                            assert actions_y < page.locator('[data-checklist-field]').first.bounding_box()['y']
                page.goto(base + 'admissions.html?' + target, wait_until='networkidle')
                page.select_option('#policy-program', index=1)
                program = page.input_value('#policy-program')
                page.locator('#checklist-notices').click()
                page.wait_for_load_state('networkidle')
                link = page.locator('#notice-policy-link').get_attribute('href')
                params = parse_qs(urlsplit(link).query)
                assert params['program'] == [program]
                for key, value in parse_qs(target).items():
                    assert params[key] == value
                assert page.locator('#school option:checked').inner_text() == '清华大学 · 计算机科学与技术系'
                assert page.locator('article:visible').count() == 8, 'Unknown years must not be excluded'
                page.locator('#notice-policy-link').click()
                page.wait_for_load_state('networkidle')
                assert page.input_value('#policy-program') == program
                page.locator('.policy-directory > summary').click()
                page.locator('[data-school="pku"]').click()
                assert page.input_value('#policy-program') == ''
                page.goto(base + 'admissions.html?' + target, wait_until='networkidle')
                page.select_option('#policy-program', index=1)
                page.locator('.policy-help > summary').first.click()
                page.select_option('#policy-group', index=1)
                assert page.input_value('#policy-program') == ''
                page.goto(base + 'admissions.html?school=pku&dept=cs&year=2028&degree=master&route=exam&track=ordinary', wait_until='networkidle')
                assert page.locator('[data-checklist-field]').count() == 8
                assert '8类要求均待查' in page.locator('#application-checklist').inner_text()
                page.goto(base + 'admissions.html?school=tsinghua&dept=wrong&year=2027', wait_until='networkidle')
                assert page.locator('[data-policy]').count() == 0
                page.goto(base + 'admissions.html?' + target, wait_until='networkidle')
                page.evaluate("ADMISSIONS_DATA.checks[ADMISSIONS_DATA.policies[0].source_id].status='error';render()")
                assert page.locator('.policy-card > .quality.error').first.is_visible()
                assert page.locator('.checklist-status.error').first.is_visible()
                # An unconnected known unit uses a registered official URL, never a guessed one.
                unit = page.evaluate("ADMISSIONS_DATA.units.find(u=>u.school==='zju'&&u.dept==='cs')")
                page.goto(base + 'notices.html?school=zju&dept=cs&year=2027', wait_until='networkidle')
                assert page.locator('#notice-empty').is_visible()
                assert page.locator('#current-source a').get_attribute('href') in [unit['notice_url'], unit['roster_url']]
                page.goto(base + 'notices.html?' + target + '&group=computer', wait_until='networkidle')
                page.select_option('#school', 'tsinghua/auto')
                cross_scope = parse_qs(urlsplit(page.locator('#notice-policy-link').get_attribute('href')).query)
                assert 'group' not in cross_scope
                assert cross_scope['dept'] == ['auto']
                page.locator('#notice-policy-link').click()
                page.wait_for_load_state('networkidle')
                assert page.input_value('#policy-dept') == 'auto'
                assert page.locator('[data-checklist-field]').count() == 8
                assert '未收录或无效' not in page.locator('#unit-description').inner_text()
                page.goto(base + 'notices.html?school=tsinghua&year=2027', wait_until='networkidle')
                school_scope = parse_qs(urlsplit(page.locator('#notice-policy-link').get_attribute('href')).query)
                assert school_scope == {'school': ['tsinghua'], 'year': ['2027']}
                visible_units = page.locator('article:visible').evaluate_all('(rows)=>rows.map(e=>e.dataset.school)')
                assert set(visible_units) == {'tsinghua/cs', 'tsinghua/auto'}
                assert page.locator('#current-source a').count() == 2
                assert '2 个院系栏目' in page.locator('#notice-context').inner_text()
                page.goto(base + 'notices.html?school=missing&year=2027', wait_until='networkidle')
                assert page.locator('article:visible').count() == 0
                assert parse_qs(urlsplit(page.locator('#notice-policy-link').get_attribute('href')).query) == {'school': ['missing'], 'year': ['2027']}
                page.goto(base + 'notices.html?school=missing&dept=unknown', wait_until='networkidle')
                assert page.locator('#current-source a').count() == 0
                assert '未登记官方入口' in page.locator('#current-source').inner_text()
                page.goto(base + 'notices.html?school=tsinghua%2Fcs&year=2027', wait_until='networkidle')
                page.fill('#search', 'zzzz_no_match')
                assert page.locator('#notice-empty').is_visible()
                page.locator('#clear-search').click()
                assert page.locator('article:visible').count() == 8
                page.goto(base + 'notices-errors.html?' + target, wait_until='networkidle')
                assert page.locator('[data-source-error="tsinghua/cs"]').is_visible()
                assert not page.locator('.notice-sources').get_attribute('open')
                page.select_option('#school', 'pku/cs')
                assert not page.locator('[data-source-error="tsinghua/cs"]').is_visible()
                assert not errors, errors
                # Direct static file access remains supported.
                page.goto((site / 'admissions.html').as_uri() + '?' + target, wait_until='networkidle')
                assert page.locator('[data-checklist-field]').count() == 8
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    print('Policy UX checks passed: context, reset, unknowns, sources, static mode, 1440/390 screenshots')


if __name__ == '__main__':
    main()

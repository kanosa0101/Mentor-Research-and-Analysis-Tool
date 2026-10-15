"""Candidate-card checks using synthetic public data and an isolated site."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server


def main():
    out = ROOT / 'cache/ux_v10/cards'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / 'site'
        site.mkdir()
        rows = [dict(page=f'test-{i}', name=name, school='test', school_name='测试大学', dept='cs',
                     dept_name='计算机学院', title='教授', supervisor='硕导', email=email,
                     research_direction_raw=direction, unit_groups=['computer'], facets=[])
                for i, (name, email, direction) in enumerate([
                    ('张方向', 'public@example.edu', '图学习、时空预测'),
                    ('张简介', '', ''), ('张空白', '', '')])]
        origin = {'source': 'https://example.edu/profile', 'fetched_at': '2026-10-10', 'origin': 'crawled'}
        compare = {'test-0': {'bio_excerpt': '不应替代方向的简介', 'provenance': {'research_direction_raw': origin, 'email': origin}},
                   'test-1': {'bio_excerpt': '从事视觉计算与神经形态感知研究。', 'provenance': {'bio_raw': dict(origin, origin='manual')}},
                   'test-2': {'bio_excerpt': '', 'provenance': {}}}
        for filename, variable, data in [('data.js', 'MENTOR_DATA', rows), ('compare-data.js', 'MENTOR_COMPARE', compare), ('search.js', 'MENTOR_SEARCH', {})]:
            (site / filename).write_text('window.'+variable+'='+json.dumps(data, ensure_ascii=False), encoding='utf-8')
        for filename in ('discovery.js', 'discovery-core.js', 'ui.css'):
            shutil.copyfile(ROOT / 'site' / filename, site / filename)
        env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'))
        (site / 'discovery.html').write_text(env.get_template('discovery.html.j2').render(), encoding='utf-8')
        server = create_server(site=site, outreach=root/'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.fulfill(status=200, body=''))
                page.goto(base+'/discovery.html')
                page.wait_for_function('window.DISCOVERY_READY')
                assert page.locator('#criteria-explanation').get_attribute('open') is None
                assert not page.locator('#intent-summary').is_visible()
                assert '不限' in page.locator('#intent-overview').inner_text()
                page.locator('#criteria-explanation summary').click()
                assert '规则：' in page.locator('#intent-summary').inner_text()
                assert '保留必须条件待核实' in page.locator('#intent-summary').inner_text()
                page.locator('#criteria-explanation summary').click()
                first = page.locator('[data-candidate="test-0"]')
                second = page.locator('[data-candidate="test-1"]')
                blank = page.locator('[data-candidate="test-2"]')
                assert '官网简介摘录' in second.inner_text(), 'existing bio must be visible when direction is absent'
                assert '从事视觉计算与神经形态感知研究。' in second.inner_text()
                assert '研究方向' in first.locator('.research-preview').inner_text()
                assert '不应替代方向' not in first.locator('.research-preview').inner_text()
                assert '简介' not in blank.locator('.research-preview').inner_text()
                assert '资料待补充' in blank.locator('.research-preview').inner_text()
                assert 'public@example.edu' in first.locator('.public-email').inner_text()
                assert page.locator('a[href^="mailto:"]').count() == 0
                assert '2026-10-10' in second.locator('.preview-source').inner_text()
                assert '人工录入于' in second.locator('.preview-source').inner_text()
                assert '采集于' in first.locator('.preview-source').inner_text()
                assert second.locator('.preview-source a').get_attribute('href') == origin['source']
                assert '采集日期未知' in blank.locator('.preview-source').inner_text()
                for card in (first, second, blank):
                    assert card.locator('.card-primary-actions > *').count() == 2
                    visible = card.inner_text()
                    assert '邮箱：命中' not in visible and '招生机会：待核实' not in visible
                    assert '申请资格：待核实' not in visible and '研究关键词：命中' not in visible
                    assert card.locator('.candidate-proof').get_attribute('open') is None
                    assert card.locator('.candidate-application').get_attribute('open') is None
                    card.locator('.candidate-proof summary').click()
                    assert all(text.strip() for text in card.locator('.checks li').all_inner_texts())
                    card.locator('.candidate-proof summary').click()
                first.locator('[data-compare]').click()
                assert page.locator('#compare-open').is_visible(), 'single selection remains accessible'
                page.fill('#intent-name', '张简介')
                assert page.locator('#criteria-dirty').is_visible()
                assert '张简介' not in page.locator('#intent-overview').inner_text()
                page.click('#apply-criteria')
                assert page.locator('[data-candidate]').count() == 1
                assert '张简介' in page.locator('#intent-overview').inner_text()
                page.locator('#criteria-explanation summary').click()
                assert '姓名：张简介' in page.locator('#intent-summary').inner_text()
                scope = '?school=test&dept=cs&year=2027&degree=master&route=recommend&track=special&program=0854%7Ctest&notes=private-secret'
                page.goto(base+'/discovery.html'+scope)
                page.wait_for_function('window.DISCOVERY_READY')
                first = page.locator('[data-candidate="test-0"]')
                first.locator('.candidate-application summary').click()
                for selector in ('.card-primary-actions a', '.candidate-application a'):
                    for href in first.locator(selector).evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("href"))'):
                        query = parse_qs(urlparse(href).query)
                        assert query['program'] == ['0854|test'] and query['year'] == ['2027'], query
                        assert 'notes' not in query
                assert first.locator('[data-review]').is_disabled()
                first.locator('.candidate-application summary').click()
                page.screenshot(path=str(out/'cards-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(out/'cards-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    print('cards v0.10 UI: PASS (synthetic data, isolated private path, desktop/mobile)')


if __name__ == '__main__':
    main()

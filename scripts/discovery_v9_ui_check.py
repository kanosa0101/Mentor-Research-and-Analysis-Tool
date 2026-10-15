"""Discovery regressions on synthetic public data and an isolated temporary site."""
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
    out = ROOT / 'cache/ux_v9/discovery'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / 'site'
        (site / 'p').mkdir(parents=True)
        rows = [dict(page=f'test-{i}', name=name, school='test', school_name='测试大学', dept=dept, dept_name=dept, title='教授', supervisor='硕导', email='test@example.edu', research_direction_raw=topic, institutes=[], provenance={}, bio_raw='', status='enriched', facets=[], unit_groups=['computer']) for i, (name, dept, topic) in enumerate([('张一', 'cs', '图学习'), ('张二', 'cs', '视觉'), ('Alice Smith', 'other', '图学习')])]
        (site / 'data.js').write_text('window.MENTOR_DATA='+json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        (site / 'compare-data.js').write_text('window.MENTOR_COMPARE='+json.dumps({p['page']: p for p in rows}, ensure_ascii=False), encoding='utf-8')
        (site / 'search.js').write_text('window.MENTOR_SEARCH={}', encoding='utf-8')
        for name in ('discovery.js', 'discovery-core.js', 'ui.css'):
            shutil.copyfile(ROOT / 'site' / name, site / name)
        env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'))
        for name in ('discovery', 'compare'):
            (site / (name+'.html')).write_text(env.get_template(name+'.html.j2').render(), encoding='utf-8')
        for p in rows:
            (site / 'p' / (p['page']+'.html')).write_text(env.get_template('detail.html.j2').render(p=p), encoding='utf-8')
        (site / 'desk.html').write_text('temporary contact destination', encoding='utf-8')
        server = create_server(site=site, outreach=root/'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        scope = '?school=test&dept=cs&year=2027&degree=master&route=recommend&track=special&program=0854%7Ctest&notes=private-secret'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={'width':1440, 'height':1000})
                page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base) else r.fulfill(status=200, body=''))
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                def visit(path):
                    page.goto(base+path, wait_until='domcontentloaded')
                    if path.startswith('/discovery'): page.wait_for_function('window.DISCOVERY_READY')
                visit('/discovery.html')
                assert page.locator('#intent-name').count() == 1, 'independent mentor name search is missing'
                page.fill('#intent-name', '张')
                page.click('#apply-criteria')
                page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                assert page.locator('[data-candidate]').count() == 2
                page.fill('#intent-name', ' 张一 ')
                page.click('#apply-criteria')
                page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                assert page.locator('[data-candidate]').count() == 1
                page.fill('#intent-topics', '视觉')
                page.click('#apply-criteria')
                page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                assert page.locator('[data-candidate]').count() == 0
                assert '交集' in page.locator('#candidate-list').inner_text()
                page.fill('#intent-name', 'alice')
                page.fill('#intent-topics', '')
                page.click('#apply-criteria')
                page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                assert page.locator('[data-candidate]').count() == 1
                visit('/discovery.html'+scope)
                page.click('[data-compare="test-0"]')
                assert page.locator('#compare-open').is_visible(), 'single selection must be accessible'
                page.click('#compare-open')
                assert page.locator('#card').is_visible()
                def query(selector): return parse_qs(urlparse(page.locator(selector).first.get_attribute('href')).query)
                def check_scope(q):
                    assert all(q.get(k)==[v] for k,v in {'school':'test','dept':'cs','year':'2027','degree':'master','route':'recommend','track':'special','program':'0854|test'}.items()), q
                    assert 'notes' not in q
                check_scope(query('.compare-contact'))
                check_scope(query('.context-actions a[href^="discovery"]'))
                page.click('.pcol .pn a')
                check_scope(query('.context-actions .primary'))
                check_scope(query('#detail-selection'))
                page.click('.context-actions .primary')
                check_scope(parse_qs(urlparse(page.url).query))
                visit('/discovery.html'+scope)
                page.locator('[data-candidate="test-0"] h2 a').click()
                check_scope(query('.context-actions .primary'))
                visit('/p/test-2.html'+scope)
                assert page.locator('#detail-scope-warning').is_visible()
                assert 'program' not in query('.context-actions .primary')
                visit('/compare.html?track=special&program=0854%7Ctest')
                assert 'program' not in query('.compare-contact')
                assert '不在原项目院系' in page.locator('.pcol').inner_text()
                visit('/compare.html'+scope)
                page.reload()
                assert page.locator('.pcol').count() == 1
                page.evaluate('localStorage.setItem("compare_sel", JSON.stringify(["test-0","test-2"]))')
                page.reload()
                q = parse_qs(urlparse(page.locator('.compare-contact').nth(1).get_attribute('href')).query)
                assert q['dept'] == ['other'] and q['year']==['2027']
                assert 'program' not in q and 'track' not in q, q
                assert '不在原项目院系' in page.locator('.pcol').nth(1).inner_text()
                page.locator('[data-rm="test-2"]').click()
                assert page.locator('.pcol').count() == 1 and page.locator('#card').is_visible()
                page.screenshot(path=str(out/'compare-desktop.png'), full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                page.screenshot(path=str(out/'compare-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('[data-rm="test-0"]').click()
                assert not page.locator('#card').is_visible()
                visit('/discovery.html'+scope)
                page.screenshot(path=str(out/'discovery-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.set_viewport_size({'width':1440,'height':1000})
                page.screenshot(path=str(out/'discovery-desktop.png'), full_page=True)
                offline = browser.new_page()
                offline.goto((site/'discovery.html').as_uri())
                offline.wait_for_function('window.DISCOVERY_READY')
                offline.fill('#intent-name','张一')
                offline.click('#apply-criteria')
                assert offline.locator('[data-candidate]').count()==1
                offline.click('[data-compare="test-0"]')
                offline.click('#compare-open')
                assert offline.locator('#card').is_visible()
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    print('discovery v0.9 UI: PASS')

if __name__ == '__main__':
    main()

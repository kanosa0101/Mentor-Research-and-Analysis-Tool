"""Read-only public guide/coverage acceptance, including missing-source fixtures."""
import copy
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import build_site, serve_public
from scripts.release_page_v1_ui_check import signatures


def start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f'http://127.0.0.1:{server.server_port}'


def main():
    output = ROOT / 'cache/public_guides_v15_ui'
    output.mkdir(parents=True, exist_ok=True)
    before, results = signatures(), []
    coverage = json.loads((ROOT / 'data/coverage.json').read_text(encoding='utf-8'))
    server = serve_public.create_server(ROOT, '127.0.0.1', 0)
    base = start(server)
    try:
        with tempfile.TemporaryDirectory(prefix='coverage-empty-source-') as tmp, sync_playwright() as pw:
            root = Path(tmp)
            site = root / 'site'
            site.mkdir()
            shutil.copyfile(ROOT / 'site/ui.css', site / 'ui.css')
            missing = copy.deepcopy(coverage)
            missing['units'] = missing['units'][:1]
            unit = missing['units'][0]
            unit['school_name'] = '验收学校（缺失链接测试）'
            unit['official_url'] = ''
            for name, key in [('policies', 'url'), ('programs', 'source_url'), ('contacts', 'source_url'), ('columns', 'url')]:
                for row in unit[name]:
                    row[key] = ''
            build_site.write_html(site / 'coverage.html', build_site.template_environment().get_template('coverage.html.j2').render(
                coverage=missing, safe_url=build_site.safe_url))
            fixture_server = serve_public.create_server(root, '127.0.0.1', 0)
            fixture_base = start(fixture_server)
            browser = pw.chromium.launch()
            try:
                for width in (1440, 390):
                    page = browser.new_page(viewport={'width': width, 'height': 900})
                    errors, writes = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD') else None)
                    page.route('**/*', lambda route: route.continue_() if any(route.request.url.startswith(host + '/') for host in (base, fixture_base)) else route.abort())
                    page.goto(base + '/coverage.html', wait_until='networkidle')
                    assert page.locator('.coverage-unit:visible').count() == len(coverage['units']) == 15
                    assert page.locator('.coverage-unit a[href="#"],.coverage-unit a[href=""]').count() == 0
                    assert all(urlsplit(href).scheme in ('http', 'https') for href in page.locator('.coverage-unit a[target="_blank"]').evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("href"))'))
                    for query, minimum in [('电子科大', 1), ('网安', 2), ('软件', 1), ('UESTC', 1)]:
                        page.locator('#coverage-search').fill(query)
                        assert page.locator('.coverage-unit:visible').count() >= minimum, query
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.locator('#coverage-search').fill('网安')
                    page.screenshot(path=str(output / f'coverage-search-{width}.png'))
                    page.locator('#coverage-search').fill('验收不存在的单位')
                    assert page.locator('.coverage-unit:visible').count() == 0
                    assert page.locator('#coverage-empty').is_visible()
                    page.screenshot(path=str(output / f'coverage-empty-{width}.png'))
                    page.goto(fixture_base + '/coverage.html', wait_until='networkidle')
                    assert page.locator('.coverage-links').get_by_text('院系官方入口尚未登记').is_visible()
                    assert page.locator('.coverage-unit a[target="_blank"]').count() == 0
                    page.locator('.coverage-unit details').evaluate_all('(nodes)=>nodes.forEach(n=>n.open=true)')
                    assert '原文入口待补齐' in page.locator('.coverage-unit').inner_text()
                    assert '咨询出处入口待补齐' in page.locator('.coverage-unit').inner_text()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'coverage-missing-links-{width}.png'))
                    page.goto(base + '/release.html', wait_until='networkidle')
                    text = page.locator('main').inner_text()
                    assert 'v1.5.0' in text and '69 / 111' in text and '42条' in text
                    assert '3条当期线索' in text and '0条已确认正在报名' in text
                    assert '181 / 2' in text and '山东完整校章及' not in text
                    assert page.locator('a[href="start.html#public-data-panel"]').count() == 1
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'release-{width}.png'))
                    for query, path in [('', '/start.html'), ('?id=iscas-research-2026', '/opportunities.html')]:
                        page.goto(base + '/local.html' + query, wait_until='networkidle')
                        link = urlsplit(page.locator('#open-local').get_attribute('href'))
                        assert link.hostname == '127.0.0.1' and link.port == 8000 and link.path == path
                        assert parse_qs(link.query) == ({'id': ['iscas-research-2026']} if query else {})
                        assert page.locator('a[href="start.html#library"]').is_visible()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'local-{width}.png'))
                    assert not errors and not writes, (errors, writes)
                    results.append(dict(width=width, passed=True, alias_search=True, missing_url_placeholder=True,
                                        release_snapshot_verified=True, local_target_preserved=True,
                                        page_errors=errors, write_requests=writes))
                    page.close()
            finally:
                browser.close()
                fixture_server.shutdown()
                fixture_server.server_close()
    finally:
        server.shutdown()
        server.server_close()
    assert signatures() == before
    result = dict(passed=True, private_files_unchanged=True, cases=results)
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Use the live catalog once, and load the public snapshot only after API failure."""
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from scripts import build_site


@pytest.mark.parametrize('fail_api,fail_snapshot', [(False, False), (True, False), (True, True)])
def test_live_catalog_and_fallback(fail_api, fail_snapshot):
    root = build_site.ROOT
    html = build_site.template_environment().get_template('opportunities.html.j2').render()
    raw = (root/'site/opportunities-data.js').read_text(encoding='utf8')
    catalog = json.loads(raw.split('=', 1)[1].strip().removesuffix(';'))
    requests, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-proxy-server'])
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def handle(route):
            path = urlsplit(route.request.url).path
            requests.append(path)
            assert route.request.method == 'GET'
            if path == '/opportunities.html':
                return route.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/opportunities':
                return route.fulfill(status=503 if fail_api else 200, content_type='application/json',
                                     body=json.dumps(dict(catalog, mode='public')))
            if path.startswith('/api/'):
                value = {'authenticated': False, 'user': None} if path == '/api/auth/me' else {'enabled': False, 'events': []}
                return route.fulfill(content_type='application/json', body=json.dumps(value))
            if path == '/opportunities-data.js' and fail_snapshot:
                return route.fulfill(status=503, body='unavailable')
            target = root/'site'/path.lstrip('/')
            assert target.resolve().is_relative_to(root/'site') and target.is_file()
            return route.fulfill(content_type='text/css' if target.suffix == '.css' else 'text/javascript', body=target.read_bytes())

        page.route('**/*', handle)
        try:
            page.goto('http://mentor-test.invalid/opportunities.html')
            page.wait_for_function('!document.getElementById("monitor-refresh").disabled')
            assert errors == []
            assert ('/opportunities-data.js' in requests) == fail_api
            assert requests.count('/api/opportunities') == 1
            if not fail_api:
                assert page.evaluate('opportunityModeReady && catalogLoaded')
            elif not fail_snapshot:
                assert page.evaluate('catalogLoaded && !opportunityModeReady')
                assert page.evaluate('opportunityRows.every(row=>row.source_state==="unavailable")')
                assert '静态快照' in page.locator('#monitor-health').text_content(), (errors, page.locator('#opportunity-count').text_content())
            else:
                assert '暂时无法读取' in page.locator('#opportunity-count').inner_text()
                assert not page.evaluate('opportunityModeReady')
            assert errors == []
        finally:
            browser.close()

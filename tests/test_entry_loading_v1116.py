"""First public views work with only HTML and their live APIs, without extra assets."""
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from scripts import build_site


@pytest.mark.parametrize('name,renderer,ready', [
    ('start', build_site.render_start_page, 'window.START_READY'),
    ('discovery', build_site.render_discovery_page, 'window.DISCOVERY_READY'),
])
def test_first_view_has_no_dependent_asset_roundtrips(name, renderer, ready):
    html = renderer()
    requests, errors, writes = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-proxy-server'])
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route_request(route):
            request = route.request
            path = urlsplit(request.url).path
            requests.append(path)
            if request.method != 'GET':
                writes.append(path)
                return route.abort()
            if path == '/' + name + '.html':
                return route.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/auth/me':
                value = {'authenticated': False, 'user': None}
            elif path == '/api/mentor-candidates':
                value = {'version': 2, 'rows': [], 'total': 0, 'revision': 'fixture'}
            else:
                return route.abort()
            route.fulfill(content_type='application/json', body=json.dumps(value))

        page.route('**/*', route_request)
        try:
            page.goto('http://mentor-test.invalid/' + name + '.html')
            page.wait_for_function(ready)
            assert page.locator('.site-header nav a[href="applications.html"]').is_visible()
            if name == 'start':
                page.locator('#target-interest').fill('机器学习')
                page.locator('#target-interest').blur()
                assert 'topics=' in page.locator('#target-entries a[href^="discovery.html"]').first.get_attribute('href')
            else:
                assert '0' in page.locator('#discovery-count').inner_text()
            assert all(path == '/' + name + '.html' or path.startswith('/api/') for path in requests)
            assert errors == [] and writes == []
        finally:
            browser.close()

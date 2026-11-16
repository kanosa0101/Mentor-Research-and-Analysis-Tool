"""Real Chromium recovery after a failed public script; no account mutations."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'http://mentor-test.invalid'


@pytest.mark.parametrize('failed_asset', [None, 'browser-library-core.js', 'cloud-library.js'])
def test_start_dependency_failure_has_reload_and_recovers(failed_asset):
    environment = Environment(loader=FileSystemLoader(ROOT/'site/templates'),
                              autoescape=select_autoescape())
    html = environment.get_template('start.html.j2').render()
    assert 'start.js?v=20261116-loadguard1' in html
    errors, writes, blocked, requests = [], [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=['--no-proxy-server'])
        context = browser.new_context()
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route_request(route):
            request = route.request
            requests.append(request.url)
            if request.method not in ('GET', 'HEAD'):
                writes.append(request.url)
                route.abort()
                return
            assert request.url.startswith(ORIGIN + '/')
            path = urlsplit(request.url).path
            if failed_asset and path == '/' + failed_asset and not blocked:
                blocked.append(path)
                route.abort('failed')
            elif path == '/api/auth/me':
                route.fulfill(status=200, content_type='application/json',
                              body=json.dumps({'authenticated': False, 'user': None}))
            elif path == '/start.html':
                route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
            else:
                target = ROOT/'site'/path.lstrip('/')
                assert target.resolve().is_relative_to(ROOT/'site') and target.is_file()
                content_type = 'text/javascript' if target.suffix == '.js' else 'text/css'
                route.fulfill(status=200, content_type=content_type+'; charset=utf-8', body=target.read_bytes())

        context.route('**/*', route_request)
        try:
            page.goto(ORIGIN+'/start.html', wait_until='networkidle')
            if failed_asset:
                assert blocked == ['/' + failed_asset]
                assert '页面资源加载失败' in page.locator('#target-status').inner_text()
                assert page.locator('#target-form').evaluate('(form)=>[...form.elements].every(field=>field.disabled)')
                assert page.locator('.site-header nav a[href="discovery.html"]').is_visible()
                assert not page.evaluate('Boolean(window.START_READY)')
                assert errors == []
                page.locator('#target-status').get_by_role('button', name='重新加载').click()
            page.wait_for_function('window.START_READY === true')
            assert page.locator('#target-form').evaluate('(form)=>[...form.elements].every(field=>!field.disabled)')
            assert page.locator('#target-status').get_by_role('button', name='重新加载').count() == 0
            assert page.locator('#start-school-options input').count() > 0
            assert page.locator('#target-year').input_value().isdigit()
            page.locator('#target-interest').fill('机器学习')
            page.locator('#target-interest').blur()
            assert 'topics=' in page.locator('#target-entries a[href^="discovery.html"]').first.get_attribute('href')
            assert errors == [] and writes == []
            if failed_asset:
                assert sum(urlsplit(url).path == '/' + failed_asset for url in requests) == 2
        finally:
            browser.close()

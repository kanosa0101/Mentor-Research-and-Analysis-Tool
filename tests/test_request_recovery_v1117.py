"""Real browser recovery from stalled reads without downloading the full directory."""
import json
from urllib.parse import urlsplit, parse_qs

import pytest
from playwright.sync_api import sync_playwright, expect

from scripts import build_site


@pytest.mark.parametrize('width', [1280, 390])
@pytest.mark.parametrize('stall_after_success', [False, True])
def test_directory_stall_releases_controls_keeps_results_and_retries(stall_after_success, width):
    row = dict(page='bit-cs-test', name='测试导师', school='bit', dept='cs',
               school_name='北京理工大学', dept_name='计算机学院', title='教授',
               supervisor='博导', research_direction_raw='计算机视觉',
               email='teacher@bit.edu.cn', email_source='https://cs.bit.edu.cn/teacher')
    html = build_site.render_discovery_page()
    calls, downloads, errors = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 844})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request):
            path = urlsplit(request.request.url).path
            assert request.request.method == 'GET'
            if path == '/discovery.html':
                return request.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/auth/me':
                return request.fulfill(content_type='application/json', body='{"authenticated":false}')
            if path == '/api/mentor-candidates':
                calls.append(parse_qs(urlsplit(request.request.url).query))
                if len(calls) == (2 if stall_after_success else 1):
                    return
                return request.fulfill(content_type='application/json', body=json.dumps(
                    dict(version=2, rows=[dict(p=row)], total=1, missing_email=0, revision='test')))
            downloads.append(path)
            request.abort()

        page.route('**/*', route)
        try:
            page.goto('http://mentor-test.invalid/discovery.html', wait_until='domcontentloaded')
            if stall_after_success:
                expect(page.locator('[data-candidate]')).to_have_count(1)
                if not page.locator('#criteria-form').is_visible():
                    page.locator('#criteria-panel > summary').click()
                page.locator('#intent-name').fill('测试')
                page.locator('#apply-criteria').click()
            expect(page.locator('#discovery-message')).to_contain_text('超时', timeout=11000)
            expect(page.locator('#apply-criteria')).to_be_visible()
            expect(page.locator('#apply-criteria')).to_be_enabled()
            expect(page.locator('[data-candidate]')).to_have_count(1 if stall_after_success else 0)
            assert not downloads  # Timeout must not fetch a multi-megabyte fallback.
            page.locator('#apply-criteria').click()
            expect(page.locator('[data-candidate]')).to_have_count(1)
            expect(page.locator('#apply-criteria')).to_be_enabled()
            assert len(calls) == (3 if stall_after_success else 2)
            assert not errors
        finally:
            browser.close()


def test_account_stall_can_be_refreshed_after_timeout():
    script = (build_site.ROOT / 'site/account-session.js').read_text(encoding='utf-8')
    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        def route(request):
            if urlsplit(request.request.url).path == '/api/auth/me':
                calls.append(1)
                if len(calls) == 1:
                    return
                return request.fulfill(content_type='application/json', body='{"authenticated":false}')
            request.fulfill(content_type='text/html', body='<script>'+script+'</script>')

        page.route('**/*', route)
        try:
            page.goto('http://mentor-test.invalid/account.html', wait_until='domcontentloaded')
            assert page.evaluate('OnlineAccount.currentRead.then(()=>false,error=>error.timedOut)') is True
            page.locator('#account-connection-message button').click()
            assert page.evaluate('OnlineAccount.ready.then(state=>state.authenticated)') is False
            expect(page.locator('#account-connection-message')).to_have_count(0)
            assert len(calls) == 2
        finally:
            browser.close()


def test_activity_entry_needs_no_external_scripts_and_keeps_public_api():
    html = build_site.render_opportunities_page()
    paths, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request):
            path = urlsplit(request.request.url).path
            paths.append(path)
            assert request.request.method == 'GET'
            if path == '/opportunities.html':
                return request.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path.startswith('/api/'):
                data = {'authenticated': False} if path == '/api/auth/me' else (
                    {'mode': 'public', 'opportunities': [], 'other_contents': []}
                    if path == '/api/opportunities' else {'enabled': False, 'events': []})
                return request.fulfill(content_type='application/json', body=json.dumps(data))
            request.abort()

        page.route('**/*', route)
        try:
            page.goto('http://mentor-test.invalid/opportunities.html', wait_until='domcontentloaded')
            page.wait_for_function('opportunityModeReady')
            expect(page.locator('.opportunity-empty')).to_be_visible()
            assert not [path for path in paths if path.endswith(('.js', '.css'))]
            assert '/api/opportunities' in paths and not errors
        finally:
            browser.close()


def test_activity_saved_records_stall_does_not_lock_public_refresh():
    html = build_site.render_opportunities_page()
    calls = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        def route(request):
            path = urlsplit(request.request.url).path
            assert request.request.method == 'GET'
            if path == '/opportunities.html':
                return request.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/workflow':
                calls.append(1)
                if len(calls) == 1:
                    return
                data = {'projects': {}}
            elif path == '/api/opportunities':
                data = {'mode': 'account', 'opportunities': [], 'other_contents': []}
            elif path == '/api/auth/me':
                data = {'authenticated': True, 'user': {'id': 'test'}}
            else:
                data = {'enabled': False, 'events': []}
            request.fulfill(content_type='application/json', body=json.dumps(data))

        page.route('**/*', route)
        try:
            page.goto('http://mentor-test.invalid/opportunities.html', wait_until='domcontentloaded')
            expect(page.locator('.opportunity-empty')).to_be_visible()
            expect(page.locator('#opportunity-result')).to_contain_text('账号申请记录暂不可读取', timeout=11000)
            expect(page.locator('#monitor-refresh')).to_be_enabled()
            page.evaluate('refreshOpportunityMonitor()')
            expect(page.locator('#opportunity-result')).to_have_text('')
            expect(page.locator('#monitor-refresh')).to_be_enabled()
            assert len(calls) == 2
        finally:
            browser.close()

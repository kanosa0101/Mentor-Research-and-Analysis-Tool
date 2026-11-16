"""The admissions first view preserves all policy evidence without dependent assets."""
import hashlib
import json
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scripts import build_site


def open_anonymously(html, verify):
    paths, errors, writes = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-proxy-server'])
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route_request(route):
            request = route.request
            path = urlsplit(request.url).path
            paths.append(path)
            if request.method != 'GET':
                writes.append(path)
                return route.abort()
            if path == '/admissions.html':
                return route.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/auth/me':
                return route.fulfill(content_type='application/json', body=json.dumps(dict(authenticated=False, user=None)))
            return route.abort()

        page.route('**/*', route_request)
        try:
            page.goto('http://mentor-test.invalid/admissions.html')
            page.wait_for_function('window.ADMISSIONS_READY')
            page.evaluate('window.OnlineAccount.ready')
            assert page.locator('.site-header nav a[href^="applications.html"]').is_visible()
            assert page.locator('#policy-school').is_visible()
            assert page.locator('#policy-welcome').is_visible()
            verify(page)
            assert set(paths) == {'/admissions.html', '/api/auth/me'}
            assert errors == writes == []
        finally:
            browser.close()


def test_real_complete_payload_executes_in_dependency_order_without_asset_requests():
    source = (build_site.SITE / 'admissions-data.js').read_text(encoding='utf8')
    expected = json.loads(source.split('=', 1)[1].strip().removesuffix(';'))
    html = build_site.render_admissions_page()
    assert not BeautifulSoup(html, 'html.parser').select('script[src], link[rel="stylesheet"]')

    def verify(page):
        assert page.evaluate('window.ADMISSIONS_DATA') == expected
        assert page.evaluate('typeof AdmissionsRules.select') == 'function'
        assert page.evaluate('typeof MaterialPreparation.publicActions') == 'function'
        school = expected['schools'][0]['id']
        page.locator('#policy-school').select_option(school)
        assert page.locator('#policy-school').input_value() == school
        assert page.locator('#unit-summary').is_visible()

    open_anonymously(html, verify)


def test_new_output_directory_uses_fresh_data_escapes_script_and_preserves_live_site(tmp_path, monkeypatch):
    live = [build_site.ROOT / 'site' / name for name in ('admissions.html', 'admissions-data.js')]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in live}
    payload = dict(version=1, schools=[dict(id='stage-only', name='</ScRiPt><script>window.injected=true</SCRIPT>')],
                   units=[], groups=[], policies=[], sources={}, checks={}, entries=[])
    (tmp_path / 'admissions-data.js').write_text('window.ADMISSIONS_DATA=' + json.dumps(payload) + ';', encoding='utf8')
    monkeypatch.setattr(build_site, 'SITE', tmp_path)
    html = build_site.render_admissions_page()
    build_site.write_html(tmp_path / 'admissions.html', html)
    soup = BeautifulSoup(html, 'html.parser')
    assert len(soup.select('script')) == 2
    assert not soup.select('script[src], link[rel="stylesheet"]')
    assert (build_site.ROOT / 'site/ui.css').read_text(encoding='utf8') in html

    def verify(page):
        assert page.evaluate('window.ADMISSIONS_DATA') == payload
        assert page.evaluate('typeof window.injected') == 'undefined'
        assert page.locator('#policy-school option[value="stage-only"]').inner_text() == payload['schools'][0]['name']

    open_anonymously((tmp_path / 'admissions.html').read_text(encoding='utf8'), verify)
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in live}


def test_raw_template_retains_preview_dependency_order():
    html = build_site.template_environment().get_template('admissions.html.j2').render()
    scripts = [node['src'].split('?')[0] for node in BeautifulSoup(html, 'html.parser').select('script[src]')]
    assert scripts == ['account-session.js', 'cloud-library.js', 'admissions-data.js',
                       'admissions-core.js', 'material-actions.js', 'admissions.js']

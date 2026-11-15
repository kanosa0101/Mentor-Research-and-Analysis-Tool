"""Real local save API and HTTP/HTTPS push UI; no production private writes or push."""
import copy
import ipaddress
import json
import shutil
import ssl
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import opportunity_util
from scripts import serve, serve_public
from scripts.opportunities_v1_2_ui_check import ACTIVITY, no_overflow, render, start
from scripts.release_page_v1_ui_check import signatures


def files(root, catalog):
    site = render(root, catalog)
    for name in ('opportunity-push.js', 'opportunity-sw.js'):
        shutil.copyfile(ROOT / 'site' / name, site / name)
    return site


def tls(server, root):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
            .sign(key, hashes.SHA256()))
    (root / 'test-key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (root / 'test-cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(root / 'test-cert.pem', root / 'test-key.pem')
    server.socket = context.wrap_socket(server.socket, server_side=True)


def main():
    out = ROOT / 'cache/opportunities_v13_ui'
    out.mkdir(parents=True, exist_ok=True)
    before, results = signatures(), []
    catalog = opportunity_util.load(ROOT)
    expected = next(item for item in catalog['opportunities'] if item['id'] == ACTIVITY)
    directions = expected['research_directions']
    assert len(directions) == 29
    with patch.object(opportunity_util, 'observed', side_effect=lambda root: copy.deepcopy(catalog)):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=['--ignore-certificate-errors'])
            for mode in ('local', 'http', 'https'):
                for width in (1440, 390):
                    with tempfile.TemporaryDirectory(prefix='opportunities-v13-') as tmp:
                        root = Path(tmp)
                        site = files(root, catalog)
                        private = root / 'private'
                        server = (serve.create_server(site=site, outreach=private / 'outreach.yaml', port=0)
                                  if mode == 'local' else serve_public.create_server(root, '127.0.0.1', 0))
                        if mode == 'https':
                            tls(server, root)
                        base = start(server).replace('http:', 'https:' if mode == 'https' else 'http:')
                        if mode != 'local':
                            folder = root / 'var/push'
                            folder.mkdir(parents=True)
                            (folder / 'config.json').write_text(json.dumps(dict(
                                origin=base if mode == 'https' else 'https://notifications.example.test',
                                public_key='test-key-never-used')), encoding='utf-8')
                        errors, writes = [], []
                        context = browser.new_context(viewport={'width': width, 'height': 900}, ignore_https_errors=True)
                        context.add_init_script("""window.permissionRequests=0;
                          if(window.Notification)Notification.requestPermission=async()=>{window.permissionRequests++;return 'denied';};""")
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('request', lambda req: writes.append(req.url) if req.method not in ('GET', 'HEAD') else None)
                        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                        try:
                            page.goto(base + '/opportunities.html?id=' + ACTIVITY, wait_until='networkidle')
                            card = page.locator('[data-opportunity="' + ACTIVITY + '"]')
                            summary = card.locator('summary').filter(has_text='研究方向与联系')
                            summary.click()
                            assert card.locator('.research-direction').count() == 29
                            for index, row in enumerate(directions):
                                rendered = card.locator('.research-direction').nth(index)
                                assert row['direction'] in rendered.inner_text()
                                assert row['department'] in rendered.inner_text()
                                assert row['source_locator'] in rendered.inner_text()
                                if row['email']:
                                    href = rendered.locator('a[href^="mailto:"]').get_attribute('href')
                                    from urllib.parse import unquote
                                    assert unquote(href.split('?')[0]) == 'mailto:' + row['email']
                            # Test every official direction string and department, not a synthetic fixture.
                            for query in [row['direction'] for row in directions] + list({row['department'] for row in directions}):
                                page.locator('#opportunity-search').fill(query)
                                assert card.is_visible(), query
                                assert card.locator('details[open] .research-direction').count() >= 1, query
                            page.locator('#opportunity-search').fill('')
                            card.locator('summary').filter(has_text='研究方向与联系').click()
                            page.locator('#push-panel > summary').click()
                            page.wait_for_function("!document.querySelector('#push-status').textContent.includes('正在读取')")
                            status = page.locator('#push-status').inner_text()
                            assert page.evaluate('window.permissionRequests') == 0
                            if mode == 'https':
                                page.wait_for_function("!document.querySelector('#push-subscribe').disabled")
                                assert '点击后由浏览器询问通知权限' in status
                                page.locator('#push-subscribe').click()
                                page.wait_for_function("document.querySelector('#push-status').textContent.includes('通知权限未允许')")
                                assert page.evaluate('window.permissionRequests') == 1
                                assert not writes
                            elif mode == 'http':
                                assert page.locator('#push-subscribe').is_disabled()
                                assert page.locator('#push-status a').get_attribute('href').startswith('https://')
                                assert not writes
                            if mode == 'local':
                                page.locator('[data-save-opportunity="' + ACTIVITY + '"]').click()
                                page.locator('#opportunity-name').fill('V1.3 方向与联系快照验收')
                                page.locator('#opportunity-confirm').click()
                                page.wait_for_function("!document.querySelector('#opportunity-save').open")
                                data = page.request.get(base + '/api/workflow').json()
                                assert len(data['projects']) == 1
                                project = next(iter(data['projects'].values()))
                                assert project['opportunity']['research_directions'] == directions
                                assert (private / 'workflow.yaml').exists()
                            no_overflow(page)
                            page.screenshot(path=str(out / f'{mode}-{width}.png'), full_page=True)
                            assert not errors, errors
                            results.append(dict(mode=mode, width=width, directions=29, departments=8,
                                                snapshot_saved=mode == 'local', automatic_permission_requests=0,
                                                writes=writes, page_errors=errors, passed=True))
                        finally:
                            context.close()
                            server.shutdown()
                            server.server_close()
            browser.close()
    assert signatures() == before, 'production private files changed'
    (out / 'results.json').write_text(json.dumps(dict(passed=True, private_files_unchanged=True,
        cases=results), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=True, cases=len(results), evidence=str(out)), ensure_ascii=False))


if __name__ == '__main__':
    main()

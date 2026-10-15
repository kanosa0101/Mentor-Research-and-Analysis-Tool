"""Read-only release-page navigation smoke test; private files stay untouched."""
import argparse
import hashlib
import json
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server


def signatures():
    paths = [ROOT / 'data' / name for name in ['outreach.yaml', 'student.yaml', 'student_sop.md',
             'workflow.yaml', 'workflow.json', 'discovery.yaml', 'backup.json']]
    for name in ['letters', 'backups']:
        paths.extend(p for p in (ROOT / 'data' / name).rglob('*') if p.is_file())
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in paths}


def check(base, out):
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            page = browser.new_page(viewport={'width': width, 'height': 1000 if width == 1440 else 844})
            errors, writes, external = [], [], []
            page.on('pageerror', lambda e: errors.append(str(e)))

            def route(request):
                if not request.request.url.startswith(base + '/'):
                    external.append(request.request.url)
                    request.fulfill(status=200, body='')
                elif request.request.method not in ['GET', 'HEAD']:
                    writes.append(dict(method=request.request.method, url=request.request.url))
                    request.abort()
                else:
                    request.continue_()

            page.route('**/*', route)
            page.goto(base + '/discovery.html', wait_until='networkidle')
            page.wait_for_function('window.DISCOVERY_READY')
            page.locator('.site-tools > summary').click()
            release = page.locator('.site-tools-menu a[href="release.html"]')
            assert release.is_visible()
            release.click()
            page.wait_for_url('**/release.html')
            page.wait_for_load_state('networkidle')
            assert page.locator('h1').inner_text() == '导师库 · 申请助手 v1.0.0'
            expected = ['39 / 59 / 56', '7173', '111 / 183 / 96', '310', '180 / 3']
            assert page.locator('main table td').all_text_contents() == expected
            for cell in page.locator('main table td').all():
                assert cell.is_visible()
            nav = page.locator('nav[aria-label="主导航"] a')
            assert nav.count() == 4
            assert nav.evaluate_all('(nodes)=>nodes.map(n=>n.getAttribute("href"))') == ['discovery.html', 'admissions.html', 'notices.html', 'desk.html']
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(out / f'release-{width}.png'), full_page=True)
            visited = []
            for target, ready in [('discovery.html', 'window.DISCOVERY_READY'),
                                  ('applications.html', 'window.WORKFLOW_READY'),
                                  ('desk.html', 'window.CONTACT_READY')]:
                page.locator('.release-links a[href="' + target + '"]').click()
                page.wait_for_url('**/' + target)
                page.wait_for_function(ready)
                visited.append(target)
                page.goto(base + '/release.html', wait_until='networkidle')
            assert not errors, errors
            assert not writes, writes
            results.append(dict(width=width, version='1.0.0', visible_counts=expected,
                                main_nav_count=nav.count(), visited=visited,
                                no_horizontal_overflow=True, page_errors=errors,
                                non_read_requests=writes, blocked_external=external))
            page.close()
        browser.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', help='Read-only live-service URL; default uses isolated private storage')
    parser.add_argument('--out', type=Path, default=ROOT / 'cache/release_v1/validation/release-page')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    before = signatures()
    with tempfile.TemporaryDirectory() as tmp:
        server = None
        try:
            if args.base:
                base = args.base.rstrip('/')
            else:
                server = create_server(outreach=Path(tmp) / 'private/outreach.yaml', port=0)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                base = f'http://127.0.0.1:{server.server_port}'
            results = check(base, args.out)
            assert signatures() == before, 'Real private files changed'
            assert not list((Path(tmp) / 'private').glob('*'))
        finally:
            if server:
                server.shutdown()
                server.server_close()
    (args.out / 'results.json').write_text(json.dumps(dict(passed=True, base=base,
        live_service=bool(args.base), private_signatures_unchanged=True, results=results),
        ensure_ascii=False, indent=2), encoding='utf8')
    print('PASS release-page 1440/390: tools navigation, counts, four main links, return flows, no writes/errors/overflow; private unchanged')


if __name__ == '__main__':
    main()

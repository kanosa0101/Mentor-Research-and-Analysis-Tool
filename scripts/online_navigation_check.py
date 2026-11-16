"""Measure public HTTPS navigation with a disposable, identifiable QA account."""
import argparse
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    if not base.startswith('https://'):
        raise ValueError('Use the public HTTPS endpoint')
    args.output.mkdir(parents=True, exist_ok=True)
    username = 'qa_v1112_' + str(int(time.time())) + '_perf'
    password = secrets.token_urlsafe(24)
    result = {'base_url': base, 'planned_usernames': [username], 'accounts': [],
              'measurements': [], 'browser_errors': [], 'failed_requests': [], 'passed': False}

    def save():
        (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    save()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=['--no-proxy-server'])
            context = browser.new_context(viewport={'width': 1440, 'height': 980})
            page = context.new_page()
            page.on('pageerror', lambda error: result['browser_errors'].append(str(error)))
            page.on('requestfailed', lambda request: result['failed_requests'].append({'url': request.url, 'error': request.failure}))
            page.goto(base + '/account.html?next=/applications.html', wait_until='networkidle')
            page.locator('[data-account-mode=register]').click()
            page.locator('#account-username').fill(username)
            page.locator('#account-password').fill(password)
            page.locator('#account-confirm').fill(password)
            page.locator('#account-submit').click()
            page.wait_for_url(lambda url: urlsplit(url).path == '/applications.html')
            state = context.request.get(base + '/api/auth/me').json()
            assert state['authenticated']
            result['accounts'].append(state['user'])
            save()
            page.wait_for_function('window.WORKFLOW_READY')
            cdp = context.new_cdp_session(page)
            for round_index in range(3):
                for name, ready in [('applications', 'window.WORKFLOW_READY'),
                                    ('desk', 'window.CONTACT_READY'),
                                    ('discovery', 'window.DISCOVERY_READY'),
                                    ('start', 'window.START_READY')]:
                    if round_index == 0:
                        cdp.send('Network.clearBrowserCache')
                    started = time.monotonic()
                    page.goto(base + '/' + name + '.html', wait_until='domcontentloaded', timeout=90000)
                    page.wait_for_function(ready, timeout=30000)
                    ready_ms = round((time.monotonic() - started) * 1000)
                    page.wait_for_load_state('networkidle')
                    resources = page.evaluate('performance.getEntriesByType("resource").map(r=>({name:r.name.split("/").pop(),transfer_bytes:r.transferSize,decoded_bytes:r.decodedBodySize,duration_ms:Math.round(r.duration)}))')
                    row = {'page': name, 'round': round_index, 'cache': 'cold' if round_index == 0 else 'warm',
                           'ready_ms': ready_ms, 'resources': resources,
                           'transfer_bytes': sum(r['transfer_bytes'] for r in resources),
                           'decoded_bytes': sum(r['decoded_bytes'] for r in resources)}
                    result['measurements'].append(row)
                    if round_index == 0:
                        page.screenshot(path=str(args.output / (name + '-desktop.png')), full_page=True)
                    save()
                    print(name, round_index, ready_ms, row['transfer_bytes'], flush=True)
            assert not result['browser_errors'], result['browser_errors']
            assert not result['failed_requests'], result['failed_requests']
            result['passed'] = True
            browser.close()
    finally:
        save()


if __name__ == '__main__':
    main()

"""Deployed HTTPS read-only acceptance; normal browser certificate verification."""
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = 'https://8.213.137.82:8443'
KEY = 'mentor-browser-library-v1'


def main():
    output = ROOT / 'cache/v15/public-ui'
    output.mkdir(parents=True, exist_ok=True)
    cases, security = [], None
    with sync_playwright() as pw:
        # No certificate-error bypass flags and no ignore_https_errors option.
        browser = pw.chromium.launch()
        try:
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 900})
                context.add_init_script("window.permissionRequests=0;if(window.Notification)Notification.requestPermission=async()=>{window.permissionRequests++;return 'denied';};")
                page = context.new_page()
                errors, writes, external, requests = [], [], [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def route(request):
                    req = request.request
                    requests.append(req.url)
                    if req.method not in ('GET', 'HEAD'):
                        writes.append(dict(method=req.method, url=req.url))
                        return request.abort()
                    if not req.url.startswith(BASE + '/'):
                        external.append(req.url)
                        return request.abort()
                    request.continue_()
                page.route('**/*', route)
                def goto(path):
                    response = page.goto(BASE + '/' + path, wait_until='networkidle', timeout=45000)
                    assert response.status == 200, (path, response.status)
                    return response
                response = goto('start.html')
                security = response.security_details()
                assert security and security.get('protocol'), 'Expected a verified TLS response'
                page.wait_for_function('window.START_READY')
                assert '2027' in page.locator('#exam-path-title').inner_text()
                assert '2028' in page.locator('#recommend-path-title').inner_text()
                assert page.locator('[name=path][value=recommend]').is_checked()
                assert page.locator('#target-year').input_value() == '2028'
                assert page.locator('.site-header nav a').count() == 5
                assert page.evaluate('(key)=>localStorage.getItem(key)', KEY) is None
                page.screenshot(path=str(output / f'start-{width}.png'))
                page.locator('.school-directory > summary').click()
                for code in ('pku', 'tsinghua'):
                    page.locator('#start-school-search').fill(code)
                    page.locator('#start-school-options input[value="' + code + '"]').check()
                assert page.locator('#target-school-chips button').count() == 2
                assert page.locator('#target-entries .entry-school').count() == 2
                page.locator('[name=path][value=exam]').check()
                assert page.locator('#target-year').input_value() == '2027'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert '公开站已使用服务器发布的资料' in page.locator('#public-data-status').inner_text()
                assert page.locator('#public-data-check').is_hidden()
                page.locator('.school-directory').scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'school-multiselect-{width}.png'))
                goto('coverage.html')
                assert page.locator('.coverage-unit').count() == 15
                counts = {}
                for query in ('电子科大', '网安', '软件'):
                    page.locator('#coverage-search').fill(query)
                    counts[query] = page.locator('.coverage-unit:visible').count()
                    assert counts[query] > 0, query
                page.locator('#coverage-search').fill('电子科大')
                card = page.locator('.coverage-unit:visible').first
                text = card.inner_text()
                assert '统计于 2026-11-15' in text
                assert '记录核对日期范围' in text and '来源抓取日期' in text
                assert 'last_verified' not in text and 'last_reviewed_at' not in text
                assert '并非全部记录都在最近日期复核' in text
                assert page.locator('.coverage-unit a[href="#"],.coverage-unit a[href=""]').count() == 0
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'coverage-{width}.png'))
                card.screenshot(path=str(output / f'coverage-dates-{width}.png'))
                goto('release.html')
                text = page.locator('main').inner_text()
                assert 'v1.5.0' in text and '69 / 111' in text and '42条' in text
                assert '181 / 2' in text and '3条当期线索' in text and '0条已确认正在报名' in text
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'release-{width}.png'))
                goto('opportunities.html?school=%E9%AA%8C%E6%94%B6%E6%9C%AA%E8%A6%86%E7%9B%96%E5%AD%A6%E6%A0%A1')
                assert page.locator('#opportunity-school').input_value() == '验收未覆盖学校'
                assert page.locator('[data-opportunity]').count() == 0
                assert page.locator('.opportunity-empty').is_visible()
                assert page.evaluate('window.permissionRequests') == 0
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / f'empty-school-{width}.png'))
                goto('p/pku-cs-zhangshanghang.html')
                page.locator('details').filter(has=page.locator('#ob-save')).evaluate_all('(nodes)=>nodes.forEach(n=>n.open=true)')
                page.wait_for_function("getComputedStyle(document.querySelector('#ob-hint')).display!=='none'")
                controls = ('ob-status', 'ob-notes', 'ob-save', 'ob-next', 'ob-due', 'ob-tags')
                assert all(page.locator('#' + key).is_disabled() for key in controls)
                assert not any('/api/outreach' in url for url in requests)
                assert page.evaluate('(key)=>localStorage.getItem(key)', KEY) is None
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#ob-hint').scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'profile-readonly-{width}.png'))
                assert not errors and not writes, (errors, writes)
                cases.append(dict(width=width, passed=True, tls_default_verification=True,
                    default_paths=True, school_multiselect=True, coverage_alias_counts=counts,
                    coverage_dates_clear=True, release='1.5.0', absent_school_stays_empty=True,
                    public_profile_private_controls_disabled=True, local_library_unwritten=True,
                    notification_permission_requests=0, blocked_write_requests=writes,
                    page_errors=errors, blocked_external_requests=external))
                context.close()
        finally:
            browser.close()
    result = dict(passed=True, origin=BASE, tested_at=datetime.now(timezone.utc).isoformat(),
                  tls_security_details=security, certificate_errors_ignored=False, cases=cases)
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

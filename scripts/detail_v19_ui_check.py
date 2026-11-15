"""Verify the detail hierarchy and application context without private writes."""
import json
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler import store
from scripts import build_site
from scripts.serve import create_server


def main():
    output = ROOT / 'cache/v19/detail'
    output.mkdir(parents=True, exist_ok=True)
    records = json.loads((ROOT / 'site/data.js').read_text(encoding='utf8').split('=', 1)[1].strip().removesuffix(';'))
    mentor = next(p for p in records if p['page'] == 'bit-cs-daiqiangqiang')
    mentor = {**store._yaml_load(ROOT / 'data/professors/bit/cs/daiqiangqiang.yaml'), **mentor}
    html = build_site.template_environment().get_template('detail.html.j2').render(p=mentor)
    path = '/p/' + mentor['page'] + '.html'
    scope = {'school': 'bit', 'dept': 'cs', 'year': '2027', 'degree': 'master', 'route': 'exam', 'track': 'ordinary', 'program': '0812'}
    result = {'cases': [], 'private_mutations': False}
    with tempfile.TemporaryDirectory(prefix='mentor-detail-ui-') as temp:
        server = create_server(outreach=Path(temp)/'outreach.yaml', workflow=Path(temp)/'workflow.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for width in (1440, 390):
                    context = browser.new_context(viewport={'width': width, 'height': 950})
                    page = context.new_page()
                    writes, errors = [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))

                    def readonly(route):
                        request = route.request
                        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                            writes.append(request.url)
                            route.abort()
                        elif urlsplit(request.url).path == path:
                            route.fulfill(status=200, body=html, content_type='text/html')
                        elif request.url.startswith(base):
                            route.continue_()
                        else:
                            route.fulfill(status=200, body='')

                    page.route('**/*', readonly)
                    page.goto(base + path + '?' + '&'.join(k+'='+v for k, v in scope.items()), wait_until='networkidle')
                    hero = page.locator('.wrap > div.card').first
                    assert hero.get_by_text(mentor['research_direction_raw'], exact=True).is_visible()
                    assert hero.get_by_text(mentor['supervisor'], exact=True).is_visible()
                    assert hero.locator('a[href^="mailto:"]').get_attribute('href') == 'mailto:' + mentor['email']
                    assert hero.get_by_text('查看学校官网资料 ↗', exact=True).get_attribute('href') == (mentor.get('profile_url') or mentor['detail_url'])
                    if not mentor.get('institutes'):
                        assert not hero.get_by_text('所属团队', exact=True).count()
                    if not mentor.get('homepage'):
                        assert not hero.get_by_text('个人主页', exact=True).count()
                    evidence = page.locator('#profile-evidence')
                    assert not evidence.evaluate('(e)=>e.open')
                    assert not evidence.locator('.meta').is_visible()
                    assert '已富化' not in page.locator('body').inner_text()
                    for link in page.locator('.context-actions a').all():
                        query = parse_qs(urlsplit(link.get_attribute('href')).query)
                        assert all(query.get(k) == [v] for k, v in scope.items()), query
                    assert not page.locator('#detail-scope-warning').is_visible()
                    page.screenshot(path=str(output / f'detail-{width}.png'))
                    summary = evidence.locator('summary')
                    summary.focus()
                    summary.press('Enter')
                    assert evidence.locator('.meta').is_visible()
                    assert evidence.locator('tr').count() == len(mentor['provenance']) + 1
                    assert evidence.locator('a[href]').count() == len(mentor['provenance'])
                    assert str(mentor['first_seen']) in evidence.inner_text()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    evidence.screenshot(path=str(output / f'evidence-{width}.png'))
                    summary.press('Enter')
                    page.locator('#detail-compare').click()
                    assert page.locator('#detail-compare').get_attribute('aria-pressed') == 'true'
                    assert mentor['page'] in page.evaluate("JSON.parse(localStorage.getItem('compare_sel'))")
                    page.locator('#detail-compare').click()
                    assert page.locator('#detail-compare').get_attribute('aria-pressed') == 'false'
                    for element_id in ('obox', 'ob-status', 'ob-save', 'ob-remove', 'ob-msg', 'ob-notes', 'ob-next', 'ob-due', 'ob-tags', 'ob-history'):
                        assert page.locator('#' + element_id).count() == 1
                    page.goto(base + path + '?school=pku&dept=cs&year=2027&track=special&program=0812', wait_until='networkidle')
                    assert page.locator('#detail-scope-warning').is_visible()
                    query = parse_qs(urlsplit(page.locator('.context-actions a.primary').get_attribute('href')).query)
                    assert query['school'] == ['bit'] and query['dept'] == ['cs']
                    assert query['mentor'] == [mentor['page']] and query['year'] == ['2027']
                    assert 'track' not in query and 'program' not in query
                    assert not errors and not writes, (errors, writes)
                    result['cases'].append({'width': width, 'passed': True, 'scope_and_comparison_preserved': True, 'source_rows': len(mentor['provenance'])})
                    context.close()
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    result['passed'] = True
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

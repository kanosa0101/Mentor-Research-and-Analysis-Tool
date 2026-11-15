"""Exercise built notice pages without writing private data or contacting schools."""
import json
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import serve_public
from scripts.release_page_v1_ui_check import signatures


def main():
    out = ROOT / 'cache/notices_v14_ui'
    out.mkdir(parents=True, exist_ok=True)
    before = signatures()
    results = []
    server = serve_public.create_server(ROOT, '127.0.0.1', 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (1440, 390):
                page = browser.new_page(viewport={'width': width, 'height': 900})
                errors, writes = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD') else None)
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                page.goto(base + '/notices.html', wait_until='networkidle')
                rows = page.locator('#notice-data').text_content()
                rows = json.loads(rows)
                assert rows and all('classification' in row for row in rows), 'Build with annotate_notices first'
                visible = lambda: page.locator('article[data-notice-id]:visible').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.noticeId)')
                expected = [row['id'] for row in rows if any(t['cycle'] in ('current', 'preparation') for t in row['classification']['tracks'])]
                assert sorted(visible()) == sorted(expected)
                assert page.locator('#notice-cycle').input_value() == 'current'
                assert '不表示报名开放' in page.locator('#notice-cycle-guide').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(out / f'current-{width}.png'))
                if expected:
                    page.locator('article[data-notice-id]:visible').first.screenshot(path=str(out / f'current-card-{width}.png'))
                page.locator('[data-notice-cycle="unknown"]').click()
                unknown = [row['id'] for row in rows if any(t['cycle'] == 'unknown' for t in row['classification']['tracks'])]
                assert sorted(visible()) == sorted(unknown)
                if unknown:
                    first = page.locator('article[data-notice-id]:visible').first
                    first.locator('summary').click()
                    assert '不等于正文已核验' in first.inner_text()
                    first.screenshot(path=str(out / f'unknown-card-{width}.png'))
                page.locator('#notice-cycle').scroll_into_view_if_needed()
                page.screenshot(path=str(out / f'unknown-{width}.png'))
                page.locator('#notice-cycle').select_option('current')
                page.locator('#notice-route').select_option('exam')
                exams = [row['id'] for row in rows if any(t['route'] == 'exam' and t['cycle'] in ('current', 'preparation') for t in row['classification']['tracks'])]
                assert sorted(visible()) == sorted(exams)
                assert page.locator('#notice-general-hint').is_visible()
                page.locator('#notice-general-policy').click()
                assert page.locator('#notice-route').input_value() == 'unknown'
                assert all(any(t['route'] == 'unknown' for t in row['classification']['tracks']) for row in rows if row['id'] in visible())
                page.locator('#notice-admission-year').select_option('')
                page.locator('#notice-route').select_option('recommend')
                recommendations = [row['id'] for row in rows if any(t['route'] == 'recommend' and t['cycle'] in ('current', 'preparation') for t in row['classification']['tracks'])]
                assert sorted(visible()) == sorted(recommendations)
                page.locator('[data-notice-cycle="historical"]').click()
                previous = [row['id'] for row in rows if any(t['route'] == 'recommend' and t['cycle'] == 'historical' for t in row['classification']['tracks'])]
                assert sorted(visible()) == sorted(previous)
                page.locator('#notice-route').select_option('')
                page.locator('#notice-cycle').select_option('all')
                page.locator('#notice-admission-year').select_option('2027')
                assert all(row['classification']['admission_year'] == 2027 for row in rows if row['id'] in visible())
                page.locator('#notice-more-years > summary').click()
                page.locator('#notice-graduation-year').select_option('unknown')
                assert all(row['classification']['graduation_year'] is None for row in rows if row['id'] in visible())
                page.reload(wait_until='networkidle')
                assert page.locator('#notice-admission-year').input_value() == '2027'
                assert page.locator('#notice-graduation-year').input_value() == 'unknown'
                assert page.locator('#notice-more-years').get_attribute('open') is not None
                linked = next((row for row in rows if row['classification'].get('linked_opportunity_id')), None)
                assert linked, 'Expected at least one notice with verified activity details'
                page.goto(base + '/notices.html?notice_cycle=all&q=' + quote(linked['title']), wait_until='networkidle')
                detail = page.get_by_role('link', name='查看已整理的条件与材料 →')
                assert detail.is_visible()
                assert parse_qs(urlsplit(detail.get_attribute('href')).query)['id'] == [linked['classification']['linked_opportunity_id']]
                page.locator('article[data-notice-id]:visible').first.screenshot(path=str(out / f'linked-card-{width}.png'))
                page.goto(base + '/notices.html?school=pku&dept=cs&year=2027&degree=master&route=recommend', wait_until='networkidle')
                assert page.locator('#school').input_value() == 'pku/cs'
                target = parse_qs(urlsplit(page.locator('#notice-policy-link').get_attribute('href')).query)
                assert target == dict(school=['pku'], dept=['cs'], year=['2027'], degree=['master'], route=['recommend'])
                page.locator('#notice-cycle').select_option('all')
                assert all(row['school'] == 'pku' and row['dept'] == 'cs' for row in rows if row['id'] in visible())
                page.goto(base + '/notices.html?school=pku&dept=unconnected-v14', wait_until='networkidle')
                assert page.locator('#school').input_value() == 'pku/unconnected-v14'
                assert page.locator('#notice-empty').is_visible()
                assert '尚未接入' in page.locator('#notice-context').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors and not writes, (errors, writes)
                results.append(dict(width=width, passed=True, total=len(rows), current=len(expected),
                                    unknown=len(unknown), exam_current=len(exams), recommendation_history=len(previous),
                                    page_errors=errors, writes=writes, legacy_context_preserved=True))
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    assert signatures() == before
    report = dict(passed=True, private_files_unchanged=True, cases=results)
    (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()

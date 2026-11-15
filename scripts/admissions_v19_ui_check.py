"""Check policy information hierarchy and preserved application scope on real pages."""
import argparse
import json
import shutil
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'cache/v19/admissions'


def check(base, output):
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 950})
            page = context.new_page()
            errors, writes = [], []
            def readonly(route):
                if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    writes.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*', readonly)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '/admissions.html', wait_until='networkidle')
            page.wait_for_function('window.ADMISSIONS_READY')
            assert page.locator('.policy-card').count() == 0
            assert page.locator('#policy-welcome').is_visible()
            assert page.locator('#school-shortcuts button').count() == 8
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(output / f'welcome-{width}.png'), full_page=True)
            page.select_option('#policy-school', 'bit')
            page.select_option('#policy-dept', 'cs')
            page.fill('#policy-year', '2027')
            page.locator('#policy-year').blur()
            page.select_option('#policy-degree', 'master')
            page.select_option('#policy-route', 'exam')
            page.locator('[data-configure-target]').click()
            assert page.locator('#policy-target-more').get_attribute('open') is not None
            page.select_option('#policy-track', 'ordinary')
            page.locator('#policy-target-more > summary').click()
            assert '普通招生' in page.locator('#policy-target-more-label').inner_text()
            assert page.locator('#application-checklist > .checklist-fields > .checklist-field').count() == 3
            assert page.locator('[data-checklist-field=exams]').is_hidden()
            assert page.locator('#official-entry-details').get_attribute('open') is None
            assert page.locator('#policy-scope-details').get_attribute('open') is None
            assert page.locator('#policy-welcome').is_hidden()
            project = parse_qs(urlsplit(page.locator('#checklist-project').get_attribute('href')).query)
            assert all(project.get(k) == [v] for k, v in {'school': 'bit', 'dept': 'cs', 'year': '2027', 'degree': 'master', 'route': 'exam', 'track': 'ordinary'}.items())
            assert page.locator('.checklist-preview').evaluate_all('(nodes)=>nodes.every(n=>n.textContent.length<=151)')
            card = page.locator('#policy-bit-2027-master-exam')
            assert card.is_visible()
            assert card.locator('.policy-body').get_attribute('open') is None
            assert card.locator('.policy-age').first.is_visible()
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.evaluate('scrollTo(0,0)')
            page.screenshot(path=str(output / f'target-{width}.png'), full_page=True)
            card.locator('.policy-body > summary').click()
            assert card.locator('.policy-fields > section').count() == 8
            assert card.get_by_text('核对完整政策 ↗', exact=True).is_visible()
            card.locator('.policy-field details').first.locator('summary').click()
            assert card.locator('.policy-field blockquote').first.is_visible()
            card.locator('.policy-body > summary').click()
            # Hash navigation opens the policy instead of leaving the target hidden.
            page.locator('[data-checklist-field=eligibility] > details > summary').click()
            page.locator('[data-checklist-field=eligibility] a[href="#policy-bit-2027-master-exam"]').click()
            assert card.locator('.policy-body').get_attribute('open') is not None
            assert page.url.endswith('#policy-bit-2027-master-exam')
            page.goto(base + '/admissions.html?school=bit&dept=cs&year=2027&degree=master&route=exam&track=ordinary#policy-bit-2027-master-exam', wait_until='networkidle')
            assert page.locator('#policy-bit-2027-master-exam .policy-body').get_attribute('open') is not None
            page.locator('#official-entry-details > summary').click()
            assert page.locator('#unit-entries a').first.is_visible()
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.screenshot(path=str(output / f'policy-detail-{width}.png'), full_page=True)
            page.fill('#policy-year', '2028');page.locator('#policy-year').blur()
            assert page.locator('#policy-bit-2027-master-exam').count() == 0
            assert '暂无政策摘要' in page.locator('#application-checklist').inner_text()
            assert not errors, errors
            assert not writes, writes
            checks.append({'width': width, 'welcome_without_policy_wall': True, 'three_primary_requirement_cards': True,
                           'advanced_scope_visible_in_summary': True, 'full_policy_and_evidence_accessible': True,
                           'project_goal_preserved': True, 'hash_reveals_policy': True, 'wrong_year_not_borrowed': True,
                           'horizontal_overflow': False, 'page_errors': errors, 'writes': writes})
            context.close()
        browser.close()
    (output / 'result.json').write_text(json.dumps({'passed': True, 'checks': checks, 'private_writes': False}, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(checks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', help='Existing site URL for read-only verification')
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    if args.base:
        check(args.base.rstrip('/'), args.output)
        return
    with tempfile.TemporaryDirectory(prefix='admissions-ui-v19-') as folder:
        site = Path(folder)
        for name in ('admissions-data.js', 'admissions-core.js', 'admissions.js', 'material-actions.js', 'ui.css'):
            shutil.copyfile(ROOT / 'site' / name, site / name)
        env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'), autoescape=True)
        (site / 'admissions.html').write_text(env.get_template('admissions.html.j2').render(), encoding='utf8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(site)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            check(f'http://127.0.0.1:{server.server_port}', args.output)
        finally:
            server.shutdown();server.server_close()


if __name__ == '__main__':
    main()

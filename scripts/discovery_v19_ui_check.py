"""Check discovery information hierarchy and compact responsive mentor cards."""
import argparse
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_site, serve_public


def check(base, output):
    result = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in (1440, 390):
            context = browser.new_context(viewport={'width': width, 'height': 1000})
            page = context.new_page()
            errors, requests, writes = [], [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda req: requests.append(req.url))
            def readonly(route):
                if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    writes.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*', readonly)
            page.goto(base + '/discovery.html', wait_until='domcontentloaded')
            page.wait_for_function('window.DISCOVERY_READY')
            assert page.locator('[data-candidate]').count() == 20
            assert page.locator('#intent-name').is_visible()
            assert page.locator('#intent-topics').is_visible()
            assert page.locator('#intent-degree').is_visible()
            assert not page.locator('#intent-year').is_visible()
            assert not page.locator('#degree-filter-note').is_visible()
            assert not page.locator('#mode-opportunity').is_visible()
            assert not page.locator('#discovery-backup').is_visible()
            assert not page.locator('#workflow-tools').is_visible()
            assert not page.locator('#discovery-message').is_visible(), 'Expected public/private API 404 must not look like a product error'
            assert page.locator('#discovery-restore').is_disabled()
            assert '年度未定' not in page.locator('#intent-overview').inner_text()
            cards = page.locator('[data-candidate]')
            first, second = cards.nth(0).bounding_box(), cards.nth(1).bounding_box()
            if width == 1440:
                assert abs(first['y'] - second['y']) < 2 and second['x'] > first['x']
                assert 340 <= first['width'] <= 500, first
            else:
                assert second['y'] > first['y'] and abs(first['x'] - second['x']) < 2
                assert first['y'] < 850, first
            assert first['height'] < 500, first
            assert cards.first.locator('.card-primary-actions > *').count() == 3
            assert cards.first.locator('.candidate-proof').evaluate('(e)=>!e.open')
            assert cards.first.locator('.candidate-application').evaluate('(e)=>!e.open')
            assert cards.first.locator('.public-email a').get_attribute('href').startswith('mailto:')
            page.screenshot(path=str(output/f'discovery-{width}-initial.png'), full_page=False)
            cards.first.scroll_into_view_if_needed()
            page.screenshot(path=str(output/f'discovery-{width}-cards.png'), full_page=False)
            cards.first.locator('.candidate-proof summary').click()
            assert cards.first.locator('.preview-source a').is_visible()
            cards.first.locator('.candidate-proof summary').click()
            page.locator('#filter-options').evaluate('(e)=>e.open=true')
            page.locator('#school-search').fill('pku')
            page.locator('#school-options input[value=pku]').check()
            page.locator('#filter-options').evaluate('(e)=>e.open=false')
            assert page.locator('#school-chips button').is_visible()
            assert '已选 1 所' in page.locator('#filter-options-label').inner_text()
            page.locator('#school-chips button').click()
            assert page.locator('#school-chips button').count() == 0
            assert page.locator('#filter-options-label').evaluate('(e)=>e===document.activeElement')
            page.locator('#advanced-criteria summary').click()
            page.select_option('#intent-degree', 'master')
            assert '优先展示' in page.locator('#degree-filter-note').inner_text()
            page.locator('#intent-year').fill('2028')
            page.select_option('#intent-route', 'recommend')
            page.select_option('#mode-email', 'off')
            page.locator('#advanced-criteria summary').click()
            summary = page.locator('#advanced-criteria-label').inner_text()
            assert '2028入学' in summary and '推免' in summary and '1项规则已调整' in summary
            page.locator('#apply-criteria').click()
            page.wait_for_function('!document.getElementById("apply-criteria").disabled')
            assert '2028入学' in page.locator('#intent-overview').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            assert not errors and not writes, (errors, writes)
            assert not any('/discovery-data.js?' in u or '/search.js?' in u for u in requests)
            result.append({'width': width, 'first_card': first, 'natural_height_layout': True,
                           'basic_filters_visible': True, 'advanced_filters_disclosed': True,
                           'selected_schools_visible_when_collapsed': True, 'changed_rule_summary': summary,
                           'direct_email_and_contact': True, 'private_controls_secondary': True,
                           'no_overflow': True, 'page_errors': errors, 'writes': writes,
                           'full_catalog_not_loaded': True})
            context.close()
        browser.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--output', type=Path, default=ROOT/'cache/v19/discovery-ui')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mentor-discovery-v19-') as directory:
        server = None
        try:
            if args.base:
                base = args.base.rstrip('/')
            else:
                root = Path(directory)
                site = root/'site'
                site.mkdir()
                for name in ('school-catalog.js', 'discovery-data.js', 'search.js', 'discovery-core.js', 'discovery.js',
                             'browser-library-core.js', 'browser-library.js', 'ui.css'):
                    shutil.copyfile(ROOT/'site'/name, site/name)
                (site/'discovery.html').write_text(build_site.render_discovery_page(site), encoding='utf8')
                server = serve_public.create_server(root, '127.0.0.1', 0)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                base = f'http://127.0.0.1:{server.server_port}'
            cases = check(base, args.output)
            (args.output/'result.json').write_text(json.dumps({'passed': True, 'cases': cases}, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps(cases, ensure_ascii=False))
        finally:
            if server:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()

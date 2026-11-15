"""Read-only paged mentor search, privacy fallback and mobile navigation checks."""
import argparse
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_site, serve_public

HEAVY = ('discovery-data.js', 'data.js', 'search.js', 'admissions-data.js', 'compare-data.js')


def run(base, output, isolated, static_site=None):
    cases = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 950})
                page = context.new_page()
                errors, requests, writes = [], [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append(request.url))

                def readonly(route):
                    if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                        writes.append(route.request.url)
                        route.abort()
                    else:
                        route.continue_()

                context.route('**/*', readonly)
                begin = time.monotonic()
                page.goto(base + '/discovery.html', wait_until='domcontentloaded')
                page.wait_for_function('window.DISCOVERY_READY')
                ready = round((time.monotonic() - begin) * 1000)
                assert page.locator('[data-candidate]').count() == 20
                assert page.evaluate('paged') is True
                resources = page.evaluate("performance.getEntriesByType('resource').map(r=>({url:r.name,encoded:r.encodedBodySize}))")
                data_bytes = page.evaluate("performance.getEntriesByType('navigation')[0].encodedBodySize") + sum(r['encoded'] for r in resources)
                assert 0 < data_bytes <= 200 * 1024, data_bytes
                assert not page.locator('script[src],link[rel=stylesheet]').count(), 'First-screen static assets should be inlined'
                first = page.locator('[data-candidate]').evaluate_all('(els)=>els.map(e=>e.dataset.candidate)')
                page.locator('[data-compare]').first.click()
                page.locator('#more-candidates').click()
                page.wait_for_function('document.querySelectorAll("[data-candidate]").length===40')
                forty = page.locator('[data-candidate]').evaluate_all('(els)=>els.map(e=>e.dataset.candidate)')
                assert len(set(forty)) == 40 and forty[:20] == first
                page.locator('[data-compare]').nth(20).click()
                page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert page.locator('[data-candidate]').evaluate_all('(els)=>els.map(e=>e.dataset.candidate)') == first
                assert page.evaluate('compareSelection.length') == 2
                page.locator('#compare-open').click()
                page.locator('.pcol').nth(1).wait_for()
                assert page.locator('.pcol').count() == 2
                page.go_back(wait_until='domcontentloaded')
                page.wait_for_function('window.DISCOVERY_READY')
                assert page.evaluate('compareSelection.length') == 2
                assert page.locator('[data-candidate]').evaluate_all('(els)=>els.map(e=>e.dataset.candidate)') == first
                page.locator('#intent-topics').fill('计算机视觉')
                page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert page.locator('[data-candidate]').count() > 0
                assert page.evaluate('view.some(r=>r.result.evidence.length>0)')
                page.locator('#filter-options').evaluate('(el)=>el.open=true')
                page.locator('#school-search').fill('pku')
                page.locator('#school-options input[value=pku]').check()
                page.locator('#school-search').fill('tsinghua')
                page.locator('#school-options input[value=tsinghua]').check()
                page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert page.locator('#school-chips button').count() == 2
                assert page.evaluate('view.every(r=>["pku","tsinghua"].includes(r.p.school))')
                page.goto(base + '/start.html', wait_until='domcontentloaded')
                page.go_back(wait_until='domcontentloaded')
                page.wait_for_function('window.DISCOVERY_READY')
                assert page.locator('#intent-topics').input_value() == '计算机视觉'
                assert page.locator('#school-chips button').count() == 2
                assert not any(urlsplit(url).path.rsplit('/', 1)[-1] in HEAVY for url in requests)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.locator('#discovery-results').scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'discovery-{width}.png'))
                assert not errors and not writes, (errors, writes)
                queries = [parse_qs(urlsplit(url).query) for url in requests if '/api/mentor-candidates?' in url]
                assert all(not {'project', 'track', 'program', 'goal', 'goal_snapshot', 'reviews'} & set(q) for q in queries)
                cases.append({'width': width, 'initial_ready_ms': ready, 'initial_data_encoded_bytes': data_bytes,
                              'first_page': 20, 'pagination_unique': 40, 'stable_repeat_order': True,
                              'comparison_survives_other_pages': True, 'search_school_and_back': True,
                              'no_full_indexes': True, 'no_horizontal_overflow': True,
                              'page_errors': errors, 'non_read_requests': writes})
                context.close()

            if isolated:
                context = browser.new_context()
                page = context.new_page()
                requests = []
                page.on('request', lambda request: requests.append(request.url))
                revised = []

                def revision(route):
                    response = route.fetch()
                    value = response.json()
                    if parse_qs(urlsplit(route.request.url).query).get('offset') == ['20']:
                        value['revision'] += '-new'
                        revised.append(True)
                    route.fulfill(response=response, json=value)

                page.route('**/api/mentor-candidates?*', revision)
                page.goto(base + '/discovery.html', wait_until='domcontentloaded')
                page.wait_for_function('window.DISCOVERY_READY')
                page.locator('#more-candidates').click()
                page.wait_for_function("document.getElementById('discovery-message').textContent.includes('公开资料已更新')")
                assert revised and page.locator('[data-candidate]').count() == 20
                cases.append({'revision_change_resets_first_page': True})
                context.close()

                context = browser.new_context()
                page = context.new_page()
                page.goto(base + '/discovery.html', wait_until='domcontentloaded')
                page.wait_for_function('window.DISCOVERY_READY')
                original = page.locator('[data-candidate]').evaluate_all('(els)=>els.map(e=>e.dataset.candidate)')
                page.route('**/api/mentor-candidates?*', lambda route: route.fulfill(status=503, json={'error': 'temporarily unavailable'}))
                page.locator('#more-candidates').click()
                page.wait_for_function("document.getElementById('discovery-message').textContent.includes('下一批导师未能加载')")
                assert page.locator('[data-candidate]').evaluate_all('(els)=>els.map(e=>e.dataset.candidate)') == original
                page.unroute('**/api/mentor-candidates?*')
                page.route('**/api/mentor-candidates?*', lambda route: route.fulfill(status=400, json={'error': '关键词过多'}))
                page.locator('#apply-criteria').click()
                page.wait_for_function("document.getElementById('discovery-message').textContent.includes('关键词过多')")
                assert page.evaluate('paged&&!fullDataLoaded')
                assert page.locator('[data-candidate]').evaluate_all('(els)=>els.map(e=>e.dataset.candidate)') == original
                cases.append({'pagination_failure_preserves_results': True, 'invalid_query_keeps_existing_results_without_full_download': True})
                context.close()

                for scenario in ('unsupported', 'empty-private', 'private-review', 'project-scope'):
                    context = browser.new_context()
                    page = context.new_page()
                    requests = []
                    page.on('request', lambda request: requests.append(request.url))
                    if scenario == 'unsupported':
                        page.route('**/api/mentor-candidates?*', lambda route: route.fulfill(status=404, json={'error': 'unsupported'}))
                    if scenario in ('empty-private', 'private-review'):
                        prefs = {'year': None, 'degree': 'any', 'route': 'unknown', 'topics': [], 'schools': [],
                                 'keep_unknown': True, 'modes': {'research': 'hard', 'qualification': 'soft',
                                 'email': 'soft', 'opportunity': 'soft', 'eligibility': 'soft'}}
                        reviews = {'private-sentinel': {'mentor_id': 'private-sentinel'}} if scenario == 'private-review' else {}
                        page.route('**/api/discovery', lambda route: route.fulfill(json={'preferences': prefs, 'reviews': reviews}))
                        page.route('**/api/discovery/project-reviews', lambda route: route.fulfill(json={'projects': {}, 'project_reviews': {}, 'replies': {}}))
                    suffix = '?project=private-project-sentinel' if scenario == 'project-scope' else ''
                    page.goto(base + '/discovery.html' + suffix, wait_until='domcontentloaded')
                    page.wait_for_function('window.DISCOVERY_READY')
                    assert page.locator('[data-candidate]').count() == 20
                    if scenario == 'empty-private':
                        assert page.evaluate('API_OK&&paged&&!fullDataLoaded')
                        assert not any('/discovery-data.js?' in url for url in requests)
                        cases.append({'empty_local_reviews_keep_pagination': True})
                        context.close()
                        continue
                    assert page.evaluate('fullDataLoaded&&!paged')
                    assert any('/discovery-data.js?' in url for url in requests)
                    candidate_requests = [u for u in requests if '/api/mentor-candidates?' in u]
                    assert scenario == 'unsupported' or not candidate_requests
                    assert all('private-sentinel' not in u and 'private-project-sentinel' not in u for u in candidate_requests)
                    cases.append({'fallback': scenario, 'local_filtering': True, 'private_data_not_sent_to_candidates': True})
                    context.close()

                context = browser.new_context()
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto((static_site / 'discovery.html').as_uri(), wait_until='domcontentloaded')
                page.wait_for_function('window.DISCOVERY_READY')
                assert page.evaluate('fullDataLoaded&&!paged')
                assert page.locator('[data-candidate]').count() == 20
                assert page.locator('#school-options input').count() > 0
                assert not errors, errors
                cases.append({'fallback': 'file-protocol', 'local_filtering': True, 'page_errors': errors})
                context.close()
        finally:
            browser.close()
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--output', type=Path, default=ROOT / 'cache/v17/discovery-ui')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mentor-v17-ui-') as temp:
        server = None
        try:
            if args.base:
                base = args.base.rstrip('/')
            else:
                root = Path(temp)
                site = root / 'site'
                site.mkdir()
                for name in ('school-catalog.js', 'discovery-data.js', 'data.js', 'search.js', 'compare-data.js',
                             'discovery-core.js', 'discovery.js', 'browser-library-core.js', 'browser-library.js',
                             'ui.css', 'start.html', 'start.js', 'plan-transfer.js', 'public-data.js'):
                    shutil.copyfile(ROOT / 'site' / name, site / name)
                for name in ('discovery', 'compare'):
                    html = build_site.render_discovery_page(site) if name == 'discovery' else build_site.template_environment().get_template(name + '.html.j2').render()
                    (site / (name + '.html')).write_text(html, encoding='utf-8')
                build_site.build_discovery_entry(site)
                server = serve_public.create_server(root, '127.0.0.1', 0)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                base = f'http://127.0.0.1:{server.server_port}'
            cases = run(base, args.output, not args.base, None if args.base else site)
            (args.output / 'results.json').write_text(json.dumps({'passed': True, 'base': base, 'cases': cases}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(cases, ensure_ascii=True))
        finally:
            if server:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()

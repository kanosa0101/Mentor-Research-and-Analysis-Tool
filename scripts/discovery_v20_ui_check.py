"""Exercise the simplified directory in an isolated, read-only public server."""
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
from crawler.public_catalog import load
from crawler.public_discovery import valid_email
from scripts import build_site, serve_public


def prepare(root):
    site = root / 'site'
    site.mkdir()
    for name in ('school-catalog.js', 'discovery-core.js', 'discovery.js', 'browser-library-core.js', 'browser-library.js', 'ui.css'):
        shutil.copyfile(ROOT / 'site' / name, site / name)
    extra = load(ROOT, 'compare-data.js')
    rows = []
    for p in load(ROOT, 'discovery-data.js'):
        source = p.get('email_source') or extra.get(p['page'], {}).get('provenance', {}).get('email', {}).get('source')
        if not valid_email(p.get('email')) or not source:
            continue
        rows.append(dict(p, email_source=source))
        if len(rows) == 45:
            break
    # Deliberate mixed field budgets are independent of today's live collection.
    for i, p in enumerate(rows):
        p['school'] = 'bit' if i % 2 else 'pku'
        p['school_name'] = '北京理工大学' if i % 2 else '北京大学'
        p['supervisor'] = ['博导', '硕导', '博导、硕导', ''][i % 4]
        p['title'] = ['教授', '副教授', '助理教授', '教授级高级工程师', '', '特聘副研究员'][i % 6]
        if i % 6 == 0:
            p['research_direction_raw'] = '计算机视觉与机器学习、跨模态多媒体、可信人工智能、机器人、智能系统的理论方法与研究' * 5
            p['name'] = '长姓名混排样本' + p['name']
        if i % 6 == 1:
            p['dept_name'] = '计算机科学与技术及网络空间安全人工智能交叉研究联合学院'
        if i % 6 == 2:
            p['research_direction_raw'] = ''
            p['bio_excerpt'] = ''
        if i % 6 == 3:
            p['recruitment_labels'] = ['本科科研招募']
        if i % 6 == 4:
            p['email'] = 'very-long-but-valid-contact-address-for-lab@department.university.edu.cn'
        if i % 6 == 5:
            p['research_direction_raw'] = 'AI'
    rows.append(dict(rows[0], page='bit-cs-noemail', name='无邮箱样本', email=''))
    for name, value in [('discovery-data.js', rows), ('search.js', {p['page']: p.get('bio_excerpt', '') for p in rows})]:
        (site / name).write_text('window.' + ('MENTOR_DATA' if name.startswith('discovery') else 'MENTOR_SEARCH') + '=' + json.dumps(value, ensure_ascii=False) + ';', encoding='utf8')
    (site / 'p').mkdir()
    env = build_site.template_environment()
    for p in rows:
        profile = dict(p, bio_raw=p.get('bio_excerpt', ''), institutes=[], status='enriched')
        (site / 'p' / (p['page'] + '.html')).write_text(env.get_template('detail.html.j2').render(p=profile), encoding='utf8')
    (site / 'compare.html').write_text(env.get_template('compare.html.j2').render(profs=rows), encoding='utf8')
    (site / 'data.js').write_text('window.MENTOR_DATA=' + json.dumps(rows, ensure_ascii=False) + ';', encoding='utf8')
    (site / 'compare-data.js').write_text('window.MENTOR_COMPARE={};', encoding='utf8')
    (site / 'discovery.html').write_text(build_site.render_discovery_page(site), encoding='utf8')


def inspect(page):
    return page.locator('[data-candidate]').evaluate_all('''cards=>cards.map(c=>{const r=c.getBoundingClientRect(),a=c.querySelector('.card-primary-actions').getBoundingClientRect();return {width:r.width,height:r.height,actions:a.y-r.y,overflow:c.scrollWidth>c.clientWidth+1,verticalOverflow:c.scrollHeight>c.clientHeight+1}})''')


def check(base, output):
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, scale in [(1440, 1), (390, 1), (320, 1), (768, 1), (720, 2)]:
            context = browser.new_context(viewport={'width': width, 'height': 1000}, device_scale_factor=scale)
            page = context.new_page()
            errors, requests, writes = [], [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('request', lambda r: requests.append(r.url))
            def guard(route):
                if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    writes.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            context.route('**/*', guard)
            page.goto(base + '/discovery.html?degree=phd&mode_opportunity=hard&keep_unknown=0', wait_until='domcontentloaded')
            page.wait_for_function('window.DISCOVERY_READY')
            assert page.locator('[data-candidate]').count() == 20
            assert page.locator('#intent-degree,#intent-year,#intent-route,[id^=mode-],#keep-unknown,#review-panel').count() == 0
            assert '45 位候选' in page.locator('#discovery-count').inner_text()
            dimensions = inspect(page)
            assert max(x['height'] for x in dimensions) - min(x['height'] for x in dimensions) <= 1, dimensions
            assert max(x['width'] for x in dimensions) - min(x['width'] for x in dimensions) <= 1, dimensions
            assert max(x['actions'] for x in dimensions) - min(x['actions'] for x in dimensions) <= 1, dimensions
            assert not any(x['overflow'] or x['verticalOverflow'] for x in dimensions), dimensions
            assert page.locator('[data-candidate] details').count() == 0
            assert page.locator('[data-candidate] .public-email a').count() == 20
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output / f'directory-{width}-{scale}x-initial.png'))
            page.locator('[data-candidate]').first.scroll_into_view_if_needed()
            page.screenshot(path=str(output / f'directory-{width}-{scale}x-cards.png'))
            if width == 1440:
                ids = page.locator('[data-candidate]').evaluate_all('(els)=>els.map(x=>x.dataset.candidate)')
                page.locator('#more-candidates').click()
                page.wait_for_function('document.querySelectorAll("[data-candidate]").length===40')
                ids40 = page.locator('[data-candidate]').evaluate_all('(els)=>els.map(x=>x.dataset.candidate)')
                assert ids40[:20] == ids and len(set(ids40)) == 40
                page.locator('[data-candidate]').nth(35).locator('h2 a').click()
                page.wait_for_selector('h1')
                page.go_back(wait_until='domcontentloaded')
                page.wait_for_function('window.DISCOVERY_READY&&document.querySelectorAll("[data-candidate]").length===40')
                assert page.locator('[data-candidate]').evaluate_all('(els)=>els.map(x=>x.dataset.candidate)') == ids40
                page.wait_for_function('scrollY>1000')
                page.locator('[data-candidate]').nth(35).locator('h2 a').click()
                page.locator('.context-actions a[href^="../discovery.html"]').click()
                page.wait_for_function('window.DISCOVERY_READY&&document.querySelectorAll("[data-candidate]").length===40')
                page.wait_for_function('scrollY>1000')
                page.locator('[data-compare]').nth(35).click()
                page.locator('#compare-open').click()
                page.wait_for_selector('.context-actions a[href^="discovery.html"]')
                page.locator('.context-actions a[href^="discovery.html"]').click()
                page.wait_for_function('window.DISCOVERY_READY&&document.querySelectorAll("[data-candidate]").length===40')
                page.wait_for_function('scrollY>1000')
                assert page.locator('[data-candidate]').evaluate_all('(els)=>els.map(x=>x.dataset.candidate)') == ids40
                page.locator('[data-compare]').nth(35).click()
                page.locator('#filter-options').evaluate('(e)=>e.open=true')
                page.locator('#school-search').fill('pku')
                page.locator('#school-options input[value=pku]').check()
                page.locator('#school-search').fill('bit')
                page.locator('#school-options input[value=bit]').check()
                page.locator('#filter-options').evaluate('(e)=>e.open=false')
                assert page.locator('#school-chips button').count() == 2
                page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert '45 位候选' in page.locator('#discovery-count').inner_text()
                page.locator('#school-chips button').first.click()
                assert page.locator('#filter-options-label').evaluate('(e)=>e===document.activeElement')
                page.locator('#school-chips button').first.click()
                page.locator('#qualification-options input[value=master]').check()
                page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert all('硕' in x for x in page.locator('.candidate-qualification').all_text_contents())
                page.locator('#qualification-options input[value=phd]').check()
                page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert page.locator('.candidate-qualification').filter(has_text='资格未明确').count() == 0
                page.locator('#advanced-criteria').evaluate('(e)=>e.open=true')
                page.locator('#title-options input[value=professor]').check()
                page.locator('#advanced-criteria').evaluate('(e)=>e.open=false')
                assert '教授' in page.locator('#advanced-criteria-label').inner_text()
                page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert set(page.locator('.candidate-title').all_text_contents()) == {'教授'}
                page.locator('[data-compare]').first.click()
                assert '已选 1 位' in page.locator('#compare-count').inner_text()
                page.locator('#intent-name').fill('无邮箱样本')
                page.locator('#qualification-options input[value=phd]').uncheck()
                page.locator('#qualification-options input[value=master]').uncheck()
                page.locator('#advanced-criteria').evaluate('(e)=>e.open=true')
                page.locator('#title-options input[value=professor]').uncheck()
                page.locator('#apply-criteria').click()
                page.wait_for_selector('#empty-include-email')
                assert '1 条匹配资料' in page.locator('.empty').inner_text()
                page.locator('#empty-include-email').click()
                page.wait_for_selector('[data-candidate]')
                assert '公开邮箱未明确' in page.locator('[data-candidate]').inner_text()
                assert '已选 1 位' in page.locator('#compare-count').inner_text()
                assert not any('/discovery-data.js?' in u or '/search.js?' in u for u in requests)
            if width == 768:
                page.locator('#qualification-options input[value=phd]').focus()
                page.keyboard.press('Space')
                page.locator('#apply-criteria').focus()
                page.keyboard.press('Enter')
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert all('博' in value for value in page.locator('.candidate-qualification').all_text_contents())
            assert not errors and not writes, (errors, writes)
            assert not any('/api/discovery' in u for u in requests)
            results.append({'width': width, 'scale': scale, 'cards': dimensions, 'no_errors': True, 'no_private_reads_or_writes': True})
            context.close()
        context = browser.new_context()
        page = context.new_page()
        page.goto(base + '/discovery.html')
        page.wait_for_function('window.DISCOVERY_READY')
        def failed_next(route):
            if 'offset=20' in route.request.url:
                route.fulfill(status=503, json={'error': 'offline'})
            else:
                route.continue_()
        page.route('**/api/mentor-candidates?*', failed_next)
        page.locator('#more-candidates').click()
        page.wait_for_function('!document.getElementById("more-candidates").disabled')
        assert page.locator('[data-candidate]').count() == 20
        assert '已保留当前结果' in page.locator('#discovery-message').inner_text()
        page.unroute('**/api/mentor-candidates?*', failed_next)
        def changed_revision(route):
            response = route.fetch()
            data = response.json()
            if 'offset=20' in route.request.url:
                data['revision'] = 'changed-during-pagination'
            route.fulfill(response=response, json=data)
        page.route('**/api/mentor-candidates?*', changed_revision)
        page.locator('#more-candidates').click()
        page.wait_for_function('!document.getElementById("more-candidates").disabled')
        assert page.locator('[data-candidate]').count() == 20
        assert '公开资料已更新' in page.locator('#discovery-message').inner_text()
        context.close()
        # API outage uses the same source/qualification/title contract locally.
        context = browser.new_context()
        page = context.new_page()
        page.route('**/api/mentor-candidates?*', lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
        page.goto(base + '/discovery.html?qualifications=master&titles=assistant_professor')
        page.wait_for_function('window.DISCOVERY_READY')
        assert page.locator('[data-candidate]').count() > 0
        assert set(page.locator('.candidate-title').all_text_contents()) == {'助理教授'}
        assert all('硕' in s for s in page.locator('.candidate-qualification').all_text_contents())
        assert '本地公开资料' in page.locator('#discovery-message').inner_text()
        context.close()
        browser.close()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'cache/v20/discovery')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mentor-directory-v20-') as directory:
        root = Path(directory)
        prepare(root)
        server = serve_public.create_server(root, '127.0.0.1', 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            result = check(f'http://127.0.0.1:{server.server_port}', args.output)
            (args.output / 'result.json').write_text(json.dumps({'passed': True, 'cases': result}, ensure_ascii=False, indent=2), encoding='utf8')
            print('Directory v20 UI: PASS (5 layouts, mixed cards, 40-row return, strict filters, no-email opt-in, API fallback)')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

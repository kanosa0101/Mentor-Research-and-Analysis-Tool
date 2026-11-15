"""Application navigation and browser library on real built pages, isolated browser."""
import copy
import json
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import serve_public
from scripts.release_page_v1_ui_check import signatures

KEY = 'mentor-browser-library-v1'


def main():
    output = ROOT / 'cache/start_v15_ui'
    output.mkdir(parents=True, exist_ok=True)
    before, cases = signatures(), []
    server = serve_public.create_server(ROOT, '127.0.0.1', 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw, tempfile.TemporaryDirectory(prefix='start-v15-backup-') as temporary:
            browser = pw.chromium.launch()
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 900}, accept_downloads=True)
                page = context.new_page()
                errors, writes = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD') else None)
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
                def read():
                    return page.evaluate('(key)=>JSON.parse(localStorage.getItem(key))', KEY)
                def goto(path):
                    page.goto(base + '/' + path, wait_until='networkidle')
                goto('start.html')
                page.wait_for_function('window.START_READY')
                assert read() is None, 'Visiting must not create records'
                assert page.locator('.site-header nav a').count() == 5
                page.screenshot(path=str(output / f'start-{width}.png'))
                page.locator('.school-directory > summary').click()
                for code in ('pku', 'tsinghua'):
                    page.locator('#start-school-search').fill(code)
                    page.locator('#start-school-options input[value="' + code + '"]').check()
                assert page.locator('#target-school-chips button').count() == 2
                page.locator('#target-interest').fill('机器学习')
                mentor_link = page.locator('#target-entries a').filter(has_text='按兴趣找导师').first
                query = parse_qs(urlsplit(mentor_link.get_attribute('href')).query)
                assert query['topics'] == ['机器学习'] and query['school'] == ['pku']
                assert 'year' not in query, 'Graduation year must not become admission year'
                page.locator('#target-form button[type=submit]').click()
                saved = read()
                assert len(saved['targets']) == 1 and saved['targets'][0]['path'] == 'recommend'
                assert len(saved['targets'][0]['schools']) == 2
                page.locator('#target-form button[type=submit]').click()
                assert len(read()['targets']) == 1
                page.locator('[name=path][value=exam]').check()
                exam_query = parse_qs(urlsplit(page.locator('#target-entries a').filter(has_text='学校与招生要求').first.get_attribute('href')).query)
                assert exam_query['route'] == ['exam'] and exam_query['year'] == [page.locator('#target-year').input_value()]
                route_links = page.locator('#target-entries .entry-school').first.locator('a').evaluate_all('(links)=>links.map(a=>a.getAttribute("href"))')
                page.locator('#current-actions button').first.click()
                assert len(read()['todos']) == 1
                page.locator('#todo-title').fill('独立验收：核对官方材料')
                page.locator('#todo-date').fill('2026-12-01')
                page.locator('#todo-target').select_option(saved['targets'][0]['id'])
                page.locator('#todo-form button[type=submit]').click()
                page.locator('#todo-list .todo-title').filter(has_text='独立验收：核对官方材料').locator('input').check()
                assert len(read()['todos']) == 2 and sum(t['done'] for t in read()['todos']) == 1, (read(), page.locator('#library-status').inner_text())
                page.reload(wait_until='networkidle')
                assert len(read()['todos']) == 2
                goto(route_links[1])
                page.wait_for_function('window.ADMISSIONS_READY')
                assert page.locator('#policy-school').input_value() == 'pku'
                goto(route_links[2])
                assert page.locator('#school').input_value() == 'pku'
                goto(route_links[3])
                assert page.locator('#opportunity-school').input_value() == '北京大学'
                assert page.evaluate("[...document.querySelectorAll('[data-opportunity]')].every(card=>opportunityRows.find(row=>row.id===card.dataset.opportunity).school_name==='北京大学')")
                goto('opportunities.html?school=%E9%AA%8C%E6%94%B6%E6%9C%AA%E8%A6%86%E7%9B%96%E5%AD%A6%E6%A0%A1')
                assert page.locator('#opportunity-school').input_value() == '验收未覆盖学校'
                assert page.locator('[data-opportunity]').count() == 0
                # Root integration applies the research keyword to the existing discovery UI.
                goto('discovery.html?school=pku&topics=' + '%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0')
                page.wait_for_function('window.DISCOVERY_READY')
                assert page.locator('#intent-topics').input_value() == '机器学习'
                page.locator('#intent-name').fill('仉尚航')
                page.locator('#apply-criteria').click()
                page.wait_for_function("document.querySelectorAll('[data-candidate]').length===1")
                page.locator('[data-browser-bookmark="mentor"]').first.click()
                assert len(read()['bookmarks']) == 1
                page.locator('[data-browser-bookmark="mentor"]').first.click()
                assert len(read()['bookmarks']) == 1
                goto(read()['bookmarks'][0]['url'])
                page.wait_for_function("getComputedStyle(document.querySelector('#ob-hint')).display!=='none'")
                assert all(page.locator('#' + field).is_disabled() for field in ('ob-status','ob-notes','ob-save','ob-next','ob-due','ob-tags'))
                page.locator('[data-browser-bookmark="mentor"]').click()
                assert len(read()['bookmarks']) == 1, 'Profile and search card should share one bookmark'
                goto('notices.html')
                page.locator('article:visible [data-browser-bookmark="notice"]').first.click()
                goto('opportunities.html')
                page.locator('[data-browser-bookmark="opportunity"]').first.click()
                assert {row['kind'] for row in read()['bookmarks']} == {'mentor', 'notice', 'opportunity'}
                goto('start.html#library')
                assert page.locator('#panel-bookmarks .library-item').count() == 3
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#library').scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'library-{width}.png'))
                with page.expect_download() as info:
                    page.locator('#library-export').click()
                backup_path = Path(temporary) / f'backup-{width}.json'
                info.value.save_as(backup_path)
                backup = json.loads(backup_path.read_text(encoding='utf-8'))
                assert backup == read()
                page.get_by_role('button', name='删除收藏', exact=True).first.click()
                original = read()
                assert len(original['bookmarks']) == 2
                page.locator('#library-import').set_input_files(str(backup_path))
                page.wait_for_function("!document.querySelector('#import-preview').hidden")
                assert read() == original, 'Choosing backup does not import until confirmed'
                page.locator('#library-import-confirm').click()
                assert len(read()['bookmarks']) == 3 and len(read()['todos']) == 2
                malicious = copy.deepcopy(backup)
                malicious['bookmarks'][0]['url'] = 'https://evil.example/notices.html'
                bad_path = Path(temporary) / 'untrusted.json'
                bad_path.write_text(json.dumps(malicious), encoding='utf-8')
                original = read()
                page.locator('#library-import').set_input_files(str(bad_path))
                page.wait_for_function("document.querySelector('#library-status').textContent.startsWith('未导入')")
                assert read() == original
                assert page.locator('#import-preview').is_hidden()
                literal = copy.deepcopy(backup)
                literal['bookmarks'].append(dict(id='literal_html', kind='notice',
                    title='<img src=x onerror="window.BACKUP_XSS=true">',
                    url='notices.html?q=literal-html-test', created_at='2026-11-15'))
                literal_path = Path(temporary) / 'literal.json'
                literal_path.write_text(json.dumps(literal), encoding='utf-8')
                page.locator('#library-import').set_input_files(str(literal_path))
                page.wait_for_function("!document.querySelector('#import-preview').hidden")
                page.locator('#library-import-confirm').click()
                assert page.locator('#panel-bookmarks img').count() == 0
                assert page.evaluate('window.BACKUP_XSS===undefined')
                page.locator('#tab-targets').click()
                page.get_by_role('button', name='删除目标', exact=True).click()
                assert not read()['targets'] and len(read()['todos']) == 2
                assert all(not t['target_id'] for t in read()['todos'])
                page.locator('#tab-todos').click()
                page.get_by_role('button', name='删除待办', exact=True).first.click()
                assert len(read()['todos']) == 1
                assert not errors and not writes, (errors, writes)
                cases.append(dict(width=width, passed=True, explicit_save=True, independent_years=True,
                                  bookmark_kinds=3, backup_roundtrip=True, unsafe_import_rejected=True,
                                  no_network_writes=True, target_school_links_verified=True,
                                  empty_school_not_fallback=True, public_profile_readonly=True, page_errors=errors))
                context.close()
            detail_context = browser.new_context(viewport={'width': 390, 'height': 900})
            detail = detail_context.new_page()
            detail.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            detail.goto(base + '/p/pku-cs-zhangshanghang.html', wait_until='networkidle')
            detail.locator('[data-browser-bookmark="mentor"]').click()
            assert detail.evaluate('(key)=>JSON.parse(localStorage.getItem(key)).bookmarks[0].title', KEY) == '仉尚航'
            assert detail.locator('#ob-save').is_disabled()
            detail.screenshot(path=str(output / 'detail-pilot-390.png'))
            detail_context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    assert signatures() == before
    result = dict(passed=True, private_files_unchanged=True, profile_first_save_title_verified=True, cases=cases)
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Keep directory feedback visible and preserve explicit application context."""
import json
import shutil
import threading
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts import build_site, serve_public


def profiles():
    return [
        dict(page=f'bit-cs-fixture-{i}', name=f'导师{i}', school='bit', dept='cs',
             school_name='北京理工大学', dept_name='计算机学院', supervisor='硕导、博导',
             research_direction_raw='计算机视觉' if i <= 4 else '',
             email=f'teacher{i}@bit.edu.cn', email_source='https://cs.bit.edu.cn/teachers')
        for i in range(1, 22)
    ]


@pytest.fixture
def directory(tmp_path):
    site = tmp_path / 'site'
    site.mkdir()
    catalog = {
        'schools': [{'id': 'bit', 'name': '北京理工大学'}, {'id': 'zju', 'name': '浙江大学'}],
        'units': [{'school': 'bit', 'dept': 'cs', 'dept_name': '计算机学院'}],
    }
    (site / 'school-catalog.js').write_text(
        'window.SCHOOL_CATALOG=' + json.dumps(catalog, ensure_ascii=False) + ';', encoding='utf-8')
    (site / 'discovery.html').write_text(build_site.render_discovery_page(site), encoding='utf-8')
    missing = dict(profiles()[0], page='bit-cs-no-email', name='缺邮箱样本', email='')
    (site / 'discovery-data.js').write_text(
        'window.MENTOR_DATA=' + json.dumps([*profiles(), missing], ensure_ascii=False) + ';', encoding='utf-8')
    (site / 'search.js').write_text('window.MENTOR_SEARCH={};', encoding='utf-8')
    env = build_site.template_environment()
    (site / 'account.html').write_text(env.get_template('account.html.j2').render(), encoding='utf-8')
    for name in ('account-session.js', 'cloud-library.js', 'account.js', 'ui.css'):
        shutil.copyfile(build_site.ROOT / 'site' / name, site / name)
    (site / 'p').mkdir()
    (site / 'p' / 'bit-cs-fixture-5.html').write_text('<h1>导师资料</h1>', encoding='utf-8')
    server = serve_public.create_server(root=tmp_path, host='127.0.0.1', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def intercept_candidates(page, base, queries):
    rows_all = profiles()

    def handle(route):
        url = urlsplit(route.request.url)
        assert route.request.method in ('GET', 'HEAD') and route.request.url.startswith(base + '/')
        if url.path != '/api/mentor-candidates':
            return route.continue_()
        query = parse_qs(url.query)
        queries.append(query)
        if query.get('name') == ['没有结果']:
            rows = []
        elif query.get('name') == ['导师21']:
            rows = rows_all[-1:]
        elif query.get('name') == ['四位导师']:
            rows = rows_all[:4]
        elif query.get('school') == ['zju']:
            rows = [dict(rows_all[0], page='zju-cs-fixture-1', school='zju', school_name='浙江大学')]
        else:
            rows = rows_all
        offset, limit = (int(query[key][0]) for key in ('offset', 'limit'))
        return route.fulfill(json=dict(version=2, total=len(rows), rows=[
            dict(p=row) for row in rows[offset:offset + limit]], missing_email=0, revision='fixture'))

    page.route('**/*', handle)


def href_query(link):
    return parse_qs(urlsplit(link.get_attribute('href')).query)


def scroll_to_submit(page):
    page.locator('#apply-criteria').evaluate(
        '(button)=>scrollTo(0, scrollY+button.getBoundingClientRect().top-160)')


def candidate_ids(page):
    return page.locator('[data-candidate]').evaluate_all('cards => cards.map(card => card.dataset.candidate)')


@pytest.mark.parametrize('width', [1440, 390])
def test_explicit_filter_submit_reveals_results_empty_state_and_error(directory, width):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 560})
        queries = []
        intercept_candidates(page, directory, queries)
        page.goto(directory + '/discovery.html')
        expect(page.locator('[data-candidate]')).to_have_count(4)
        if width == 1440:
            scroll_to_submit(page)
            assert page.locator('#discovery-results').evaluate('(node)=>node.getBoundingClientRect().top') < 0
        page.locator('#intent-name').fill('导师21')
        scroll_to_submit(page)
        page.locator('#apply-criteria').click()
        expect(page.locator('[data-candidate="bit-cs-fixture-21"]')).to_be_visible()
        expect(page.locator('#more-candidates')).to_be_hidden()
        expect(page.locator('#discovery-results')).to_be_focused()
        assert page.evaluate(
            "document.querySelector('#discovery-count').getBoundingClientRect().top >= "
            "document.querySelector('.site-header').getBoundingClientRect().bottom")

        page.locator('#intent-name').fill('没有结果')
        scroll_to_submit(page)
        page.locator('#apply-criteria').click()
        expect(page.get_by_role('heading', name='当前条件下暂无可联系候选')).to_be_visible()
        expect(page.locator('#discovery-results')).to_be_focused()

        page.locator('#intent-name').fill('超' * 101)
        scroll_to_submit(page)
        page.locator('#apply-criteria').click()
        expect(page.locator('#discovery-message')).to_contain_text('姓名最多100字')
        expect(page.locator('#discovery-message')).to_be_focused()
        assert page.evaluate(
            "document.querySelector('#discovery-message').getBoundingClientRect().top >= "
            "document.querySelector('.site-header').getBoundingClientRect().bottom")
        expect(page.get_by_role('heading', name='当前条件下暂无可联系候选')).to_be_visible()
        assert len(queries) == 3
        browser.close()


def test_directory_header_links_keep_intent_through_filter_paging_and_return(directory):
    target = dict(school='bit', dept='cs', year='2028', degree='master', route='recommend',
                  track='ordinary', program='0812|计算机科学与技术')
    expected = {key: [value] for key, value in target.items()}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 800})
        queries = []
        intercept_candidates(page, directory, queries)
        page.goto(directory + '/discovery.html?' + urlencode(dict(target, qualifications='phd')))
        expect(page.locator('[data-candidate]')).to_have_count(4)
        nav = page.get_by_role('navigation', name='主导航')
        policy = nav.get_by_role('link', name='学校要求')
        applications = nav.get_by_role('link', name='我的申请')
        assert href_query(policy) == href_query(applications) == expected
        assert page.locator('#application-context-link').get_attribute('href') == applications.get_attribute('href')
        assert queries[0]['qualifications'] == ['phd'] and 'degree' not in queries[0]

        page.locator('#more-candidates').click()
        page.locator('[data-candidate="bit-cs-fixture-5"] h2 a').click()
        expect(page.get_by_role('heading', name='导师资料')).to_be_visible()
        page.go_back(wait_until='domcontentloaded')
        expect(page.locator('[data-candidate="bit-cs-fixture-5"]')).to_be_visible()
        expect(page.locator('[data-candidate]')).to_have_count(4)
        assert candidate_ids(page) == [f'bit-cs-fixture-{i}' for i in range(5, 9)]
        assert href_query(policy) == expected

        page.locator('#clear-unit-context').click()
        expect(page.locator('#unit-context')).to_be_hidden()
        expect(page.locator('#apply-criteria')).to_be_enabled()
        assert href_query(policy) == {key: expected[key] for key in ('school', 'year', 'degree', 'route')}
        assert href_query(applications) == expected
        applications.click()
        expect(page.get_by_role('heading', name='登录后继续申请准备')).to_be_visible()
        next_url = urlsplit(parse_qs(urlsplit(page.url).query)['next'][0])
        assert next_url.path == '/applications.html' and parse_qs(next_url.query) == expected

        page.goto(directory + '/discovery.html?school=bit&track=ordinary&qualifications=phd')
        expect(page.locator('[data-candidate]')).to_have_count(4)
        assert href_query(policy) == href_query(applications) == {'school': ['bit'], 'track': ['ordinary']}

        page.goto(directory + '/discovery.html?qualifications=phd&project=existing-project')
        expect(page.locator('[data-candidate]')).to_have_count(4)
        assert policy.get_attribute('href') == 'admissions.html'
        assert href_query(applications) == {'project': ['existing-project']}
        browser.close()


def test_four_candidate_batches_replace_cards_and_wrap_on_mobile(directory):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 320, 'height': 780})
        queries, errors = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        intercept_candidates(page, directory, queries)
        page.goto(directory + '/discovery.html')
        cards = page.locator('[data-candidate]')
        more = page.get_by_role('button', name='换一批')
        expect(cards).to_have_count(4)
        assert more.bounding_box()['y'] < cards.first.bounding_box()['y']
        assert page.evaluate('document.documentElement.scrollWidth === innerWidth')
        cards.first.get_by_role('button', name='加入对比').click()
        expect(page.locator('#compare-count')).to_contain_text('已选 1 位')

        for offset in (4, 8, 12, 16, 20, 3):
            more.click()
            expect(cards.first).to_have_attribute('data-candidate', f'bit-cs-fixture-{offset + 1}')
            expect(cards).to_have_count(4)
            assert candidate_ids(page) == [f'bit-cs-fixture-{(offset + i) % 21 + 1}' for i in range(4)]
            expect(page.locator('#compare-count')).to_contain_text('已选 1 位')
            if offset == 20:
                expect(page.locator('[data-compare="bit-cs-fixture-1"]')).to_have_attribute('aria-pressed', 'true')

        assert [int(q['offset'][0]) for q in queries] == [0, 4, 8, 12, 16, 20, 0, 3]
        assert all(q['limit'] == ['4'] and q['include_missing_email'] == ['0'] for q in queries)
        assert len({q['seed'][0] for q in queries}) == 1
        page.locator('#intent-name').fill('四位导师')
        page.locator('#apply-criteria').click()
        expect(page.locator('#discovery-count')).to_have_text('4 位候选 · 当前显示 4 位')
        expect(more).to_be_hidden()
        assert not errors
        browser.close()


def test_failed_batch_retries_with_applied_criteria_and_handles_new_revision(directory):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        queries, pending = [], []
        updated = False
        intercept_candidates(page, directory, queries)

        def hold_next(route):
            query = parse_qs(urlsplit(route.request.url).query)
            if query['offset'] == ['4']:
                pending.append(route)
            elif updated and 'name' not in query:
                queries.append(query)
                route.fulfill(json=dict(version=2, rows=[dict(p=row) for row in profiles()[:4]], total=21,
                                        missing_email=0, revision='updated'))
            else:
                route.fallback()

        page.route('**/api/mentor-candidates?*', hold_next)
        page.goto(directory + '/discovery.html')
        expect(page.locator('[data-candidate]')).to_have_count(4)
        first = candidate_ids(page)
        page.locator('#intent-name').fill('导师21')
        more = page.get_by_role('button', name='换一批')
        status = page.locator('#batch-status')
        with page.expect_request('**/api/mentor-candidates?*'):
            more.click()
        expect(status).to_have_text('正在换一批…')
        expect(more).to_be_disabled()
        assert candidate_ids(page) == first
        pending[0].fulfill(status=503, json={'error': 'offline'})
        expect(status).to_contain_text('已保留当前结果')
        expect(more).to_be_enabled()
        assert candidate_ids(page) == first

        with page.expect_request('**/api/mentor-candidates?*'):
            more.click()
        assert all('name' not in parse_qs(urlsplit(route.request.url).query) for route in pending)
        assert all(parse_qs(urlsplit(route.request.url).query)['offset'] == ['4'] for route in pending)
        updated = True
        pending[1].fulfill(json=dict(version=2, rows=[dict(p=row) for row in profiles()[4:8]], total=21,
                                     missing_email=0, revision='updated'))
        expect(status).to_contain_text('公开资料已更新')
        assert candidate_ids(page) == first
        assert queries[-1]['offset'] == ['0'] and 'name' not in queries[-1]
        expect(page.locator('#criteria-dirty')).to_be_visible()
        page.locator('#apply-criteria').click()
        expect(page.locator('[data-candidate="bit-cs-fixture-21"]')).to_be_visible()
        expect(more).to_be_hidden()
        browser.close()


def test_late_batch_cannot_replace_new_filter_results(directory):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        intercept_candidates(page, directory, [])
        pending = []

        def hold_next(route):
            if parse_qs(urlsplit(route.request.url).query)['offset'] == ['4']:
                pending.append(route)
            else:
                route.fallback()

        page.route('**/api/mentor-candidates?*', hold_next)
        page.goto(directory + '/discovery.html')
        more = page.get_by_role('button', name='换一批')
        with page.expect_request('**/api/mentor-candidates?*'):
            more.click()
        page.locator('#intent-name').fill('导师21')
        page.locator('#apply-criteria').click()
        expect(page.locator('[data-candidate="bit-cs-fixture-21"]')).to_be_visible()
        with page.expect_response(lambda response: response.url == pending[0].request.url) as late:
            pending[0].fulfill(json=dict(version=2, rows=[dict(p=row) for row in profiles()[4:8]], total=21,
                                         missing_email=0, revision='fixture'))
        late.value.finished()
        expect(page.locator('#batch-status')).to_be_empty()
        assert candidate_ids(page) == ['bit-cs-fixture-21']
        expect(more).to_be_hidden()
        browser.close()


def test_public_api_batch_uses_full_directory_ranking_and_excludes_missing_email(directory):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(directory + '/discovery.html')
        expect(page.locator('#discovery-count')).to_have_text('21 位候选 · 当前显示 4 位')
        first = candidate_ids(page)
        assert set(first) == {f'bit-cs-fixture-{i}' for i in range(1, 5)}
        more = page.get_by_role('button', name='换一批')
        more.press('Enter')
        expect(page.locator('#batch-status')).to_have_text('已显示新一批导师。')
        expect(more).to_be_focused()
        second = candidate_ids(page)
        assert len(second) == 4 and set(first).isdisjoint(second)
        expect(page.locator('.public-email a')).to_have_count(4)
        expect(page.locator('#discovery-message')).to_be_empty()
        page.reload()
        expect(page.locator('[data-candidate]')).to_have_count(4)
        assert candidate_ids(page) == second
        browser.close()


def test_browser_fallback_switches_four_and_recovers_same_batch_after_reload(directory):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.route('**/api/mentor-candidates?*', lambda route: route.fulfill(status=503, json={'error': 'offline'}))
        page.goto(directory + '/discovery.html')
        candidates = page.locator('[data-candidate]')
        expect(candidates).to_have_count(4)
        first = candidate_ids(page)
        more = page.get_by_role('button', name='换一批')
        more.click()
        second = candidate_ids(page)
        assert len(second) == 4 and set(first).isdisjoint(second)
        expect(page.locator('#discovery-count')).to_have_text('21 位候选 · 当前显示 4 位')
        page.reload()
        expect(candidates).to_have_count(4)
        assert candidate_ids(page) == second
        expect(page.locator('.public-email a')).to_have_count(4)
        browser.close()


def test_card_continues_matched_project_and_preserves_existing_bookmark(directory):
    target = dict(school='bit', dept='cs', year='2028', degree='master', route='recommend', project='existing-project')
    original_page = 'discovery.html?' + urlencode(target)
    original_bookmark = 'p/bit-cs-fixture-1.html?' + urlencode(dict(
        year='2028', degree='master', route='recommend', school='bit', dept='cs', discovery_return=original_page))
    bookmarks = [dict(id='bookmark-fixture', kind='mentor', title='导师1', url=original_bookmark, created_at='2026-01-01')]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        requests = []
        intercept_candidates(page, directory, requests)
        page.route('**/api/auth/me', lambda route: route.fulfill(json=dict(authenticated=True)))
        page.route('**/api/library', lambda route: route.fulfill(json=dict(
            revision=1, library=dict(version=1, targets=[], bookmarks=bookmarks, todos=[]))))
        page.goto(directory + '/' + original_page)
        card = page.locator('[data-candidate="bit-cs-fixture-1"]')
        expect(card.get_by_role('button', name='已收藏')).to_be_visible()
        detail, contact = (href_query(card.get_by_role('link', name=label)) for label in ('查看资料', '准备联系'))
        assert detail['project'] == contact['project'] == ['existing-project']
        assert detail['discovery_return'] == contact['discovery_return'] == [original_page]
        assert contact['mentor'] == ['bit-cs-fixture-1']
        assert 'project' not in requests[0]

        page.get_by_role('button', name='换一批').click()
        expect(card).to_have_count(0)
        page.reload()
        expect(page.locator('[data-candidate="bit-cs-fixture-5"]')).to_be_visible()

        page.locator('#school-options input[value="bit"]').uncheck()
        page.locator('#school-options input[value="zju"]').check()
        page.locator('#apply-criteria').click()
        other = page.locator('[data-candidate="zju-cs-fixture-1"]')
        expect(other).to_be_visible()
        for link in ('查看资料', '准备联系'):
            params = href_query(other.get_by_role('link', name=link))
            assert 'project' not in params and params['discovery_return'] == [original_page]
        assert 'project' not in requests[-1]
        browser.close()

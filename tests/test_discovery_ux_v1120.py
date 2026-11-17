"""Keep directory feedback visible and preserve explicit application context."""
import json
import shutil
import threading
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts import build_site, serve_public


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
    env = build_site.template_environment()
    (site / 'account.html').write_text(env.get_template('account.html.j2').render(), encoding='utf-8')
    for name in ('account-session.js', 'cloud-library.js', 'account.js', 'ui.css'):
        shutil.copyfile(build_site.ROOT / 'site' / name, site / name)
    (site / 'p').mkdir()
    (site / 'p' / 'bit-cs-fixture-21.html').write_text('<h1>导师资料</h1>', encoding='utf-8')
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
    profiles = [
        dict(page=f'bit-cs-fixture-{i}', name=f'导师{i}', school='bit', dept='cs',
             school_name='北京理工大学', dept_name='计算机学院', supervisor='硕导、博导',
             email=f'teacher{i}@bit.edu.cn', email_source='https://cs.bit.edu.cn/teachers')
        for i in range(1, 22)
    ]

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
            rows = profiles[-1:]
        else:
            rows = profiles
        offset = int(query['offset'][0])
        return route.fulfill(json=dict(version=2, total=len(rows), rows=[
            dict(p=row) for row in rows[offset:offset + 20]], missing_email=0, revision='fixture'))

    page.route('**/*', handle)


def href_query(link):
    return parse_qs(urlsplit(link.get_attribute('href')).query)


def scroll_to_submit(page):
    page.locator('#apply-criteria').evaluate(
        '(button)=>scrollTo(0, scrollY+button.getBoundingClientRect().top-160)')


@pytest.mark.parametrize('width', [1440, 390])
def test_explicit_filter_submit_reveals_results_empty_state_and_error(directory, width):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 560})
        queries = []
        intercept_candidates(page, directory, queries)
        page.goto(directory + '/discovery.html')
        expect(page.locator('[data-candidate]')).to_have_count(20)
        if width == 1440:
            scroll_to_submit(page)
            assert page.locator('#discovery-results').evaluate('(node)=>node.getBoundingClientRect().top') < 0
        page.locator('#intent-name').fill('导师21')
        scroll_to_submit(page)
        page.locator('#apply-criteria').click()
        expect(page.locator('[data-candidate="bit-cs-fixture-21"]')).to_be_visible()
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
        expect(page.locator('[data-candidate]')).to_have_count(20)
        nav = page.get_by_role('navigation', name='主导航')
        policy = nav.get_by_role('link', name='学校要求')
        applications = nav.get_by_role('link', name='我的申请')
        assert href_query(policy) == href_query(applications) == expected
        assert page.locator('#application-context-link').get_attribute('href') == applications.get_attribute('href')
        assert queries[0]['qualifications'] == ['phd'] and 'degree' not in queries[0]

        page.locator('#more-candidates').click()
        expect(page.locator('[data-candidate]')).to_have_count(21)
        page.locator('[data-candidate="bit-cs-fixture-21"] h2 a').click()
        expect(page.get_by_role('heading', name='导师资料')).to_be_visible()
        page.go_back(wait_until='domcontentloaded')
        expect(page.locator('[data-candidate]')).to_have_count(21)
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
        expect(page.locator('[data-candidate]')).to_have_count(20)
        assert href_query(policy) == href_query(applications) == {'school': ['bit'], 'track': ['ordinary']}

        page.goto(directory + '/discovery.html?qualifications=phd&project=existing-project')
        expect(page.locator('[data-candidate]')).to_have_count(20)
        assert policy.get_attribute('href') == 'admissions.html'
        assert href_query(applications) == {'project': ['existing-project']}
        browser.close()

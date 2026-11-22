"""Browser acceptance for the first-screen notice controls and scoped links."""
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from bs4 import BeautifulSoup
from playwright.sync_api import expect, sync_playwright

from crawler.notice_util import annotate_notices
from scripts import build_site


ORIGIN = 'http://notices-test.invalid'
LISTING = 'https://sai.xidian.edu.cn/tzgg.htm'
XIDIAN = '西安电子科技大学 · 人工智能学院'
PLAN = 'https://sai.xidian.edu.cn/info/1106/32502.htm'
GENERAL = 'https://sai.xidian.edu.cn/info/1106/99999.htm'
TSINGHUA = 'https://yz.tsinghua.edu.cn/zsxx/bszs/ptzk.htm'
TSINGHUA_CS = 'https://www.cs.tsinghua.edu.cn/zszp/zsxx.htm'


def notice(id, title, url, source, school='xidian', dept='ai', unit=XIDIAN):
    return dict(id=id, title=title, url=url, source=source, school=school, dept=dept, unit=unit,
                publication_date='2026-11-03', fetched_at='2026-11-23', deadline=None,
                reviewed=False, seen_in_latest_list=True, title_years=[])


ROWS = [
    notice('2028', '人工智能学院2028届优秀本科毕业生推荐免试攻读硕士学位研究生工作实施方案', PLAN, LISTING),
    notice('2029', '人工智能学院2029届优秀本科毕业生推荐免试攻读硕士学位研究生工作实施方案',
           'https://sai.xidian.edu.cn/info/1106/32522.htm', LISTING),
    notice('general', '人工智能学院2027年硕士研究生招生简章', GENERAL, LISTING),
    notice('tsinghua-root', '清华大学2027年普通招考博士研究生冬季报考须知',
           'https://yz.tsinghua.edu.cn/info/1012/3296.htm', TSINGHUA, 'tsinghua', '', '清华大学研究生招生网'),
    notice('tsinghua-cs', '清华大学计算机系2027年硕士研究生招生简章',
           'https://www.cs.tsinghua.edu.cn/info/1048/9999.htm', TSINGHUA_CS, 'tsinghua', 'cs', '清华大学计算机系'),
]
SOURCES = {
    'xidian-ai-notices': dict(url=LISTING, scope='xidian/ai', name=XIDIAN),
    'tsinghua-doctoral': dict(url=TSINGHUA, scope='tsinghua/', name='普通博士招考'),
    'tsinghua/cs': dict(url=TSINGHUA_CS, error='HTTP 503'),
}
CATALOG = {'units': [
    dict(school='xidian', dept='cs', school_name='西安电子科技大学', dept_name='计算机科学与技术学院'),
    dict(school='tsinghua', dept='cs', school_name='清华大学', dept_name='计算机系'),
]}


@pytest.fixture
def notices_browser():
    document = build_site.template_environment().get_template('notices.html.j2').render(
        notices=annotate_notices(ROWS, day='2026-11-23'), sources=SOURCES)
    with sync_playwright() as api:
        browser = api.chromium.launch()

        def notice_page(width=390, height=844, rendered=document):
            page = browser.new_page(viewport=dict(width=width, height=height))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def public_read(route):
                request = route.request
                assert request.method == 'GET' and request.url.startswith(ORIGIN + '/')
                name = urlsplit(request.url).path
                if name == '/notices.html':
                    return route.fulfill(content_type='text/html; charset=utf-8', body=rendered)
                if name == '/api/auth/me':
                    return route.fulfill(json={'authenticated': False, 'user': None, 'enabled': True})
                if name == '/school-catalog.js':
                    return route.fulfill(content_type='text/javascript',
                                         body='window.SCHOOL_CATALOG = ' + json.dumps(CATALOG))
                file = build_site.SITE / name.removeprefix('/')
                if file.is_file() and file.suffix in ('.js', '.css'):
                    mime = 'text/css' if file.suffix == '.css' else 'text/javascript'
                    return route.fulfill(content_type=mime, body=file.read_text(encoding='utf-8'))
                return route.abort()

            page.route('**/*', public_read)
            return page, errors

        yield notice_page
        browser.close()


def query(url):
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


def open_notices(page, **params):
    response = page.goto(ORIGIN + '/notices.html?' + urlencode(params))
    assert response.status == 200
    expect(page.locator('#count')).to_contain_text('条通知')


def card(page, id):
    return page.locator(f'article[data-notice-id="{id}"]')


@pytest.mark.parametrize('width,height', [(390, 844), (1440, 900)])
def test_primary_controls_and_first_official_title_fit_initial_viewport(notices_browser, width, height):
    page, errors = notices_browser(width, height)
    open_notices(page)
    for scoped in (False, True):
        if scoped:
            open_notices(page, school='xidian', dept='ai', notice_cycle='preparation',
                         notice_route='recommend', notice_graduation_year='2028')
            expect(page.locator('#school option:checked')).to_have_text(XIDIAN)
            expect(page.locator('#notice-graduation-year')).to_have_value('2028')
            expect(page.locator('#notice-filter-panel summary')).to_contain_text('推免')
            expect(card(page, '2029')).to_be_hidden()
        for id in ('school', 'notice-graduation-year', 'search'):
            expect(page.locator('#' + id)).to_be_visible()
        for id in ('notice-filter-panel', 'notice-help'):
            assert not page.locator('#' + id).evaluate('element => element.open')
        expect(page.locator('[data-notice-cycle]')).to_have_count(4)
        expect(page.get_by_role('navigation', name='主导航').get_by_role('link', name='学校要求')).to_be_visible()
        title = card(page, '2028').locator('a.title')
        expect(title).to_have_attribute('href', PLAN)
        box = title.bounding_box()
        assert box and box['y'] >= 0 and box['y'] + box['height'] <= height, (width, scoped, box)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        if width == 390:
            school, cohort, search = (page.locator('#' + id).bounding_box()
                                      for id in ('school', 'notice-graduation-year', 'search'))
            assert school['width'] > 300 and school['y'] < cohort['y']
            assert abs(cohort['y'] - search['y']) <= 4 and cohort['x'] < search['x']
    assert not errors


def test_scoped_reload_sources_and_original_application_link(notices_browser):
    page, errors = notices_browser()
    intent = dict(school='xidian', dept='ai', year='2027', degree='phd', route='assessment',
                  track='special', program='081200|计算机科学与技术', group='ai')
    open_notices(page, **intent, notice_cycle='preparation', notice_route='recommend',
                 notice_admission_year='unknown', notice_graduation_year='2028', notice_activity_year='unknown')
    assert page.reload().status == 200
    expect(page.locator('#notice-graduation-year')).to_have_value('2028')
    expect(page.locator('#notice-filter-panel summary')).to_contain_text('推免')
    assert not page.locator('#notice-filter-panel').evaluate('element => element.open')
    page.locator('#notice-filter-panel summary').click()
    for id in ('cycle', 'route', 'admission-year', 'activity-year'):
        expect(page.locator('#notice-' + id)).to_be_visible()
    assert query(page.locator('#notice-policy-link').get_attribute('href')) == intent
    page.locator('#notice-help > summary').click()
    expect(page.locator('#notice-policy-link')).to_be_visible()
    expect(page.locator(f'#current-source a[href="{LISTING}"]')).to_be_visible()
    expect(card(page, '2028')).to_be_visible()
    expect(card(page, '2028').locator('a.title')).to_have_attribute('href', PLAN)
    expect(card(page, '2028').locator(f'a[href="{LISTING}"]')).to_have_count(1)
    assert not errors


def test_explicit_school_level_and_all_departments_are_distinct(notices_browser):
    page, errors = notices_browser()
    open_notices(page, school='tsinghua', dept='', notice_cycle='all')
    assert page.reload().status == 200
    expect(page.locator('#school')).to_have_value('tsinghua/')
    assert query(page.url)['dept'] == ''
    expect(card(page, 'tsinghua-root')).to_be_visible()
    expect(card(page, 'tsinghua-cs')).to_be_hidden()
    expect(page.locator('#notice-help-summary')).not_to_contain_text('来源更新失败')
    page.locator('#notice-help > summary').click()
    expect(page.locator('#current-source a')).to_have_count(1)
    open_notices(page, school='tsinghua', notice_cycle='all')
    expect(page.locator('#school')).to_have_value('tsinghua')
    assert 'dept' not in query(page.url)
    expect(card(page, 'tsinghua-root')).to_be_visible()
    expect(card(page, 'tsinghua-cs')).to_be_visible()
    expect(page.locator('#notice-help-summary')).to_contain_text('1 个来源更新失败')
    page.locator('#notice-help > summary').click()
    expect(page.locator('#current-source a')).to_have_count(2)
    expect(page.locator('[data-source-error="tsinghua/cs"]')).to_be_visible()
    assert not errors


def test_search_empty_state_still_links_the_official_column(notices_browser):
    page, errors = notices_browser()
    open_notices(page, school='xidian', dept='ai', q='无此通知')
    expect(page.locator('#notice-empty')).to_be_visible()
    expect(page.locator(f'#empty-source a[href="{LISTING}"]')).to_be_visible()
    page.locator('#clear-search').click()
    expect(page.locator('#search')).to_be_focused()
    expect(card(page, '2028')).to_be_visible()
    assert 'q' not in query(page.url)
    assert not errors


@pytest.mark.parametrize('admission', ['', 'unknown', '2027'])
def test_general_policy_navigation_drops_unrelated_years(notices_browser, admission):
    page, errors = notices_browser()
    open_notices(page, school='xidian', dept='ai', notice_cycle='active', notice_route='recommend',
                 notice_admission_year=admission, notice_graduation_year='2028', notice_activity_year='unknown')
    expected_admission = admission if admission.isdigit() else ''
    if not expected_admission:
        expect(card(page, '2028')).to_be_visible()
    action = page.locator('#notice-general-policy')
    expect(action).to_have_text('查看通用政策')
    action.click()
    expect(card(page, 'general')).to_be_visible()
    assert page.locator('#notice-graduation-year').input_value() == ''
    assert page.locator('#notice-activity-year').input_value() == ''
    assert page.locator('#notice-admission-year').input_value() == expected_admission
    actual = query(page.url)
    assert actual['notice_route'] == 'unknown'
    assert actual.get('notice_admission_year', '') == expected_admission
    assert 'notice_graduation_year' not in actual and 'notice_activity_year' not in actual
    feedback = page.locator('#notice-action-status[role="status"]')
    expect(feedback).to_be_visible()
    expect(feedback).to_contain_text(re.compile(r'通用政策.*清除.*毕业届别.*活动年'))
    if not expected_admission:
        expect(feedback).to_contain_text(re.compile(r'入学年.*(?:待核验|未指定|未明确)'))
    else:
        expect(feedback).to_contain_text(re.compile(r'保留.*2027.*入学'))
    if admission == 'unknown':
        expect(feedback).to_contain_text(re.compile(r'清除[^。]*入学年'))
    assert not errors


def test_normal_renderer_keeps_inventory_and_loads_filters_without_assets(notices_browser, tmp_path):
    literal = '资料原文含 <说明>、</script> 和 &'
    rows = annotate_notices(ROWS + [notice('safe-text', literal, GENERAL + '?safe=1', LISTING)], day='2026-11-23')
    (tmp_path / 'school-catalog.js').write_text(
        'window.SCHOOL_CATALOG = ' + json.dumps(CATALOG) + ';window.noticeLiteral = "</script>";',
        encoding='utf-8')
    rendered = build_site.render_notices_page(rows, SOURCES, site=tmp_path)
    soup = BeautifulSoup(rendered, 'html.parser')
    assert not soup.select('script[src],link[rel=stylesheet]')
    assert json.loads(soup.select_one('#notice-data').string) == rows
    assert [article['data-notice-id'] for article in soup.select('article[data-notice-id]')] == [row['id'] for row in rows]
    assert soup.select_one('article[data-notice-id="safe-text"] .title').get_text() == literal
    page, errors = notices_browser(rendered=rendered)
    requested_assets = []
    page.on('request', lambda request: requested_assets.append(request.resource_type))
    open_notices(page, school='xidian', dept='ai', notice_cycle='preparation', notice_graduation_year='2028')
    expect(card(page, '2028')).to_be_visible()
    expect(card(page, '2029')).to_be_hidden()
    assert page.evaluate('window.noticeLiteral') == '</script>'
    assert not set(requested_assets) & {'script', 'stylesheet'}
    assert not errors

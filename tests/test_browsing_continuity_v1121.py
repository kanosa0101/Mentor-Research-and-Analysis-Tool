"""Browser journeys preserve intent without treating cohort as admission year."""
import copy
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts import build_site


ORIGIN = 'http://mentor-test.invalid'


@pytest.fixture
def browsing_pages():
    pages = {
        '/start.html': build_site.render_start_page(),
        '/admissions.html': build_site.render_admissions_page(),
        '/opportunities.html': build_site.render_opportunities_page(),
    }
    admissions = (build_site.SITE / 'admissions-data.js').read_text(encoding='utf-8')
    _, school_assets = build_site.admissions_entry_assets(json.loads(admissions.split('=', 1)[1].strip().removesuffix(';')))
    source = (build_site.SITE / 'opportunities-data.js').read_text(encoding='utf-8')
    catalog = json.loads(source.split('=', 1)[1].strip().removesuffix(';'))
    row = copy.deepcopy(next(r for r in catalog['opportunities']
                             if r['content_classification']['scope'] == 'institutional_activity'))
    row.update(id='fixture-history', title='视觉测试营', school_id='tsinghua', school_name='清华大学',
               graduation_year=2020, cycle='historical', registration_start='2019-01-01',
               deadline='2019-02-01', event_start='', event_end='', source_state='verified',
               research_directions=[], source_url='https://example.edu/fixture')
    row['content_classification']['source_url'] = row['source_url']
    catalog.update(opportunities=[row], other_contents=[], mode='public')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors, writes = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route_request(route):
            request = route.request
            assert request.url.startswith(ORIGIN + '/')
            if request.method != 'GET':
                writes.append(request.url)
                return route.abort()
            path = urlsplit(request.url).path
            if path in pages:
                return route.fulfill(content_type='text/html; charset=utf-8', body=pages[path])
            if path.startswith('/admissions/') and path.endswith('.json'):
                return route.fulfill(content_type='application/json', body=school_assets[path.rsplit('/', 1)[1][:-5]])
            if path == '/api/opportunities':
                return route.fulfill(json=catalog)
            if path.startswith('/api/'):
                return route.fulfill(json={'authenticated': False, 'user': None, 'enabled': False, 'events': []})
            return route.abort()

        page.route('**/*', route_request)
        yield page
        assert errors == writes == []
        browser.close()


def query(link):
    return parse_qs(urlsplit(link.get_attribute('href')).query)


def test_research_interest_survives_the_school_requirements_detour(browsing_pages):
    page = browsing_pages
    page.goto(ORIGIN + '/start.html')
    page.wait_for_function('window.START_READY')
    page.locator('input[name=path][value=exam]').check()
    page.locator('#target-year').fill('2028')
    page.locator('details:has(#start-school-options) > summary').click()
    page.locator('#start-school-search').fill('清华')
    page.locator('#start-school-options input[value=tsinghua]').check()
    page.locator('#target-interest').fill('视觉,安全')
    page.locator('#target-interest').blur()
    school_link = page.locator('#target-entries a[href^="admissions.html"]').first
    assert query(school_link)['topics'] == ['视觉,安全']
    school_link.click()
    page.wait_for_function('window.ADMISSIONS_READY')
    page.locator('#policy-dept').select_option('cs')
    page.locator('#policy-target-more > summary').click()
    page.locator('#policy-track').select_option('ordinary')
    assert parse_qs(urlsplit(page.url).query)['topics'] == ['视觉,安全']
    page.reload()
    page.wait_for_function('window.ADMISSIONS_READY')
    values = query(page.locator('#checklist-mentors'))
    assert {k: values[k] for k in ('school', 'dept', 'year', 'degree', 'route', 'track', 'topics')} == {
        'school': ['tsinghua'], 'dept': ['cs'], 'year': ['2028'], 'degree': ['master'],
        'route': ['exam'], 'track': ['ordinary'], 'topics': ['视觉,安全'],
    }


def test_history_preserves_school_interest_and_restores_filtered_login_return(browsing_pages):
    page = browsing_pages
    page.goto(ORIGIN + '/opportunities.html?' + urlencode({'school': '清华大学', 'year': '2028', 'query': '视觉'}))
    page.wait_for_function('catalogLoaded&&opportunityModeReady')
    expect(page.locator('.opportunity-card')).to_have_count(0)
    assert query(page.get_by_role('link', name='查官方招生通知 →'))['school'] == ['tsinghua']
    for target in ('discovery', 'admissions'):
        values = query(page.locator(f'.site-header nav a[href^="{target}.html"]'))
        assert values == {'school': ['tsinghua']}
    page.locator('#opportunity-history').click()
    expect(page.locator('[data-opportunity=fixture-history]')).to_have_count(1)
    values = parse_qs(urlsplit(page.url).query)
    assert values == {'school': ['清华大学'], 'query': ['视觉'], 'state': ['closed']}
    page.reload()
    page.wait_for_function('catalogLoaded&&opportunityModeReady')
    expect(page.locator('#opportunity-school')).to_have_value('清华大学')
    expect(page.locator('#opportunity-search')).to_have_value('视觉')
    expect(page.locator('#opportunity-state')).to_have_value('closed')
    login_next = query(page.get_by_role('link', name='登录后加入申请'))['next'][0]
    next_values = parse_qs(urlsplit(login_next).query)
    assert next_values == dict(values, id=['fixture-history'])
    page.goto(ORIGIN + login_next)
    page.wait_for_function('catalogLoaded&&opportunityModeReady')
    assert query(page.get_by_role('link', name='← 返回筛选结果')) == values
    page.locator('#opportunity-search').fill('无匹配项')
    expect(page.locator('.opportunity-card')).to_have_count(0)
    assert 'id' not in parse_qs(urlsplit(page.url).query)


def test_explicit_study_target_survives_the_activity_detour(browsing_pages):
    page = browsing_pages
    page.goto(ORIGIN + '/start.html')
    page.wait_for_function('window.START_READY')
    page.locator('input[name=path][value=exam]').check()
    page.locator('#target-year').fill('2028')
    page.locator('details:has(#start-school-options) > summary').click()
    page.locator('#start-school-search').fill('清华')
    page.locator('#start-school-options input[value=tsinghua]').check()
    page.locator('#target-interest').fill('视觉,安全')
    page.locator('#target-interest').blur()
    page.locator('#target-entries a[href^="opportunities.html"]').first.click()
    page.wait_for_function('catalogLoaded&&opportunityModeReady')
    for target in ('discovery', 'admissions'):
        assert query(page.locator(f'.site-header nav a[href^="{target}.html"]')) == {
            'school': ['tsinghua'], 'topics': ['视觉,安全'], 'year': ['2028'],
            'degree': ['master'], 'route': ['exam'],
        }
    page.locator('#opportunity-search').fill('某活动名称')
    assert query(page.locator('.site-header nav a[href^="discovery.html"]'))['topics'] == ['视觉,安全']
    assert query(page.locator('.site-header a[href^="notices.html"]')) == {
        'school': ['tsinghua'], 'notice_admission_year': ['2028'], 'notice_route': ['exam'],
        'notice_cycle': ['current'],
    }


def test_unknown_activity_retains_only_the_filtered_list_return(browsing_pages):
    page = browsing_pages
    values = {'school': '清华大学', 'year': '2028', 'query': '视觉', 'state': 'current'}
    page.goto(ORIGIN + '/opportunities.html?' + urlencode(dict(values, id='unlisted')))
    page.wait_for_function('catalogLoaded&&opportunityModeReady')
    expect(page.locator('.opportunity-empty')).to_contain_text('当前目录未找到这条记录')
    assert query(page.get_by_role('link', name='← 返回筛选结果')) == {k: [v] for k, v in values.items()}
    expect(page.locator('#opportunity-list a[href="opportunities.html"]')).to_have_count(0)

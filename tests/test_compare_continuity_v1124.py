"""A slow comparison read must not break an existing application journey."""
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from bs4 import BeautifulSoup
from playwright.sync_api import expect, sync_playwright

from scripts import build_site


ORIGIN = 'http://mentor-test.invalid'
MENTORS = [
    dict(page='bit-cs-fixture', name='同院导师', school='bit', dept='cs', school_name='北京理工大学',
         dept_name='计算机学院', email='fixture@example.invalid', research_direction_raw='机器学习',
         title='教授', supervisor='博导', provenance={}),
    dict(page='zju-cs-fixture', name='另一院系导师', school='zju', dept='cs', school_name='浙江大学',
         dept_name='计算机学院', email='other@example.invalid', research_direction_raw='计算机视觉',
         title='副教授', supervisor='硕导', provenance={}),
]
GOAL = dict(school='bit', dept='cs', year='2028', degree='master', route='recommend',
            track='ordinary', program='081200', project='existing-project')
RETURN = 'discovery.html?' + urlencode(dict(GOAL, topics='机器学习'))


@pytest.fixture
def comparison():
    env = build_site.template_environment()
    pages = {'/compare.html': env.get_template('compare.html.j2').render()}
    pages.update({f'/p/{p["page"]}.html': env.get_template('detail.html.j2').render(p=p) for p in MENTORS})
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        page.add_init_script('if(localStorage.getItem("compare_sel")===null)localStorage.setItem("compare_sel",'+json.dumps(json.dumps([p['page'] for p in MENTORS]))+')')
        state = dict(mode='ok', attempts=0, requests=[], errors=[])
        page.on('pageerror', lambda error: state['errors'].append(str(error)))

        def route_request(route):
            request = route.request
            assert request.method == 'GET' and request.url.startswith(ORIGIN + '/')
            path = urlsplit(request.url).path
            state['requests'].append(path)
            if path == '/api/mentors':
                state['attempts'] += 1
                if state['mode'] == 'pending':
                    state['held'] = route
                    return
                if state['mode'] == 'error':
                    return route.fulfill(status=503, json={'error': 'unavailable'})
                if state['mode'] == 'invalid':
                    return route.fulfill(json={'mentors': None})
                if state['mode'] == 'removed':
                    return route.fulfill(json={'mentors': []})
                return route.fulfill(json={'mentors': MENTORS})
            if path in pages:
                return route.fulfill(content_type='text/html; charset=utf-8', body=pages[path])
            if path.startswith('/api/'):
                return route.fulfill(json={'authenticated': False, 'user': None, 'enabled': False})
            file = build_site.SITE / path.removeprefix('/')
            if file.name in {'ui.css', 'account-session.js', 'cloud-library.js'}:
                return route.fulfill(content_type='text/css' if file.suffix == '.css' else 'text/javascript', body=file.read_text(encoding='utf-8'))
            return route.abort()

        page.route('**/*', route_request)
        yield page, state
        assert not state['errors']
        browser.close()


def query(link):
    return {key: values[0] for key, values in parse_qs(urlsplit(link.get_attribute('href')).query).items()}


@pytest.mark.parametrize('mode', ['pending', 'error', 'invalid'])
def test_read_failure_keeps_selection_and_return_and_recovers_without_full_catalog(comparison, mode):
    page, state = comparison
    state['mode'] = mode
    page.goto(ORIGIN + '/compare.html?' + urlencode(dict(GOAL, discovery_return=RETURN)), wait_until='domcontentloaded')
    expect(page.locator('.context-actions a').first).to_have_attribute('href', RETURN)
    expect(page.locator('#compare-retry')).to_be_visible(timeout=11000)
    expect(page.locator('#compare-status')).to_contain_text('已保留')
    assert page.evaluate('JSON.parse(localStorage.getItem("compare_sel"))') == [p['page'] for p in MENTORS]
    state['mode'] = 'ok'
    page.locator('#compare-retry').click()
    expect(page.locator('.compare-contact')).to_have_count(2)
    expect(page.locator('#compare-retry')).not_to_be_visible()
    assert state['attempts'] == 2
    assert '/data.js' not in state['requests'] and '/compare-data.js' not in state['requests']


@pytest.mark.parametrize('via_detail', [False, True])
def test_existing_project_survives_comparison_but_never_attaches_to_another_unit(comparison, via_detail):
    page, _ = comparison
    path = '/p/bit-cs-fixture.html' if via_detail else '/compare.html'
    page.goto(ORIGIN + path + '?' + urlencode(dict(GOAL, discovery_return=RETURN)))
    if via_detail:
        page.locator('#detail-selection').click()
    expect(page.locator('.compare-contact')).to_have_count(2)
    same, other = (query(page.locator('.compare-contact').nth(index)) for index in range(2))
    assert all(same.get(key) == value for key, value in GOAL.items())
    assert same['discovery_return'] == other['discovery_return'] == RETURN
    assert other['school'] == 'zju' and other['mentor'] == MENTORS[1]['page']
    assert not any(key in other for key in ('project', 'track', 'program'))
    assert query(page.locator('.pcol .pn a').first)['project'] == GOAL['project']
    assert query(page.locator('.site-header a[href^="applications.html"]'))['project'] == GOAL['project']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_clear_while_loading_prevents_late_response_from_restoring_selection(comparison):
    page, state = comparison
    state['mode'] = 'pending'
    page.goto(ORIGIN + '/compare.html', wait_until='domcontentloaded')
    expect(page.locator('#compare-status')).to_contain_text('正在加载')
    page.locator('#clear-selection').click()
    state['held'].fulfill(json={'mentors': MENTORS})
    expect(page.locator('#hint')).to_be_visible()
    expect(page.locator('#card')).not_to_be_visible()
    expect(page.locator('#compare-status')).not_to_be_visible()
    expect(page.locator('.context-actions a').first).to_be_focused()
    assert page.evaluate('JSON.parse(localStorage.getItem("compare_sel"))') == []


def test_removing_a_column_keeps_keyboard_focus_and_contact_action(comparison):
    page, _ = comparison
    page.goto(ORIGIN + '/compare.html')
    page.get_by_role('button', name='移出同院导师').focus()
    page.keyboard.press('Enter')
    expect(page.get_by_role('button', name='移出另一院系导师')).to_be_focused()
    expect(page.locator('.compare-contact')).to_have_count(1)
    assert page.evaluate('JSON.parse(localStorage.getItem("compare_sel"))') == [MENTORS[1]['page']]
    page.keyboard.press('Enter')
    expect(page.locator('#hint')).to_be_visible()
    expect(page.locator('.context-actions a').first).to_be_focused()


def test_confirmed_removed_ids_are_explained_and_do_not_repeat_after_reload(comparison):
    page, state = comparison
    state['mode'] = 'removed'
    page.goto(ORIGIN + '/compare.html')
    expect(page.locator('#compare-status')).to_contain_text('2 位导师资料已更新或下架')
    expect(page.locator('#hint')).to_be_visible()
    assert page.evaluate('JSON.parse(localStorage.getItem("compare_sel"))') == []
    page.reload()
    expect(page.locator('#hint')).to_be_visible()
    expect(page.locator('#compare-status')).not_to_be_visible()
    assert state['attempts'] == 1


@pytest.mark.parametrize('field,label,value', [
    ('supervisor','导师资格','硕导'),
    ('profile_url','官方资料入口','https://example.edu/teachers/fixture'),
])
def test_detail_evidence_shows_the_actual_field_value(field, label, value):
    proof=dict(origin='crawled',confidence='auto',source='https://example.edu/roster',fetched_at='2026-11-23')
    mentor=dict(MENTORS[0], **{field:value, 'provenance':{field:proof}})
    html=build_site.template_environment().get_template('detail.html.j2').render(p=mentor)
    soup=BeautifulSoup(html,'html.parser')
    row=next(row for row in soup.select('table.pv tr') if row.find('td') and row.td.get_text(strip=True)==label)
    cells=row.find_all('td')
    assert cells[1].get_text(strip=True)==value
    assert cells[4].get_text(strip=True)==proof['fetched_at'] and cells[5].a['href']==proof['source']

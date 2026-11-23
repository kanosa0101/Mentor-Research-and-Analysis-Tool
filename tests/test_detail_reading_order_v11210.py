"""A student can assess a mentor before reaching the existing actions."""
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts import build_site


ORIGIN = 'http://mentor-reading.invalid'
PROFILE = dict(page='bit-cs-fixture', name='测试导师', school='bit', dept='cs',
               title='教授', supervisor='博导', email='mentor@example.invalid',
               research_direction_raw='数据库、计算机系统',
               detail_url='https://example.edu/mentor', provenance={})
GOAL = dict(school='bit', dept='cs', year='2028', degree='master', route='recommend',
            project='existing-project', program='0812', track='ordinary',
            discovery_return='discovery.html?school=bit&topics=数据库')


@pytest.fixture
def detail():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page()
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        state = {}

        def respond(route):
            requests.append(route.request.method)
            assert route.request.method == 'GET'
            path = urlsplit(route.request.url).path
            if path == '/p/bit-cs-fixture.html':
                return route.fulfill(content_type='text/html; charset=utf-8', body=state['html'])
            if path == '/photo.svg':
                return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="112" height="150"><rect width="112" height="150" fill="#bbc"/></svg>')
            if path.startswith('/api/'):
                return route.fulfill(json={'authenticated': False, 'user': None, 'enabled': False})
            file = build_site.SITE / path.removeprefix('/')
            if file.is_file() and file.suffix in ('.js', '.css'):
                return route.fulfill(content_type='text/css' if file.suffix == '.css' else 'text/javascript',
                                     body=file.read_text(encoding='utf-8'))
            return route.abort()

        page.route('**/*', respond)

        def open_detail(width, *, profile=None, goal=None):
            state['html'] = build_site.template_environment().get_template('detail.html.j2').render(p=profile or PROFILE)
            page.set_viewport_size({'width': width, 'height': 844})
            page.goto(ORIGIN + '/p/bit-cs-fixture.html?' + urlencode(goal or GOAL))
            expect(page.locator('[data-browser-bookmark]')).to_have_count(1)
            return page

        yield open_detail
        assert not errors
        assert set(requests) == {'GET'}
        browser.close()


def facts_before_actions(page):
    facts = page.locator('.wrap > .card').first
    actions = page.locator('.context-actions')
    for selector in ('h2', '.dl'):
        box = facts.locator(selector).bounding_box()
        assert box['y'] + box['height'] <= actions.bounding_box()['y']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    return facts, actions


@pytest.mark.parametrize('width', [320, 390, 1440])
def test_mentor_facts_precede_actions_and_are_visible_on_arrival(detail, width):
    page = detail(width)
    facts, actions = facts_before_actions(page)
    assert facts.locator('h2').bounding_box()['y'] < 300
    assert facts.locator('a[href^="mailto:"]').bounding_box()['y'] < 550
    for control in actions.locator('a,button').all():
        expect(control).to_be_visible()
        assert control.bounding_box()['height'] >= (44 if width <= 760 else 40)
    facts.locator('a', has_text='查看学校官网资料').focus()
    page.keyboard.press('Tab')
    expect(actions.locator('a.primary')).to_be_focused()


@pytest.mark.parametrize('width', [320, 390, 1440])
def test_long_facts_and_large_text_keep_actions_reachable(detail, width):
    profile = dict(PROFILE, name='测试导师' * 9, research_direction_raw='数据库系统、人工智能与多模态学习；' * 20,
                   photo_url='/photo.svg')
    page = detail(width, profile=profile)
    page.evaluate("document.documentElement.style.setProperty('--text-body','30px');document.documentElement.style.setProperty('--text-control','28px')")
    facts, actions = facts_before_actions(page)
    photo = facts.locator('img.photo').bounding_box()
    assert photo['y'] + photo['height'] <= actions.bounding_box()['y']
    primary = actions.locator('a.primary')
    primary.scroll_into_view_if_needed()
    expect(primary).to_be_in_viewport()
    assert parse_qs(urlsplit(primary.get_attribute('href')).query)['project'] == ['existing-project']


def test_missing_contact_and_cross_unit_context_keep_original_actions(detail):
    page = detail(390, profile=dict(PROFILE, email=''), goal=dict(GOAL, school='zju'))
    facts, actions = facts_before_actions(page)
    expect(facts).to_contain_text('暂未收录，可查看官网联系渠道')
    expect(page.locator('#detail-scope-warning')).to_be_visible()
    query = parse_qs(urlsplit(actions.locator('a.primary').get_attribute('href')).query)
    assert query['school'] == ['bit'] and query['dept'] == ['cs'] and query['year'] == ['2028']
    assert not any(key in query for key in ('project', 'track', 'program'))
    expect(actions.locator('a', has_text='继续找导师')).to_have_attribute('href', '../' + GOAL['discovery_return'])
    page.locator('#detail-compare').click()
    expect(page.locator('#detail-compare')).to_have_attribute('aria-pressed', 'true')
    page.reload()
    expect(page.locator('#detail-compare')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#detail-selection')).to_contain_text('1 / 5')
    expect(page.locator('[data-browser-bookmark]')).to_have_count(1)

"""Mobile filter interactions ignore superseded requests and retain draft edits."""
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from test_discovery_ux_v1120 import directory, intercept_candidates, open_filters, profiles


@pytest.fixture
def mobile_page(directory):
    with sync_playwright() as pw:
        port = urlsplit(directory).port
        browser = pw.chromium.launch(args=[f'--explicitly-allowed-ports={port}'])
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        intercept_candidates(page, directory, [])
        try:
            yield page
            assert not errors
        finally:
            browser.close()


def candidate_response(route, rows, total):
    route.fulfill(json={'version': 2, 'total': total, 'revision': 'fixture',
                        'missing_email': 0, 'rows': [{'p': row} for row in rows]})


def watch_submit(page):
    page.evaluate('''() => {
      const form = document.getElementById('criteria-form');
      const submit = form.onsubmit;
      form.onsubmit = event => (window.qaDirectorySubmit = submit.call(form, event));
    }''')


@pytest.mark.parametrize('status', [200, 400])
def test_superseded_startup_does_not_open_filters_after_other_results(directory, mobile_page, status):
    page = mobile_page
    held = []

    def delay_startup(route):
        if parse_qs(urlsplit(route.request.url).query).get('dept') == ['cs']:
            held.append(route)
            return
        route.fallback()

    page.route('**/api/mentor-candidates?*', delay_startup)
    page.goto(directory + '/discovery.html?school=bit&dept=cs', wait_until='domcontentloaded')
    page.locator('#clear-unit-context').click()
    expect(page.locator('[data-candidate]')).to_have_count(4)
    expect(page.locator('#criteria-form')).to_be_hidden()
    assert len(held) == 1
    if status == 200:
        candidate_response(held[0], profiles()[4:8], 21)
    else:
        held[0].fulfill(status=status, json={'error': '旧院系请求失败'})

    page.wait_for_function('window.DISCOVERY_READY')
    expect(page.locator('#criteria-form')).to_be_hidden()
    expect(page.locator('#discovery-message')).to_be_empty()
    expect(page.locator('[data-candidate]')).to_have_count(4)
    expect(page.locator('[data-candidate]').first).to_have_attribute('data-candidate', 'bit-cs-fixture-1')


def test_submit_superseded_by_clearing_the_unit_does_not_steal_focus(directory, mobile_page):
    page = mobile_page
    held = []

    def delay_submit(route):
        query = parse_qs(urlsplit(route.request.url).query)
        if query.get('name') != ['导师21']:
            route.fallback()
        elif query.get('dept') == ['cs']:
            held.append(route)
        else:
            route.fulfill(status=400, json={'error': '新范围暂不可用'})

    page.route('**/api/mentor-candidates?*', delay_submit)
    page.goto(directory + '/discovery.html?school=bit&dept=cs')
    page.wait_for_function('window.DISCOVERY_READY')
    open_filters(page)
    watch_submit(page)
    name = page.locator('#intent-name')
    name.fill('导师21')
    page.locator('#apply-criteria').click()
    page.locator('#clear-unit-context').click()
    expect(page.locator('#discovery-message')).to_contain_text('新范围暂不可用')
    name.focus()
    assert len(held) == 1
    candidate_response(held[0], profiles()[-1:], 1)
    page.evaluate('window.qaDirectorySubmit')

    expect(name).to_be_focused()
    expect(page.locator('#criteria-form')).to_be_visible()
    expect(page.locator('[data-candidate]')).to_have_count(4)
    expect(page.locator('#discovery-message')).to_contain_text('新范围暂不可用')


def test_edit_during_submit_keeps_mobile_form_and_input_focus(directory, mobile_page):
    page = mobile_page
    held = []

    def delay_submit(route):
        name = parse_qs(urlsplit(route.request.url).query).get('name')
        if name == ['导师21']:
            held.append(route)
        elif name == ['导师20']:
            candidate_response(route, profiles()[-2:-1], 1)
        else:
            route.fallback()

    page.route('**/api/mentor-candidates?*', delay_submit)
    page.goto(directory + '/discovery.html')
    page.wait_for_function('window.DISCOVERY_READY')
    open_filters(page)
    watch_submit(page)
    name = page.locator('#intent-name')
    name.fill('导师21')
    page.locator('#apply-criteria').click()
    name.fill('导师20')
    assert len(held) == 1
    candidate_response(held[0], profiles()[-1:], 1)
    page.evaluate('window.qaDirectorySubmit')

    expect(page.locator('[data-candidate="bit-cs-fixture-21"]')).to_be_visible()
    expect(page.locator('#criteria-form')).to_be_visible()
    expect(page.locator('#filter-draft-status')).to_be_visible()
    expect(name).to_have_value('导师20')
    expect(name).to_be_focused()

    page.locator('#apply-criteria').click()
    expect(page.locator('[data-candidate="bit-cs-fixture-20"]')).to_be_visible()
    expect(page.locator('#criteria-form')).to_be_hidden()
    expect(page.locator('#discovery-results')).to_be_focused()

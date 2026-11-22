"""Activity browsing and uncertain saves remain usable on small screens."""
import copy
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from crawler import opportunity_util
from scripts import build_site


def catalog():
    row = copy.deepcopy(next(row for row in opportunity_util.load(build_site.ROOT)['opportunities']
                             if opportunity_util.content_scope(row) == 'institutional_activity'))
    day = datetime.now(timezone(timedelta(hours=8))).date()
    row.update(source_state='verified', cycle='current', checked_at=day.isoformat(), verified_at=day.isoformat(),
               registration_start=(day-timedelta(days=1)).isoformat(), deadline=(day+timedelta(days=10)).isoformat(),
               event_start='', event_end='')
    return {'mode': 'account', 'opportunities': [row], 'other_contents': []}


@pytest.mark.parametrize('width', [390, 1440])
def test_lost_save_response_preserves_inputs_and_explicit_retry_uses_existing_project(width):
    data = catalog()
    html = build_site.render_opportunities_page()
    posts, errors = [], []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route(request):
            path = urlsplit(request.request.url).path
            if path == '/opportunities.html':
                return request.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/workflow/opportunities':
                assert request.request.method == 'POST'
                posts.append(request.request.post_data_json)
                assert request.request.headers['x-csrf-token'] == 'fixture-csrf'
                if len(posts) == 1:
                    return  # The server may have saved; its response is lost.
                value = {'project_id': 'existing-project', 'duplicate': True}
            elif path == '/api/auth/me':
                value = {'authenticated': True, 'user': {'id': 'fixture'}, 'csrf_token': 'fixture-csrf'}
            elif path == '/api/opportunities':
                value = data
            elif path == '/api/workflow':
                value = {'projects': {}}
            else:
                value = {'enabled': False, 'events': []}
            request.fulfill(content_type='application/json', body=json.dumps(value))

        page.route('**/*', route)
        try:
            page.goto('http://mentor-test.invalid/opportunities.html', wait_until='domcontentloaded')
            page.locator('[data-save-opportunity]').click()
            page.locator('#opportunity-name').fill('我准备参加的科研活动')
            day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            page.locator('#opportunity-reminder').fill(day)
            page.locator('#opportunity-confirm').click()
            expect(page.locator('#save-message')).to_contain_text('尚未确认', timeout=11000)
            expect(page.locator('#opportunity-confirm')).to_be_enabled()
            expect(page.locator('#opportunity-cancel')).to_be_enabled()
            expect(page.locator('#opportunity-name')).to_have_value('我准备参加的科研活动')
            expect(page.locator('#opportunity-reminder')).to_have_value(day)
            assert len(posts) == 1  # Recovery must never replay a write automatically.
            page.locator('#opportunity-confirm').click()
            expect(page.locator('#opportunity-save')).not_to_be_visible()
            expect(page.locator('#opportunity-result')).to_contain_text('未重复创建')
            expect(page.locator('#opportunity-result a')).to_have_attribute('href', 'applications.html?project=existing-project')
            assert posts == [posts[0], posts[0]]
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize('width', [320, 390, 1440])
def test_activity_summary_keeps_conditions_and_search_shows_the_matching_contact(width):
    data = catalog()
    row = data['opportunities'][0]
    row.update(graduation_year=None, title='计算机研究冬令营', eligibility=['计算机相关专业本科三年级', '须经本校推荐，成绩排名前20%'])
    row['research_directions'] = [dict(direction=direction, department='计算机研究所', contact='张老师' if index < 2 else '李老师',
        email='zhang@example.edu.cn' if index < 2 else 'li@example.edu.cn', source_url=row['source_url'],
        source_locator='研究方向表', verified_at=row['verified_at'])
        for index, direction in enumerate(['深度学习', '系统安全', '可信计算'])]
    html = build_site.render_opportunities_page()
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 900})

        def route(request):
            path = urlsplit(request.request.url).path
            assert request.request.method == 'GET'
            if path == '/opportunities.html':
                return request.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/opportunities':
                value = dict(data, mode='public')
            else:
                value = {'authenticated': False, 'enabled': False, 'events': []}
            request.fulfill(content_type='application/json', body=json.dumps(value))

        page.route('**/*', route)
        try:
            page.goto('http://mentor-test.invalid/opportunities.html', wait_until='domcontentloaded')
            card = page.locator('[data-opportunity]')
            expect(card).to_have_count(1)
            for condition in row['eligibility']:
                expect(card.get_by_text(condition, exact=True)).to_be_visible()
            expect(card.locator('.opportunity-cohort')).to_contain_text('毕业届别未明确')
            expect(card.locator('.opportunity-contact-preview a')).to_have_count(1)
            assert page.evaluate('document.documentElement.scrollWidth') == width
            panel = page.locator('#opportunity-filter-panel')
            assert panel.evaluate('(node)=>node.open') == (width > 650)
            if width == 390:
                action = card.locator('.opportunity-primary').bounding_box()
                assert action['y'] + action['height'] <= 900
            if width <= 650:
                panel.locator('summary').click()
            page.locator('#opportunity-search').fill('可信计算')
            expect(card.locator('.opportunity-contact-preview')).to_contain_text('可信计算')
            expect(card.locator('.opportunity-contact-preview')).to_contain_text('李老师')
            expect(card.locator('.opportunity-contact-preview')).not_to_contain_text('张老师')
            page.locator('#opportunity-search').fill('计算机研究所 可信计算')
            expect(card.locator('.opportunity-contact-preview')).to_contain_text('李老师')
            expect(card.locator('.opportunity-contact-preview')).not_to_contain_text('张老师')
            page.locator('#opportunity-search').fill('可信计算')
            if width <= 650:
                panel.locator('summary').click()
                expect(page.locator('#opportunity-filter-summary')).to_contain_text('可信计算')
                page.set_viewport_size({'width': 1440, 'height': 900})
                expect(page.locator('#opportunity-search')).to_be_visible()
                expect(page.locator('#opportunity-search')).to_have_value('可信计算')
            materials = card.locator('details').filter(has=page.get_by_text('申请材料与报名步骤', exact=True)).first
            materials.locator('summary').first.click()
            for material in row['materials']:
                expect(materials.get_by_text(material, exact=True)).to_be_visible()
        finally:
            browser.close()

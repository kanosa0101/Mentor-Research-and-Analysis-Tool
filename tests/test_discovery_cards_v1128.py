"""Keep four-card batches compact, aligned and clear about source dates."""
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from test_discovery_ux_v1120 import directory, profiles


def card_rows():
    rows = [dict(p, source_date='2026-11-23', email_source_date='2026-11-20') for p in profiles()[:8]]
    rows[4].update(name='欧阳明远·亚历山大', dept_name='计算机科学与工程学院（网络空间安全学院）')
    rows[5]['research_direction_raw'] = '多模态学习、机器人与计算机视觉。' * 15
    rows[6].update(email='very-long-personal-address-for-layout@example.edu.cn', recruitment_labels=['科研实习招募记录'])
    rows[7].update(email='', research_direction_raw='', bio_excerpt='官网本人简历介绍研究背景。' * 12)
    return rows


def respond(page, rows):
    def handle(route):
        query = parse_qs(urlsplit(route.request.url).query)
        offset, limit = (int(query[key][0]) for key in ('offset', 'limit'))
        route.fulfill(json=dict(version=2, total=len(rows), rows=[dict(p=p) for p in rows[offset:offset + limit]],
                                missing_email=0, revision='card-layout'))
    page.route('**/api/mentor-candidates?*', handle)


def geometry(page):
    return page.locator('.results-card').evaluate_all('''cards => cards.map(card => {
      const rect = node => {const r=node.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height}};
      return {card:rect(card),source:rect(card.querySelector('.candidate-source')),
        actions:rect(card.querySelector('.card-primary-actions')),
        bookmark:rect(card.querySelector('.candidate-bookmark')),
        buttons:[...card.querySelectorAll('.card-primary-actions > *')].map(rect)};
    })''')


@pytest.mark.parametrize('width', [1440, 850, 390, 320])
def test_four_cards_use_content_height_without_clipping_or_losing_batch_state(directory, width):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=[f'--explicitly-allowed-ports={urlsplit(directory).port}'])
        page = browser.new_page(viewport={'width': width, 'height': 844})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        respond(page, card_rows())
        page.goto(directory + '/discovery.html')
        expect(page.locator('.results-card')).to_have_count(4)
        # Four short profiles should not reserve a large empty source row.
        before = geometry(page)
        assert max(row['actions']['top'] - row['source']['bottom'] for row in before) <= 16
        if width <= 850:
            assert before[0]['card']['bottom'] <= 844
        page.get_by_role('button', name='换一批').click()
        expect(page.locator('[data-candidate="bit-cs-fixture-5"]')).to_have_count(1)
        expect(page.locator('.candidate-source')).to_contain_text(['邮箱来源采集', '邮箱来源采集', '科研实习招募记录', '邮箱来源采集'])
        long_cards = geometry(page)
        heights = [row['card']['height'] for row in long_cards]
        assert max(heights) - min(heights) <= 1
        for row in long_cards:
            assert row['actions']['top'] >= row['source']['bottom']
            assert row['bookmark']['top'] >= row['actions']['bottom']
            assert row['bookmark']['bottom'] <= row['card']['bottom'] - 1
            assert all(button['height'] >= (44 if width <= 850 else 40) for button in row['buttons'])
            assert all(button['left'] >= row['card']['left'] and button['right'] <= row['card']['right'] for button in row['buttons'])
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        page.reload()
        expect(page.locator('[data-candidate="bit-cs-fixture-5"]')).to_have_count(1)
        expect(page.locator('.results-card')).to_have_count(4)
        assert not errors
        browser.close()


def test_source_caption_does_not_borrow_a_different_fields_newer_date(directory):
    rows = card_rows()[:4]
    rows[0]['provenance'] = {'research_direction_raw': {'fetched_at': '2026-11-23'}}
    rows[1]['email_source_date'] = ''
    rows[2].update(email_source='', detail_url='https://cs.bit.edu.cn/profile', source_date='2024-10-01')
    rows[3]['email_source'] = 'javascript:alert(1)'
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=[f'--explicitly-allowed-ports={urlsplit(directory).port}'])
        page = browser.new_page()
        respond(page, rows)
        page.goto(directory + '/discovery.html')
        captions = page.locator('.candidate-source > :last-child')
        expect(captions).to_have_text(['邮箱来源采集 2026-11-20', '邮箱来源日期未明确',
                                      '资料采集记录 2024-10-01', '来源待核对'])
        expect(page.locator('.candidate-source a')).to_have_count(3)
        assert page.locator('.candidate-source').last.inner_text() == '来源待核对'
        browser.close()

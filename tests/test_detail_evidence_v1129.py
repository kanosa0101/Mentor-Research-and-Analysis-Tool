"""Source evidence stays readable without horizontal hunting on a phone."""
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts import build_site


ORIGIN = 'http://mentor-evidence.invalid'
SOURCE = 'https://example.edu/teachers/fixture'
DATE = '2026-11-23'
LONG_VALUE = '计算机视觉、神经网络与多模态学习；' * 20
LONG_URL = 'https://example.edu/teachers/' + 'long-official-path/' * 10


@pytest.fixture
def evidence():
    proof = dict(origin='crawled', confidence='auto', source=SOURCE, fetched_at=DATE)
    mentor = dict(page='bit-cs-fixture', name='测试导师', school='bit', dept='cs',
                  title='教授', supervisor='博导', email='fixture@example.invalid',
                  research_direction_raw=LONG_VALUE, homepage=LONG_URL,
                  provenance={
                      'research_direction_raw': proof,
                      'homepage': dict(proof, origin='manual', confidence='verified'),
                      'email': dict(proof, source='', fetched_at=''),
                      'supervisor': dict(proof, source='人工电话核实'),
                  })
    html = build_site.template_environment().get_template('detail.html.j2').render(p=mentor)
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            assert route.request.method == 'GET'
            path = urlsplit(route.request.url).path
            if path == '/p/bit-cs-fixture.html':
                return route.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path.startswith('/api/'):
                return route.fulfill(json={'authenticated': False, 'user': None, 'enabled': False})
            file = build_site.SITE / path.removeprefix('/')
            if file.is_file() and file.suffix in ('.js', '.css'):
                return route.fulfill(content_type='text/css' if file.suffix == '.css' else 'text/javascript', body=file.read_text(encoding='utf-8'))
            return route.abort()

        page.route('**/*', respond)
        page.goto(ORIGIN + '/p/bit-cs-fixture.html?school=bit&dept=cs&year=2028&route=recommend&project=existing-project')
        page.locator('#profile-evidence > summary').focus()
        page.keyboard.press('Enter')
        expect(page.locator('#profile-evidence')).to_have_attribute('open', '')
        yield page
        assert not errors
        browser.close()


@pytest.mark.parametrize('width', [320, 390, 620, 760, 761, 850, 1440])
def test_field_value_date_and_source_fit_without_horizontal_reading(evidence, width):
    page = evidence
    page.set_viewport_size({'width': width, 'height': 900})
    table = page.locator('#profile-evidence .pv')
    row = table.locator('tr').filter(has=page.locator('td', has_text='研究方向')).first
    cells = row.locator('td')
    expect(cells.nth(1)).to_have_text(LONG_VALUE)
    expect(cells.nth(4)).to_have_text(DATE)
    expect(cells.nth(5).locator('a')).to_have_attribute('href', SOURCE)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert page.locator('.proof-scroll').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
    for index in (0, 1, 4, 5):
        box = cells.nth(index).bounding_box()
        assert 0 <= box['x'] and box['x'] + box['width'] <= width + 1
    # A date is readable as a single unit, even in a narrow evidence row.
    assert cells.nth(4).evaluate('''el => {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const ys=[]; while(walker.nextNode()) {
        if(!walker.currentNode.textContent.trim()) continue;
        const range=document.createRange();range.selectNodeContents(walker.currentNode);
        ys.push(...[...range.getClientRects()].filter(r=>r.width>0).map(r=>Math.round(r.y)));
      } return new Set(ys).size;
    }''') == 1
    homepage = table.locator('tr').filter(has=page.locator('td', has_text='个人主页')).first
    expect(homepage.locator('td').nth(1)).to_have_text(LONG_URL)
    expect(homepage).to_contain_text('人工整理')
    expect(homepage).to_contain_text('已核对')
    # Opening evidence does not discard the selected application.
    assert 'project=existing-project' in page.locator('.context-actions a.primary').get_attribute('href')


def test_missing_evidence_does_not_offer_a_self_link_or_invent_a_date(evidence):
    rows = evidence.locator('#profile-evidence .pv tr')
    email = rows.filter(has=evidence.locator('td', has_text='邮箱')).first
    expect(email.locator('td').nth(4)).to_have_text('日期未记录')
    expect(email.locator('td').nth(5)).to_have_text('来源未记录')
    expect(email.locator('a')).to_have_count(0)
    manual = rows.filter(has=evidence.locator('td', has_text='导师资格')).first
    expect(manual.locator('td').nth(5)).to_have_text('人工电话核实')
    expect(manual.locator('a')).to_have_count(0)
    expect(evidence.locator('.dl a[href=""]')).to_have_count(0)


@pytest.mark.parametrize('width', [320, 761, 850])
def test_larger_evidence_text_wraps_metadata_without_clipping_the_date(evidence, width):
    page = evidence
    page.set_viewport_size({'width': width, 'height': 900})
    page.add_style_tag(content='#profile-evidence{--text-small:26px;--text-body:30px}')
    assert page.locator('.proof-scroll').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
    for time in page.locator('#profile-evidence time').all():
        box = time.bounding_box()
        assert 0 <= box['x'] and box['x'] + box['width'] <= width
    for link in page.locator('#profile-evidence .pv a').all():
        box = link.bounding_box()
        assert box['width'] >= 44
        if width<=760:assert box['height'] >= 44

"""Read-only v20 content and task checks, rendering owned templates in memory."""
import json
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler import opportunity_util
from scripts import build_site
from scripts.serve import create_server


def main():
    output = ROOT / 'cache/v20/ui'
    output.mkdir(parents=True, exist_ok=True)
    catalog = opportunity_util.public_catalog(opportunity_util.load(ROOT))
    assert len(catalog['opportunities']) == 9 and len(catalog['other_contents']) == 9
    env = build_site.template_environment()
    pages = {name + '.html': env.get_template(name + '.html.j2').render() for name in ('opportunities', 'admissions', 'start', 'desk')}
    result = {'cases': [], 'writes': [], 'page_errors': [], 'screenshots_reviewed': False}
    with tempfile.TemporaryDirectory(prefix='mentor-v20-ui-') as temp:
        server = create_server(outreach=Path(temp)/'outreach.yaml', workflow=Path(temp)/'workflow.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for width, scale, label in ((1440, 1, '1440'), (390, 1, '390'), (320, 1, '320'), (768, 1, '768'), (720, 2, '1440-zoom200-equivalent')):
                    context = browser.new_context(viewport={'width': width, 'height': 950}, device_scale_factor=scale)
                    def readonly(route):
                        path = urlsplit(route.request.url).path.lstrip('/')
                        if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                            result['writes'].append(route.request.url)
                            route.abort()
                        elif not route.request.url.startswith(base):
                            route.fulfill(status=200, body='')
                        elif path in pages:
                            route.fulfill(status=200, body=pages[path], content_type='text/html')
                        elif path == 'opportunities-data.js':
                            route.fulfill(status=200, body='window.OPPORTUNITIES='+json.dumps(catalog, ensure_ascii=False)+';', content_type='application/javascript')
                        elif path == 'api/opportunities':
                            route.fulfill(json={**catalog, 'mode': 'public'})
                        elif path == 'api/health':
                            route.fulfill(json={'mode': 'public'})
                        elif path == 'api/push/config':
                            route.fulfill(json={'enabled': False, 'mode': 'public'})
                        elif path == 'api/updates':
                            route.fulfill(json={'updates': []})
                        else:
                            route.continue_()
                    context.route('**/*', readonly)
                    page = context.new_page()
                    page.on('pageerror', lambda error: result['page_errors'].append(str(error)))
                    page.goto(base+'/opportunities.html', wait_until='networkidle')
                    page.wait_for_function('opportunityModeReady')
                    cards = page.locator('[data-opportunity]')
                    assert cards.count() == 2
                    assert page.locator('.opportunity-eligibility').first.is_visible()
                    assert not page.locator('.opportunity-details[open]').count()
                    assert not page.locator('#monitor-details').evaluate('(e)=>e.open')
                    assert not page.locator('[data-save-opportunity]').count()
                    assert page.locator('[href^="local.html?id="]').count() == 2
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    page.screenshot(path=str(output/f'opportunities-{label}.png'), full_page=True)
                    source = catalog['opportunities']
                    for card in cards.all():
                        item = next(o for o in source if o['id'] == card.get_attribute('data-opportunity'))
                        assert item['content_classification']['organizer_name'] in card.inner_text()
                        assert all(condition in card.inner_text() for condition in item['eligibility'])
                        assert card.locator('a.opportunity-primary').get_attribute('href') == item['source_url']
                    card = page.locator('[data-opportunity="iscas-research-2026"]')
                    summary = card.locator('details>summary').first
                    summary.focus(); summary.press('Enter')
                    assert card.get_by_text('材料与提交阶段', exact=True).is_visible()
                    summary.press('Enter')
                    assert not card.get_by_text('材料与提交阶段', exact=True).is_visible()
                    card.locator('summary', has_text='研究方向与部门联系人').click()
                    assert card.locator('.research-direction a[href^="mailto:"]').first.is_visible()
                    page.locator('#opportunity-state').select_option('all')
                    assert page.locator('[data-opportunity]').count() == 9
                    for old in catalog['other_contents']:
                        page.goto(base+'/opportunities.html?id='+old['id'], wait_until='networkidle')
                        page.wait_for_function('opportunityModeReady')
                        assert page.locator('[data-other-content]').get_attribute('data-other-content') == old['id']
                        assert not page.locator('[data-opportunity], [data-save-opportunity]').count()
                        assert page.locator('a.opportunity-primary').get_attribute('href') == old['source_url']
                        links = page.locator('.opportunity-moved a[href^="p/"]')
                        assert links.count() == len(old.get('mentor_ids', []))
                    page.screenshot(path=str(output/f'legacy-{label}.png'), full_page=True)
                    page.goto(base+'/admissions.html?school=bit&dept=cs&year=2027&degree=master&route=exam&track=ordinary', wait_until='networkidle')
                    page.wait_for_function('window.ADMISSIONS_READY')
                    assert page.locator('#policy-year').input_value() == '2027'
                    assert page.locator('#policy-degree').input_value() == 'master'
                    assert page.locator('#policy-route').input_value() == 'exam'
                    assert '非全日制仅接受定向就业' in page.locator('[data-checklist-field="eligibility"]').inner_text()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    page.screenshot(path=str(output/f'admissions-{label}.png'), full_page=True)
                    page.goto(base+'/start.html', wait_until='networkidle')
                    assert page.locator('#target-entries a').count() >= 4
                    assert not page.locator('#current-actions').is_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    page.screenshot(path=str(output/f'start-{label}.png'), full_page=True)
                    original='discovery.html?schools=bit,pku&topics=graph'
                    page.goto(base+'/desk.html?'+urlencode({'mentor':'bit-cs-daiqiangqiang','discovery_return':original}), wait_until='networkidle')
                    page.wait_for_function('window.CONTACT_READY')
                    assert parse_qs(urlsplit(page.url).query)['discovery_return'] == [original]
                    assert page.locator('.site-header nav a', has_text='找导师').get_attribute('href') == original
                    assert not page.locator('#desk-backup').is_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    page.screenshot(path=str(output/f'desk-{label}.png'), full_page=True)
                    page.locator('.site-tools>summary').click()
                    page.locator('.site-tools-menu details>summary').click()
                    assert page.get_by_role('link', name='旧套磁看板').is_visible()
                    if width == 1440:
                        for bad in ('https://other.example/discovery.html','//other.example/discovery.html','discovery.html#bad','discovery.html?x=%5c','discovery.html?x=%0a','discovery.html?bad=\x01'):
                            page.goto(base+'/desk.html?'+urlencode({'discovery_return':bad}), wait_until='networkidle')
                            assert 'discovery_return' not in parse_qs(urlsplit(page.url).query)
                    result['cases'].append({'viewport': label, 'passed': True, 'legacy_ids_checked': 9, 'active_cards': 2})
                    context.close()
                browser.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()
    assert not result['writes'] and not result['page_errors'], result
    result['passed'] = True
    result['zoom_note'] = '720 CSS px at deviceScaleFactor 2 models 1440 physical pixels at 200% layout zoom; native browser toolbar zoom not exercised.'
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

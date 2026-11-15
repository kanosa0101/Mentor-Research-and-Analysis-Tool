"""Public discovery UX acceptance; all rendering and private files stay temporary."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix='discovery-ux-v1-1-') as tmp:
        root = Path(tmp)
        site = root / 'site'
        site.mkdir()
        for name in ['data.js', 'compare-data.js', 'search.js', 'discovery.js', 'discovery-core.js', 'ui.css']:
            shutil.copyfile(ROOT / 'site' / name, site / name)
        env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'), autoescape=True)
        (site / 'discovery.html').write_text(env.get_template('discovery.html.j2').render(), encoding='utf-8')
        server = create_server(site=site, outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for width in [1440, 390]:
                    page = browser.new_page(viewport={'width': width, 'height': 900})
                    errors, writes = [], []
                    page.on('pageerror', lambda e: errors.append(str(e)))

                    def route(request):
                        if request.request.method not in ['GET', 'HEAD']:
                            writes.append(request.request.method)
                            request.abort()
                        elif request.request.url.startswith(base + '/'):
                            request.continue_()
                        else:
                            request.fulfill(status=200, body='')

                    page.route('**/*', route)
                    page.goto(base + '/discovery.html', wait_until='networkidle')
                    page.wait_for_function('window.DISCOVERY_READY')
                    assert not page.locator('#project-options').evaluate('(e)=>e.open')
                    y = page.locator('[data-candidate]').first.bounding_box()['y']
                    assert y < 900, f'first candidate below first viewport: {width}, {y}'
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    if width == 390:
                        assert not page.locator('#filter-options').evaluate('(e)=>e.open')
                        page.locator('#filter-options > summary').click()
                    page.fill('#school-search', '上海')
                    page.click('#select-visible-schools')
                    chosen = page.locator('#intent-schools option:checked').count()
                    assert chosen >= 2
                    page.click('#clear-school-search')
                    assert page.locator('#intent-schools option:checked').count() == chosen
                    page.evaluate('reviewDirty=true')
                    page.once('dialog', lambda dialog: dialog.dismiss())
                    page.click('#clear-schools')
                    assert page.locator('#intent-schools option:checked').count() == chosen
                    page.evaluate('reviewDirty=false')
                    page.click('#apply-criteria')
                    page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                    page.locator('#filter-options > summary').click()
                    assert '上海' in page.locator('#filter-options-label').inner_text()
                    assert page.locator('#criteria-dirty').is_hidden()
                    first = page.locator('[data-candidate]').first.get_attribute('data-candidate')
                    page.click('#apply-criteria')
                    page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                    assert page.locator('[data-candidate]').first.get_attribute('data-candidate') == first
                    # Public fixture: suspicious contact is not copied into the card.
                    page.evaluate("""() => { const p=DATA.find(p=>p.page==='hnu-cs-huyikun');view=[{p,result:DiscoveryRules.evaluate(p,applied,{})}];render(); }""")
                    assert '13873160076' not in page.locator('.public-email').inner_text()
                    assert '待核对' in page.locator('.public-email').inner_text()
                    page.goto(base + '/discovery.html?project=missing&school=bit&dept=cs&track=special&program=085404%7C计算机技术', wait_until='networkidle')
                    page.wait_for_function('window.DISCOVERY_READY')
                    assert page.locator('#project-options').evaluate('(e)=>e.open')
                    assert page.locator('#mode-opportunity').is_disabled()
                    assert not errors and not writes, (errors, writes)
                    results.append(dict(width=width, first_candidate_y=y, multi_select=True, unsaved_guard=True, scope_guard=True, stable_order=True, suspicious_email_hidden=True))
                    page.close()
                browser.close()
            assert not list((root / 'private').glob('*'))
        finally:
            server.shutdown()
            server.server_close()
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    main()

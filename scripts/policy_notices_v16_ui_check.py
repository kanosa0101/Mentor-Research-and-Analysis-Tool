"""Real v16 public policies/notices in an isolated site and temporary private directory."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from admissions_v15_ui_check import fixture
from build_site import template_environment, write_html
from serve import create_server


def main():
    out = ROOT / 'cache/policy_v16/integration_data/ui'
    out.mkdir(parents=True, exist_ok=True)
    data = fixture()
    data.update(yaml.safe_load((ROOT / 'data/admissions.yaml').read_text(encoding='utf-8')))
    data['checks'] = json.loads((ROOT / 'data/admissions_checks.json').read_text(encoding='utf-8'))
    data['entries'] = yaml.safe_load((ROOT / 'data/admissions_entries.yaml').read_text(encoding='utf-8'))['entries']
    notices = json.loads((ROOT / 'data/notices.json').read_text(encoding='utf-8'))
    targets = yaml.safe_load((ROOT / 'cache/policy_v16/integration_data/new-targets.yaml').read_text(encoding='utf-8'))['targets']
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / 'site'
        site.mkdir()
        for name in ('admissions.js', 'admissions-core.js', 'ui.css', 'workflow.js'):
            shutil.copy2(ROOT / 'site' / name, site / name)
        (site / 'admissions-data.js').write_text('window.ADMISSIONS_DATA=' + json.dumps(data, ensure_ascii=False) + ';', encoding='utf-8')
        write_html(site / 'admissions.html', template_environment().get_template('admissions.html.j2').render())
        write_html(site / 'notices.html', template_environment().get_template('notices.html.j2').render(**notices))
        server = create_server(site=site, outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}/'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                    for school, dept, track, ids in (
                        ('tsinghua', 'cs', 'ordinary', ['tsinghua-2027-phd-assessment-v16pilot', 'tsinghua-cs-2027-phd-assessment-v16pilot']),
                        ('tsinghua', 'cs', 'special', ['tsinghua-2027-phd-assessment-v16pilot']),
                        ('tsinghua', 'auto', 'ordinary', ['tsinghua-2027-phd-assessment-v16pilot']),
                        ('zju', 'cs', 'ordinary', ['zju-2027-phd-assessment-v16pilot']),
                        ('pku', 'cs', 'ordinary', []),
                    ):
                        page.goto(base + f'admissions.html?school={school}&dept={dept}&year=2027&degree=phd&route=assessment&track={track}', wait_until='networkidle')
                        page.wait_for_function('window.ADMISSIONS_READY === true')
                        actual = page.locator('[data-policy]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.policy)')
                        assert sorted(actual) == sorted(ids), (school, dept, track, actual)
                        if school == 'tsinghua' and dept == 'cs' and track == 'ordinary':
                            card = page.locator('[data-policy="tsinghua-cs-2027-phd-assessment-v16pilot"]')
                            card.locator('summary').click()
                            assert '2026-11-30T15:00:00+08:00' in card.inner_text()
                            assert '全部专项仅第一时间' in card.inner_text()
                            assert '3.5/4' in card.inner_text() and '不作为所有普通博士GPA门槛' in card.inner_text()
                            school_card = page.locator('[data-policy="tsinghua-2027-phd-assessment-v16pilot"]')
                            assert school_card.locator('.quality').count() == 1, 'school policy must not inherit CS deadline'
                        if school == 'zju':
                            card = page.locator('[data-policy]')
                            card.locator('summary').click()
                            assert '2026-11-20T20:00:00+08:00' in card.inner_text()
                            assert '不是普通全日制统一补报名' in card.inner_text()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, school, dept)
                        tag = f'policy-{school}-{dept}-{track}-{width}'
                        page.screenshot(path=str(out / (tag + '.png')), full_page=True)
                        page.screenshot(path=str(out / (tag + '-viewport.png')))
                        results.append({'case': tag, 'policies': actual, 'overflow': False})
                    for target in targets:
                        school = target['school']
                        expected = [n for n in notices['notices'] if n['school'] == school and n['dept'] == 'cs']
                        page.goto(base + f'notices.html?school={school}&dept=cs&year=2027&degree=phd&route=assessment&track=ordinary', wait_until='networkidle')
                        visible = page.locator('article.card:visible')
                        assert visible.count() == len(expected), (school, visible.count(), len(expected))
                        text = visible.all_inner_texts()
                        assert all('截止日期 待核验' in t and '入学年份 待核验' in t and '候选通知，申请条件和日期尚未核验' in t for t in text)
                        assert all(n['publication_date'] in t for n, t in zip(expected, text))
                        assert page.locator('#school option').count() == 19
                        assert page.locator('#notice-policy-link').get_attribute('href').find('degree=phd') >= 0
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, school)
                        tag = f'notices-{school}-{width}'
                        page.screenshot(path=str(out / (tag + '.png')), full_page=True)
                        page.screenshot(path=str(out / (tag + '-viewport.png')))
                        results.append({'case': tag, 'count': len(expected), 'overflow': False})
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    (out / 'results.json').write_text(json.dumps({'cases': results, 'page_errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(results)} isolated UI cases passed; no overflow or page errors')


if __name__ == '__main__':
    main()

"""核对清单验收：仅渲染临时站点，私人 API 使用临时目录。"""
import shutil
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from scripts.build_site import SITE, template_environment, write_html
from scripts.serve import create_server


def main():
    out = Path('cache/checklist')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp)
        site = temporary / 'site'
        site.mkdir()
        for source in SITE.iterdir():
            if source.is_file():
                shutil.copy2(source, site / source.name)
        # 固定测试范围，不对集成后的真实规则总数做断言。
        data = json.loads((site / 'admissions-data.js').read_text(encoding='utf-8').split('=', 1)[1].strip().rstrip(';'))
        fixture_ids = {'tsinghua-2027-master-exam', 'tsinghua-cs-2027-085400-exam', 'seu-auto-2027-master-recommend'}
        data['policies'] = [policy for policy in data['policies'] if policy['id'] in fixture_ids]
        general = next(policy for policy in data['policies'] if policy['id'] == 'tsinghua-cs-2027-085400-exam')
        secondary_url = 'https://example.edu/pre-registration.pdf'
        data['sources']['fixture-secondary'] = {'url': secondary_url, 'format': 'pdf', 'label': '预报名材料PDF'}
        data['sources'][general['source_id']]['label'] = '正式报名通知'
        general['review_hashes'] = {**general['review_hashes'], 'fixture-secondary': 'fixture-hash'}
        data['checks']['fixture-secondary'] = {'status': 'ok', 'hash': 'fixture-hash', 'last_success': '2026-10-14'}
        general['fields']['materials'] = {'text': '仅预报名阶段提交材料', 'quote': '预报名材料', 'locator': '预报名PDF第二页', 'source_ids': ['fixture-secondary']}
        general['fields']['timeline'] = {'text': '预报名与正式报名阶段分别核对', 'quote': '报名阶段', 'locator': '两份PDF报名阶段', 'source_ids': [general['source_id'], 'fixture-secondary']}
        general['events'] = [{'kind': 'deadline', 'at': '2026-09-12', 'label': '预报名材料提交截止', 'quote': '材料提交', 'locator': '预报名PDF第二页', 'source_ids': ['fixture-secondary']}]
        for name in ['工程硕博士专项', '菁英班']:
            data['policies'].append({**general, 'id': 'fixture-' + name, 'level': 'dept', 'track': 'special', 'program': name, 'fields': {'eligibility': {'text': name + '专属条件', 'quote': name, 'locator': '测试条款'}}})
        (site / 'admissions-data.js').write_text('window.ADMISSIONS_DATA = ' + json.dumps(data, ensure_ascii=False) + ';', encoding='utf-8')
        write_html(site / 'admissions.html', template_environment().get_template('admissions.html.j2').render())
        private = temporary / 'private'
        server = create_server(site=site, outreach=private / 'outreach.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        target = 'school=tsinghua&dept=cs&year=2027&degree=master&route=exam&track=ordinary'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/admissions.html?' + target, wait_until='networkidle')
                    page.wait_for_function('window.ADMISSIONS_READY === true')
                    assert page.locator('[data-checklist-field]').count() == 8, '完整目标应显示8类核对清单'
                    assert page.locator('[data-checklist-field="exams"] [data-checklist-policy]').count() == 2
                    assert '408' in page.locator('[data-checklist-field="exams"]').inner_text()
                    assert '专业适用待核对' in page.locator('[data-checklist-field="exams"]').inner_text()
                    material = page.locator('[data-checklist-field="materials"] [data-checklist-policy="tsinghua-cs-2027-085400-exam"]')
                    assert material.locator('a[target="_blank"]').all_text_contents() == ['预报名材料PDF']
                    assert material.locator('a[target="_blank"]').get_attribute('href') == secondary_url
                    policy_material = page.locator('[data-policy="tsinghua-cs-2027-085400-exam"] .policy-field').filter(has=page.get_by_role('heading', name='所需材料', exact=True))
                    assert policy_material.locator('a').get_attribute('href') == secondary_url
                    assert policy_material.locator('a').inner_text() == '预报名材料PDF'
                    mixed = page.locator('[data-checklist-field="timeline"] [data-checklist-policy="tsinghua-cs-2027-085400-exam"] a[target="_blank"]')
                    assert mixed.all_text_contents() == ['正式报名通知', '预报名材料PDF']
                    checklist_event = page.locator('#checklist-events .quality').filter(has_text='预报名材料提交截止')
                    assert checklist_event.locator('a').get_attribute('href') == secondary_url
                    assert checklist_event.locator('a').inner_text() == '预报名材料PDF'
                    policy_event = page.locator('[data-policy="tsinghua-cs-2027-085400-exam"] .quality').filter(has_text='预报名材料提交截止')
                    assert policy_event.locator('a').get_attribute('href') == secondary_url
                    page.select_option('#policy-program', '085400|电子信息')
                    assert '专业适用待核对' not in page.locator('[data-checklist-field="exams"]').inner_text()
                    page.goto(base + '/admissions.html?' + target + '&program=081200', wait_until='networkidle')
                    assert '408' not in page.locator('#application-checklist').inner_text()
                    page.goto(base + '/admissions.html?' + target, wait_until='networkidle')
                    assert '未整理' in page.locator('[data-checklist-field="funding"]').inner_text()
                    assert page.locator('[data-checklist-field="funding"] a[target="_blank"]').count() == 2, '未整理项也应能核对各层原文及质量'
                    assert '待选择导师核验' in page.locator('#application-checklist').inner_text()
                    assert page.locator('#application-checklist a[target="_blank"]').count() > 0
                    assert page.locator('#application-checklist input[type="checkbox"]').count() == 0, '证据清单不应提供临时已读勾选'
                    page.reload(wait_until='networkidle')
                    assert not private.exists(), '仅查看不得保存私人文件'
                    page.screenshot(path=str(out / 'checklist-desktop.png'), full_page=True)
                    page.locator('#application-checklist').screenshot(path=str(out / 'checklist-desktop-panel.png'))
                    discovery = page.locator('#checklist-mentors').get_attribute('href')
                    assert all(value in discovery for value in ['school=tsinghua', 'dept=cs', 'year=2027', 'route=exam', 'track=ordinary'])
                    assert 'school=tsinghua%2Fcs' in page.locator('#checklist-notices').get_attribute('href')
                    assert 'year=2027' in page.locator('#checklist-notices').get_attribute('href')
                    assert 'track=ordinary' in page.locator('#checklist-notices').get_attribute('href')
                    page.locator('#checklist-project').click()
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert page.input_value('#project-year') == '2027'
                    assert '清华' in page.input_value('#project-school')
                    assert '计算机' in page.input_value('#project-college')
                    assert not private.exists(), '项目预填不得自动写文件'
                    page.goto(base + '/admissions.html?' + target.replace('&track=ordinary', ''), wait_until='networkidle')
                    assert page.locator('[data-policy]').count() == 4, '原有全部范围浏览仍须工作'
                    assert page.locator('[data-checklist-field]').count() == 0
                    assert '招生范围' in page.locator('#checklist-prompt').inner_text()
                    page.select_option('#policy-track', 'special')
                    assert page.locator('[data-checklist-field="exams"] [data-checklist-policy]').count() == 3
                    assert '专项适用性仍待核实' in page.locator('#application-checklist').inner_text()
                    assert '408' not in page.locator('#application-checklist').inner_text()
                    page.select_option('#policy-program', '085400|菁英班')
                    assert '菁英班专属条件' in page.locator('#application-checklist').inner_text()
                    assert '工程硕博士专项专属条件' not in page.locator('#application-checklist').inner_text()
                    page.locator('#checklist-project').click()
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert '菁英班' in page.input_value('#project-type')
                    assert '工程硕博士' not in page.input_value('#project-type')
                    assert not private.exists()
                    page.goto(base + '/applications.html?school=unknown&dept=unknown&year=2027&degree=master&route=exam&track=special', wait_until='networkidle')
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert page.input_value('#project-school') == ''
                    assert page.input_value('#project-college') == ''
                    page.goto(base + '/admissions.html?' + target.replace('2027', '2028'), wait_until='networkidle')
                    assert page.locator('[data-checklist-field]').count() == 8
                    assert page.locator('[data-checklist-policy]').count() == 0
                    assert '待查' in page.locator('#application-checklist').inner_text()
                    assert page.locator('#unit-entries a').count() > 0
                    page.locator('#checklist-project').click()
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert page.input_value('#project-year') == '2028'
                    assert '清华' in page.input_value('#project-school')
                    assert '计算机' in page.input_value('#project-college')
                    assert '2028' in page.input_value('#project-notes')
                    assert not private.exists()
                    page.goto(base + '/admissions.html?' + target.replace('dept=cs', 'dept=wrong'), wait_until='networkidle')
                    assert page.locator('[data-checklist-field]').count() == 0
                    page.goto(base + '/admissions.html?' + target, wait_until='networkidle')
                    for status, mutation in [('changed', 'ADMISSIONS_DATA.checks.school_pdf.hash="changed"'), ('error', 'ADMISSIONS_DATA.checks.school_pdf.status="error"'), ('stale', 'ADMISSIONS_DATA.checks.school_pdf.status="ok";ADMISSIONS_DATA.checks.school_pdf.hash=ADMISSIONS_DATA.policies[0].review_hashes.school_pdf;ADMISSIONS_DATA.checks.school_pdf.last_success="2020-01-01"')]:
                        page.evaluate(mutation + ';render()')
                        assert page.locator('#application-checklist .quality.' + status).count() > 0
                        assert '需重新核对' in page.locator('#application-checklist').inner_text()
                    page.evaluate('ADMISSIONS_DATA.policies[0].fields.eligibility.text="<img src=x onerror=alert(1)>";render()')
                    assert page.locator('#application-checklist img').count() == 0
                    page.goto(base + '/admissions.html?school=seu&dept=auto&year=2027&degree=master&route=recommend&track=ordinary', wait_until='networkidle')
                    assert '该轮次已截止' in page.locator('#checklist-events').inner_text()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.screenshot(path=str(out / 'checklist-mobile-past.png'), full_page=True)
                    page.goto(base + '/admissions.html?' + target, wait_until='networkidle')
                    page.evaluate('scrollTo(0,document.getElementById("application-checklist").getBoundingClientRect().top+scrollY-110)')
                    page.screenshot(path=str(out / 'checklist-mobile.png'), full_page=True)
                    page.screenshot(path=str(out / 'checklist-mobile-viewport.png'))
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors, errors
                    offline = browser.new_page()
                    offline.goto((site / 'admissions.html').as_uri() + '?' + target, wait_until='load')
                    offline.wait_for_function('window.ADMISSIONS_READY === true')
                    assert offline.locator('[data-checklist-field]').count() == 8
                    print('PASS: checklist scope/layers/unknown/quality/past/links/prefill/no writes/XSS/390px/file mode')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    main()

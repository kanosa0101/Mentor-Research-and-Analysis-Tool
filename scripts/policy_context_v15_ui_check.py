"""政策卡到项目的公开目标上下文回归；仅临时 private。"""
import copy
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from admissions_v15_ui_check import fixture
from build_site import template_environment, write_html
from serve import create_server


def main():
    out = ROOT / 'cache/policy_v15/context_ui'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / 'site'
        site.mkdir()
        for name in ('admissions.js', 'admissions-core.js', 'ui.css', 'workflow.js'):
            shutil.copy2(ROOT / 'site' / name, site / name)
        data = fixture()
        data['policies'][0]['events'] = [{'label': '学校报名截止', 'kind': 'deadline', 'at': '2026-10-24T22:00:00+08:00', 'quote': '隔离测试学校日期', 'locator': '隔离学校总则'}]
        other = next(u for u in data['units'] if u['school'] != 'tsinghua' and u['dept'] == 'cs')
        data['policies'].append(dict(copy.deepcopy(data['policies'][0]), id='other-school', school=other['school']))
        (site / 'admissions-data.js').write_text('window.ADMISSIONS_DATA=' + json.dumps(data, ensure_ascii=False) + ';', encoding='utf-8')
        (site / 'data.js').write_text('window.MENTOR_DATA=[];', encoding='utf-8')
        for page in ('admissions', 'applications'):
            write_html(site / (page + '.html'), template_environment().get_template(page + '.html.j2').render())
        server = create_server(site=site, outreach=root / 'private/outreach.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port) + '/'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                def project_values():
                    page.wait_for_function('window.WORKFLOW_READY')
                    return {k: page.locator('#project-' + k).input_value() for k in ('school-id', 'dept-id', 'track', 'program-code', 'program-name', 'college', 'year')}
                def click_policy(policy, query):
                    page.goto(base + 'admissions.html?' + query, wait_until='networkidle')
                    page.wait_for_function('window.ADMISSIONS_READY')
                    card = page.locator('[data-policy="' + policy + '"]')
                    card.locator('summary').click()
                    link = card.get_by_role('link', name='建立申请项目 →')
                    href = link.get_attribute('href')
                    assert not any(k in href for k in ['project=', 'notes=', 'PRIVATE', 'name='])
                    link.click()
                    return project_values()
                query = 'school=tsinghua&dept=cs&year=2027&degree=master&route=exam&track=ordinary&program=085404%7C计算机技术&project=PRIVATE&notes=PRIVATE'
                values = click_policy('school-policy', query)
                assert values['dept-id'] == 'cs', ('school policy lost selected department', values)
                assert values['track'] == 'ordinary' and values['program-code'] == '085404' and values['program-name'] == '计算机技术', values
                assert values['college'] == next(u['dept_name'] for u in data['units'] if u['school'] == 'tsinghua' and u['dept'] == 'cs')
                assert page.locator('[data-add-policy-date]').count() == 1, 'ordinary complete scope may use generic school event'
                page.click('#project-save')
                page.wait_for_function('Object.keys(WORKFLOW.projects).length===1')
                saved = page.evaluate('Object.values(WORKFLOW.projects)[0]')
                assert saved['school_id'] == 'tsinghua' and saved['dept_id'] == 'cs' and saved['program_code'] == '085404'
                values = click_policy('school-policy', query.replace('track=ordinary', 'track=special').replace('085404%7C计算机技术', '085400%7C指定专项'))
                assert values['track'] == 'special' and values['program-name'] == '指定专项'
                assert page.locator('[data-add-policy-date]').count() == 0
                values = click_policy('program-policy', query)
                assert values['program-code'] == '085404'
                values = click_policy('other-school', query.replace('school=tsinghua', 'school=' + other['school']).replace('085404%7C计算机技术', '085405%7C软件工程'))
                assert values['school-id'] == other['school'] and values['dept-id'] == 'cs' and values['program-code'] == '085405'
                # Independent project landing rejects mismatched query context, not just card-generated URLs.
                for bad in ('school=' + other['school'] + '&dept=cs&year=2027&degree=master&route=exam', 'school=tsinghua&dept=wrong&year=2027&degree=master&route=exam'):
                    page.goto(base + 'applications.html?policy=school-policy&' + bad + '&track=special&program=085405%7C软件工程')
                    values = project_values()
                    assert values['school-id'] == 'tsinghua' and values['dept-id'] == '' and values['track'] == '' and values['program-code'] == '', values
                for bad in ('year=2026&degree=master&route=exam', 'year=2027&degree=phd&route=exam', 'year=2027&degree=master&route=recommend'):
                    page.goto(base + 'applications.html?policy=school-policy&school=tsinghua&dept=cs&' + bad + '&track=special&program=085405%7C软件工程')
                    values = project_values()
                    assert values['dept-id'] == 'cs' and values['year'] == '2027' and values['track'] == '' and values['program-code'] == '', values
                page.goto(base + 'applications.html?policy=program-policy&school=tsinghua&dept=cs&year=2027&degree=master&route=exam&track=special&program=085405%7C软件工程')
                values = project_values()
                assert values['track'] == 'ordinary' and values['program-code'] == '085404' and values['program-name'] == '计算机技术', values
                page.goto(base + 'applications.html?policy=named-school&school=tsinghua&dept=cs&year=2027&degree=master&route=exam&track=ordinary&program=085405%7C软件工程')
                values = project_values()
                assert values['track'] == 'special' and values['program-code'] == '085400' and values['program-name'] == '指定专项', values
                page.goto(base + 'applications.html?policy=school-policy')
                values = project_values()
                assert values['dept-id'] == '' and values['track'] == '' and values['program-code'] == ''
                values = click_policy('nankai-policy', 'school=nankai&year=2027&degree=master&route=exam&track=ordinary')
                assert values['school-id'] == 'nankai' and values['dept-id'] == '' and page.locator('[data-add-policy-date]').count() == 0
                assert not errors, errors
                browser.close()
            print('PASS: visible card→project→save, same-dept two-school isolation, ordinary/special/program/generic/no-unit and forged scope guards')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    main()

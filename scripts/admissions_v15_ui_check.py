"""分层覆盖/官方入口隔离验收；不读取或写入真实私人文件。"""
import copy
import json
import shutil
import sys
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.admissions_entries import load_catalog
from scripts.build_site import template_environment, write_html
from scripts.serve import create_server


def fixture():
    schools, _ = load_catalog(ROOT)
    units = []
    names = {s['id']: s['name'] for s in schools}
    for path in sorted((ROOT / 'sites').glob('*/*.yaml')):
        c = yaml.safe_load(path.read_text(encoding='utf-8'))
        if c['school'] in ('nankai', 'nudt'): continue  # 保留无单位学校与旧载荷兼容的隔离夹具。
        units.append({'school': c['school'], 'school_name': names[c['school']], 'dept': c['dept'],
                      'dept_name': c['dept_name'], 'groups': [], 'count': 0, 'roster_url': 'https://example.edu/faculty', 'notice_url': '',
                      'coverage': {'source_dates': {'known': 0, 'unknown': 0, 'earliest': '', 'latest': ''}}})
    today = date.today().isoformat()
    sources = {sid: {'url': 'https://example.edu/' + sid, 'label': label, 'format': 'html', 'selector': 'body'}
               for sid, label in [('school', '学校官方招生栏目'), ('failed', '院系官方招生栏目'), ('unchecked', '未检查入口'), ('stale', '过期入口')]}
    checks = {'school': {'status': 'ok', 'hash': 'a' * 64, 'last_attempt': today, 'last_success': today},
              'failed': {'status': 'error', 'hash': 'a' * 64, 'last_attempt': today, 'last_success': '2026-01-01', 'error': '测试离线'},
              'stale': {'status': 'ok', 'hash': 'a' * 64, 'last_attempt': today, 'last_success': (date.today() - timedelta(days=8)).isoformat()}}
    base = {'id': 'school-policy', 'school': 'tsinghua', 'dept': '', 'level': 'school', 'title': '仅学校通用规则',
            'year': 2027, 'degree': 'master', 'route': 'exam', 'track': 'general', 'program': '', 'program_code': '',
            'published_at': today, 'reviewed_at': today, 'source_id': 'school', 'review_hashes': {'school': 'a' * 64},
            'fields': {'materials': {'text': '学校通用材料；院系补充另查', 'quote': '材料', 'locator': '学校第三条'}}, 'events': []}
    program = dict(copy.deepcopy(base), id='program-policy', dept='cs', level='program', title='计算机技术专属规则', program='计算机技术', program_code='085404', track='ordinary')
    other = dict(copy.deepcopy(program), id='other-program', title='软件工程专属规则', program='软件工程', program_code='085405')
    named = [dict(copy.deepcopy(base), id='named-' + level, level=level, dept='' if level == 'school' else 'cs', title='命名专项' + level, track='special', program='指定专项', program_code='085400') for level in ('school', 'dept', 'program')]
    special = dict(copy.deepcopy(base), id='special-policy', dept='cs', level='dept', title='仅专项院系要求', track='special')
    pending = dict(copy.deepcopy(base), id='nankai-policy', school='nankai', title='南开学校统考规则', events=[{'label': '学校报名截止', 'kind': 'deadline', 'at': '2026-10-24T22:00:00+08:00', 'quote': '测试截止', 'locator': '隔离测试'}])
    entries = [dict(school='tsinghua', dept=dept, source_id=sid, reviewed_at=today, note=note)
               for dept, sid, note in [('', 'school', '学校章程及网报入口'), ('cs', 'failed', '院系材料须继续核查'), ('cs', 'unchecked', '等待首次回源'), ('cs', 'stale', '旧入口仍需复核')]]
    entries.append(dict(entries[0], school='nankai'))
    return {'version': 1, 'schools': schools, 'units': units, 'sources': sources, 'checks': checks,
            'groups': {}, 'entries': entries, 'policies': [base, program, other, special, pending] + named}


def main():
    out = ROOT / 'cache/policy_v15/coverage_ui'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / 'site'
        site.mkdir()
        for name in ('admissions.js', 'admissions-core.js', 'ui.css', 'workflow.js'):
            shutil.copy2(ROOT / 'site' / name, site / name)
        data = fixture()
        (site / 'admissions-data.js').write_text('window.ADMISSIONS_DATA=' + json.dumps(data, ensure_ascii=False) + ';', encoding='utf-8')
        write_html(site / 'admissions.html', template_environment().get_template('admissions.html.j2').render())
        write_html(site / 'applications.html', template_environment().get_template('applications.html.j2').render())
        (site / 'data.js').write_text('window.MENTOR_DATA=[];', encoding='utf-8')
        private = root / 'private'
        server = create_server(site=site, outreach=private / 'outreach.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port) + '/admissions.html?'
        query = 'school=tsinghua&dept=cs&year=2027&degree=master&route=exam&track=ordinary'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base + query, wait_until='networkidle')
                page.wait_for_function('window.ADMISSIONS_READY === true')
                assert page.locator('#policy-school option').count() == 40, '39配置学校含未接入院系的学校'
                layer = page.locator('#policy-layer-coverage')
                assert '学校规则已整理' in layer.inner_text()
                assert '院系附加要求未整理' in layer.inner_text(), '学校总则不能充当院系已覆盖'
                assert '专业未指定' in layer.inner_text() and '不计覆盖' in layer.inner_text()
                assert '仅专项院系要求' not in page.locator('#policy-list').inner_text()
                assert page.locator('#unit-entries a').first.get_attribute('href') == 'https://example.edu/school'
                failed = page.locator('[data-entry-source="failed"]')
                assert '回源失败' in failed.inner_text() and '历史最近成功' in failed.inner_text()
                assert '2026-01-01' in failed.inner_text()
                assert '尚未检查' in page.locator('[data-entry-source="unchecked"]').inner_text()
                assert '超过7天' in page.locator('[data-entry-source="stale"]').inner_text()
                assert '院系材料须继续核查' in failed.inner_text()
                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(out / f'layers-{width}.png'), full_page=True)
                page.select_option('#policy-program', '085404|计算机技术')
                assert '专业专属规则已整理' in layer.inner_text()
                assert page.locator('[data-policy=program-policy]').count() == 1
                assert page.locator('[data-policy=other-program]').count() == 0, '选择专业后隐藏其他专业规则'
                assert page.locator('[data-policy=school-policy]').count() == 1
                assert page.locator('#policy-program option').count() == 3, '专业过滤不缩掉其他可选专业'
                page.goto(base + query.replace('track=ordinary', 'track=special'))
                assert '学校通用规则对专项适用仍待核实' in page.locator('#policy-layer-coverage').inner_text()
                assert '仅专项院系要求' in page.locator('#policy-list').inner_text()
                assert '专业未指定' in layer.inner_text()
                page.select_option('#policy-program', '085400|指定专项')
                assert '专业专属规则已整理 · 3 条摘要' in layer.inner_text()
                assert '院系附加规则已整理 · 1 条摘要' in layer.inner_text()
                for level in ('school', 'dept', 'program'):
                    assert page.locator('[data-policy=named-' + level + ']').count() == 1
                page.goto(base + query.replace('dept=cs', 'dept=wrong'))
                assert page.locator('[data-policy]').count() == 0
                assert '院系未收录' in page.locator('#policy-layer-coverage').inner_text()
                assert page.locator('#unit-entries [data-entry-source]').count() == 0, '错误院系不能借入口冒充适用'
                page.goto(base + query.replace('&dept=cs', ''))
                assert '院系尚未选择' in page.locator('#policy-layer-coverage').inner_text()
                page.goto(base + 'school=nankai&year=2027&degree=master&route=exam&track=ordinary')
                assert page.locator('[data-policy="nankai-policy"]').count() == 1
                assert '院系目录待接入' in page.locator('#unit-description').inner_text()
                assert page.locator('#unit-mentors').is_hidden()
                assert page.locator('#unit-entries a').first.get_attribute('href') == 'https://example.edu/school'
                page.set_viewport_size({'width': 390, 'height': 844})
                page.screenshot(path=str(out / 'school-without-units-390.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                # Older generated fixtures lack schools/entries; valid unit navigation remains readable.
                legacy = copy.deepcopy(data)
                del legacy['schools']
                del legacy['entries']
                next(u for u in legacy['units'] if u['school'] == 'tsinghua' and u['dept'] == 'cs')['notice_url'] = 'https://example.edu/legacy-admissions'
                page.route('**/admissions-data.js*', lambda route: route.fulfill(content_type='application/javascript', body='window.ADMISSIONS_DATA=' + json.dumps(legacy, ensure_ascii=False) + ';'))
                page.goto(base + query)
                assert page.locator('#policy-school option').count() == 38
                assert '尚无独立来源检查记录' in page.locator('#unit-entries').inner_text()
                assert not errors, errors
                assert not private.exists(), '纯公开查看不写私人文件'
                page.unroute('**/admissions-data.js*')
                page.goto(base + 'school=nankai&year=2027&degree=master&route=exam&track=ordinary')
                page.locator('[data-policy=nankai-policy] summary').click()
                page.locator('[data-policy=nankai-policy] a', has_text='建立申请项目').click()
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.locator('#project-school-id option:checked').inner_text() == '南开大学'
                assert page.locator('#project-school').input_value() == '南开大学'
                assert page.locator('#project-dept-id').input_value() == ''
                assert page.locator('#project-dept-id option').count() == 1
                assert page.locator('[data-add-policy-date]').count() == 0
                page.click('#project-save')
                page.wait_for_function('Object.keys(WORKFLOW.projects).length===1')
                saved = page.evaluate('Object.values(WORKFLOW.projects)[0]')
                assert saved['school_id'] == 'nankai' and saved['dept_id'] == '' and saved['deadlines'] == []
                assert '南开大学' in page.locator('#project-list').inner_text()
                page.locator('[data-project-requirements]').click()
                assert '院系待补' in page.locator('#project-list').inner_text()
                page.locator('#project-list').screenshot(path=str(out / 'school-only-project-390.png'))
                page.locator('#project-list a', has_text='回查学校政策').click()
                assert page.locator('#policy-school').input_value() == 'nankai'
                assert page.locator('[data-policy=nankai-policy]').count() == 1
                assert not errors, errors
                browser.close()
            print('PASS: 39 configured schools / layered gaps / source state / special / invalid dept / no-unit school / program / 1440+390 / public browsing does not write private / isolated school-only project roundtrip')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    main()

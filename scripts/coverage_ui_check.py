"""CS相关院系覆盖、普通/专项与历史时间窗口验收，私人记录临时隔离。"""
import sys, tempfile, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from scripts.serve import create_server, SITE


def main():
    out = Path('cache/coverage_ui'); out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp) / 'private'
        server = create_server(outreach=private / 'outreach.yaml', port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/admissions.html?group=control', wait_until='networkidle')
                    assert '选择学校或院系' in page.locator('#unit-readiness').inner_text()
                    assert page.input_value('#policy-group') == 'control'
                    assert page.evaluate('visibleUnits.every(u=>u.groups.includes("control"))')
                    assert '自动化' in page.locator('#unit-directory-list').inner_text()
                    page.select_option('#policy-school', 'sjtu'); page.select_option('#policy-dept', 'auto')
                    info = page.locator('[data-unit-info="sjtu/auto"]')
                    assert info.count() == 1
                    assert all(label in info.inner_text() for label in ['公开邮箱', '明确研究方向', '官网简介', '导师资格', '来源抓取日期'])
                    assert '信息更新日期' not in info.inner_text()
                    assert 'school=sjtu' in info.locator('a').first.get_attribute('href')
                    page.evaluate('ADMISSIONS_DATA.units.find(u=>u.school==="sjtu"&&u.dept==="auto").roster_pending="试点名单范围待核对"; render()')
                    assert '试点名单范围待核对' in info.inner_text(), '有记录时也要展示名单完整性缺口'
                    page.evaluate('ADMISSIONS_DATA.units.find(u=>u.school==="sjtu"&&u.dept==="auto").roster_pending=""; render()')
                    page.locator('#unit-summary').screenshot(path=str(out / 'unit-information-desktop.png'))
                    page.fill('#policy-year', '2027'); page.locator('#policy-year').blur()
                    page.select_option('#policy-degree', 'master'); page.select_option('#policy-route', 'recommend')
                    page.select_option('#policy-track', 'ordinary')
                    assert page.locator('[data-policy]').count() == 0, '普通直硕不能借用专项规则'
                    page.select_option('#policy-track', 'special')
                    assert page.locator('[data-policy]').count() == 1
                    assert '该轮次已截止' in page.locator('#policy-list').inner_text()
                    assert '专项' in page.locator('#policy-list').inner_text()
                    page.locator('[data-policy] a').filter(has_text='建立申请项目').click()
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert '专项' in page.input_value('#project-type')
                    assert not (private / 'workflow.yaml').exists()
                    page.goto(base + '/admissions.html?school=seu&dept=auto&group=control&year=2027')
                    if page.evaluate('ADMISSIONS_DATA.units.find(u=>u.school==="seu"&&u.dept==="auto").count') == 0:
                        assert '待补' in page.locator('#unit-description').inner_text()
                    else:
                        assert page.locator('[data-unit-info="seu/auto"]').count() == 1
                    assert page.locator('[data-policy]').count() > 0
                    page.goto(base + '/discovery.html?group=cyber', wait_until='networkidle')
                    page.wait_for_function('window.DISCOVERY_READY === true')
                    assert page.evaluate('view.length>0&&view.every(r=>r.p.unit_groups.includes("cyber"))')
                    assert page.evaluate('view.some(r=>r.p.school==="buaa"&&r.p.dept==="cyber")')
                    page.screenshot(path=str(out / 'cyber-desktop.png'), full_page=False)
                    page.goto(base + '/admissions.html?school=tsinghua&dept=auto&year=2027&route=recommend')
                    assert '既往安排' in page.locator('#policy-list').inner_text()
                    assert page.locator('#unit-catalog a').count() > 0
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.locator('#unit-summary').screenshot(path=str(out / 'unit-information-mobile.png'))
                    page.screenshot(path=str(out / 'coverage-mobile.png'), full_page=False)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert not errors, errors
                    page.goto((SITE / 'admissions.html').as_uri() + '?group=cyber')
                    assert page.input_value('#policy-group') == 'cyber'
                    assert page.locator('#unit-directory-list button').count() > 0
                    print('PASS: CS groups/unit coverage/special scope/past dates/project/no private write/mobile/file mode')
                finally:
                    browser.close()
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=2)


if __name__ == '__main__':
    main()

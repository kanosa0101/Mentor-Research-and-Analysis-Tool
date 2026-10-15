"""学校政策流程验收；私人项目仅使用临时目录。"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from scripts.serve import create_server, SITE


def main():
    out = Path('cache/admissions_ui')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp) / 'private'
        server = create_server(outreach=private / 'outreach.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/admissions.html?school=tsinghua&dept=cs&year=2027&degree=master&route=exam', wait_until='networkidle')
                    page.wait_for_function('window.ADMISSIONS_READY === true')
                    assert page.locator('[data-policy]').count() == 2
                    assert '学校通用' in page.locator('#policy-list').inner_text()
                    assert '085400' in page.locator('#policy-list').inner_text()
                    page.locator('[data-policy="tsinghua-cs-2027-085400-exam"] .policy-body > summary').click()
                    assert '未整理' in page.locator('#policy-list').inner_text()
                    assert not (private / 'workflow.yaml').exists()
                    page.screenshot(path=str(out / 'admissions-desktop.png'), full_page=True)
                    page.locator('[data-policy="tsinghua-cs-2027-085400-exam"] a').filter(has_text='建立申请项目').click()
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert page.input_value('#project-year') == '2027'
                    assert page.input_value('#project-type') == '硕士 / 统考'
                    assert page.input_value('#project-school') == '清华大学'
                    assert '计算机' in page.input_value('#project-college')
                    assert '7195.htm' in page.input_value('#project-notes')
                    assert not (private / 'workflow.yaml').exists(), '预填不得写私人文件'
                    page.click('#project-save')
                    page.wait_for_function('Object.keys(WORKFLOW.projects).length === 1')
                    assert (private / 'workflow.yaml').exists()
                    page.goto(base + '/admissions.html?school=tsinghua&dept=cs&year=2027&degree=master&route=recommend')
                    assert page.locator('[data-policy]').count() == 2
                    page.locator('#unit-mentors').click()
                    page.wait_for_function('window.DISCOVERY_READY === true')
                    assert page.evaluate('view.every(row=>row.p.school==="tsinghua"&&row.p.dept==="cs")')
                    assert page.input_value('#intent-year') == '2027'
                    assert page.input_value('#intent-route') == 'recommend'
                    assert '院系' in page.locator('#unit-context').inner_text()
                    page.goto(base + '/admissions.html?school=pku&dept=cs&year=2027&degree=master&route=exam')
                    assert page.locator('[data-policy]').count() == 0
                    assert '未覆盖' in page.locator('#policy-list').inner_text()
                    assert page.locator('#unit-entries a').count() > 0
                    page.goto(base + '/admissions.html?school=tsinghua&dept=wrong&year=2027&route=exam')
                    assert page.locator('[data-policy]').count() == 0, '未知院系不能借用学校规则'
                    page.goto(base + '/admissions.html?school=tsinghua&year=2028&route=exam')
                    assert page.locator('[data-policy]').count() == 0
                    page.goto(base + '/admissions.html?school=tsinghua&dept=cs&year=unknown&route=exam')
                    assert page.locator('[data-policy]').count() == 0, '无效年度不能悄悄变成全部年度'
                    assert '无效年度' in page.locator('#policy-count').inner_text()
                    page.fill('#policy-year', '2027')
                    page.locator('#policy-year').blur()
                    assert page.locator('[data-policy]').count() == 2
                    page.goto(base + '/admissions.html?school=tsinghua&route=unknown')
                    assert '未知渠道' in page.locator('#policy-count').inner_text()
                    page.goto(base + '/notices.html?school=tsinghua/cs')
                    page.select_option('#school', 'pku/cs')
                    assert 'school=pku' in page.locator('#notice-policy-link').get_attribute('href')
                    page.select_option('#school', '')
                    assert page.locator('#notice-policy-link').get_attribute('href') == 'admissions.html'
                    page.goto(base + '/admissions.html?school=tsinghua&dept=cs&year=2027')
                    page.evaluate('ADMISSIONS_DATA.policies[0].fields.eligibility.text="<img src=x onerror=alert(1)>"; render()')
                    assert page.locator('#policy-list img').count() == 0
                    page.evaluate('ADMISSIONS_DATA.checks.school_pdf.hash="different"; render()')
                    assert '摘要待复核' in page.locator('#policy-list').inner_text()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(out / 'admissions-mobile.png'), full_page=True)
                    page.screenshot(path=str(out / 'admissions-mobile-viewport.png'), full_page=False)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors, errors
                    offline = browser.new_page()
                    offline.goto((SITE / 'admissions.html').as_uri() + '?school=tsinghua&dept=cs&year=2027')
                    offline.wait_for_function('window.ADMISSIONS_READY === true')
                    assert offline.locator('[data-policy]').count() == 4
                    print('PASS: layered policies/context/unknown/year/source-change/XSS/project prefill/no auto write/mobile/file mode')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    main()

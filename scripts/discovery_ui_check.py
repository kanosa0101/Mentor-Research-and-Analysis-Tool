"""条件找导师和全站主题验收，核验记录仅为临时测试数据。"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from scripts.serve import SITE, create_server


def main():
    out = Path('cache/discovery_ui')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        private = Path(tmp) / 'private'
        server = create_server(outreach=private / 'outreach.yaml', port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base) else r.fulfill(status=200, body='', content_type='image/png'))
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/discovery.html', wait_until='networkidle')
                    page.wait_for_function('window.DISCOVERY_READY === true')
                    page.locator('#advanced-criteria summary').click()
                    assert not (private / 'discovery.yaml').exists()
                    page.fill('#intent-year', '2027')
                    page.select_option('#intent-degree', 'master')
                    page.select_option('#intent-route', 'recommend')
                    page.fill('#intent-topics', '计算机视觉')
                    page.select_option('#mode-opportunity', 'hard')
                    page.click('#save-criteria')
                    page.wait_for_function('document.querySelector("#discovery-message").textContent.includes("已保存")')
                    assert page.locator('[data-candidate]').count() > 0
                    pid = page.locator('[data-candidate]').first.get_attribute('data-candidate')
                    page.locator('.candidate-application summary').first.click()
                    page.locator('[data-review]').first.click()
                    page.select_option('#review-opportunity', 'pass')
                    page.fill('#review-source', 'https://example.edu/notice/2027')
                    page.fill('#review-quote', '<img src=x onerror=alert(1)>临时测试记录，不是真实招生结论')
                    page.locator('#review-confirmed').check()
                    page.click('#review-save')
                    page.wait_for_function('Object.keys(PRIVATE.reviews).length === 1 && !document.querySelector("#review-panel").hidden === false')
                    page.locator('#keep-unknown').uncheck()
                    page.click('#apply-criteria')
                    page.wait_for_function('view.length === 1')
                    assert page.locator('#candidate-list img').count() == 0
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(out / 'discovery-desktop.png'), full_page=True)
                    page.fill('#intent-year', '2028')
                    page.click('#apply-criteria')
                    page.wait_for_function('view.length === 0')
                    assert '暂无候选' in page.locator('#candidate-list').inner_text()
                    page.fill('#intent-year', '2027')
                    page.click('#apply-criteria')
                    page.wait_for_function('view.length === 1')
                    with page.expect_download() as download:
                        page.click('#discovery-backup')
                    backup = Path(tmp) / 'discovery-backup.json'
                    download.value.save_as(str(backup))
                    page.reload(wait_until='networkidle')
                    page.wait_for_function('window.DISCOVERY_READY === true')
                    page.locator('#advanced-criteria summary').click()
                    assert page.input_value('#intent-year') == '2027'
                    assert page.evaluate('Object.keys(PRIVATE.reviews).length') == 1
                    page.locator('#keep-unknown').uncheck()
                    page.click('#apply-criteria')
                    page.wait_for_function('view.length === 1')
                    page.locator('.candidate-application summary').first.click()
                    page.locator('[data-candidate] a').filter(has_text='准备联系').click()
                    page.wait_for_url('**/desk.html?*')
                    page.wait_for_function('window.CONTACT_READY === true')
                    assert page.evaluate('new URLSearchParams(location.search).get("year")') == '2027'
                    page.locator('.site-tools summary').click()
                    page.click('#manage-link')
                    page.wait_for_url('**/applications.html?*')
                    assert page.input_value('#project-year') == '2027'
                    assert page.input_value('#project-degree') == 'master' and page.input_value('#project-route') == 'recommend'
                    assert '硕士' in page.input_value('#project-type') and '推免' in page.input_value('#project-type')
                    page.locator('#project-form details').filter(has=page.locator('#project-type')).locator('summary').click()
                    page.fill('#project-name', '临时非推免项目')
                    page.fill('#project-type', '硕士 / 统考（非推免）')
                    page.click('#project-save')
                    page.wait_for_function('Object.keys(WORKFLOW.projects).length === 1')
                    project = page.evaluate('Object.keys(WORKFLOW.projects)[0]')
                    assert page.evaluate('(id)=>WORKFLOW.projects[id].route', project) == 'recommend', '旧文本不能反推结构化渠道'
                    page.locator('[data-edit-project="' + project + '"]').click()
                    page.select_option('#project-route', 'exam')
                    page.select_option('#project-track', 'ordinary')
                    page.click('#project-save')
                    page.wait_for_function('(id)=>WORKFLOW.projects[id].route === "exam"', arg=project)
                    page.locator('[data-project-requirements="' + project + '"]').click()
                    project_contact = page.locator('article').filter(has=page.locator('[data-project-requirements="' + project + '"]')).get_by_role('link', name='到联系人工作台').get_attribute('href')
                    page.click('#back-desk')
                    page.wait_for_function('window.CONTACT_READY === true')
                    assert page.evaluate('currentTarget') == '', '无显式项目时，推免来访不能自动认领统考目标'
                    page.goto(base + '/' + project_contact, wait_until='networkidle')
                    page.wait_for_function('window.CONTACT_READY === true')
                    assert page.evaluate('(id)=>!target() || target().project_id === id', project), '显式项目不得借用其他项目目标'
                    assert page.evaluate('forwardedGoal().route') == 'exam', '保存的结构化渠道须随显式项目延续'
                    page.goto(base + '/notices.html?school=unknown/cs')
                    assert page.input_value('#school') == 'unknown/cs'
                    assert '未接入' in page.locator('#notice-context').inner_text()
                    assert page.locator('article:visible').count() == 0
                    page.select_option('#school', '')
                    assert page.locator('article:visible').count() > 0
                    for file in ['discovery.html', 'index.html', 'p/' + pid + '.html', 'compare.html', 'notices.html', 'admissions.html', 'desk.html', 'applications.html', 'board.html']:
                        page.goto(base + '/' + file, wait_until='domcontentloaded')
                        assert page.locator('header.site-header').count() == 1, file
                        assert page.locator('header.site-header nav > a').count() == 4, file
                        assert page.locator('.site-tools-menu a').count() == 4, file
                        if file == 'desk.html':
                            assert page.locator('#manage-link').count() == 1
                        if file == 'applications.html':
                            assert page.locator('#back-desk').count() == 1
                        assert page.evaluate('getComputedStyle(document.body).backgroundColor') == 'rgb(243, 244, 240)', file
                        page.set_viewport_size({'width': 390, 'height': 844})
                        page.screenshot(path=str(out / ('mobile-' + file.split('/')[0].replace('.html', '') + '.png')), full_page=False)
                        if not page.evaluate('document.documentElement.scrollWidth <= innerWidth'):
                            print('overflow:', file, page.evaluate('[...document.querySelectorAll("body *")].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(e=>e.tagName+"."+e.className)'))
                            raise AssertionError(file)
                        page.set_viewport_size({'width': 1440, 'height': 1000})
                    assert not errors, errors
                    offline = browser.new_page()
                    offline.goto((SITE / 'discovery.html').as_uri())
                    offline.wait_for_function('window.DISCOVERY_READY === true')
                    assert offline.locator('#save-criteria').is_disabled()
                    assert offline.locator('[data-candidate]').count() > 0
                    print('PASS: criteria/evidence/private review/year scope/backup/intent handoff/9 page theme/mobile/file mode')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    main()

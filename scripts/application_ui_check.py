"""申请工作台浏览器验收；只使用临时私人存储和材料。"""
import json
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site


def main():
    out = Path('cache/ux_v8/workflow/application')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        materials = root / 'materials'
        materials.mkdir()
        file = materials / 'letter.md'
        file.write_text('私有材料原文', encoding='utf-8')
        private = root / 'private'
        test_site = render_test_site(root)
        server = create_server(site=test_site, outreach=private / 'outreach.yaml', port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/applications.html', wait_until='networkidle')
                    assert page.locator('h1').inner_text() == '申请工作台'
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    pid = page.evaluate('window.MENTOR_DATA[0].page')
                    def choose_mentor(prefix):
                        page.fill('#' + prefix + '-mentor-query', pid)
                        page.locator('#' + prefix + '-mentor-results button').first.click()
                    page.fill('#project-name', '浏览器验收项目')
                    page.fill('#project-school', '测试学校')
                    page.fill('#project-year', '2027')
                    choose_mentor('project')
                    page.click('#project-save')
                    page.wait_for_function('Object.keys(WORKFLOW.projects).length === 1')
                    project = page.evaluate('Object.keys(WORKFLOW.projects)[0]')
                    page.locator('[data-edit-project="' + project + '"]').click()
                    page.select_option('#project-status', 'submitted')
                    page.click('#project-save')
                    page.wait_for_function('(id) => WORKFLOW.projects[id].status === "submitted"', arg=project)
                    page.click('[data-section="material"]')
                    page.fill('#scan-root', str(materials))
                    page.click('#scan-save')
                    page.wait_for_function('Object.keys(WORKFLOW.materials).length === 1')
                    mid = page.evaluate('Object.keys(WORKFLOW.materials)[0]')
                    page.locator('[data-edit-material="' + mid + '"]').click()
                    page.fill('#material-title', '<script>关联草稿</script>')
                    page.select_option('#material-kind', 'letter')
                    page.select_option('#material-projects', project)
                    choose_mentor('material')
                    page.click('#material-save')
                    page.wait_for_function('(Object.values(WORKFLOW.materials)[0].project_ids || []).length === 1')
                    assert page.locator('#material-list script').count() == 0
                    assert '<script>关联草稿</script>' in page.locator('#material-list').inner_text()
                    page.click('[data-section="communication"]')
                    choose_mentor('communication')
                    page.select_option('#communication-project', project)
                    page.select_option('#communication-materials', mid)
                    page.fill('#communication-subject', '首次草稿')
                    page.fill('#communication-content', '<img src=x onerror=alert(1)>私人内容')
                    page.select_option('#communication-kind', 'draft')
                    page.click('#communication-save')
                    page.wait_for_function('Object.keys(WORKFLOW.communications).length === 1')
                    page.click('[data-section="communication"]')
                    choose_mentor('communication')
                    page.fill('#communication-subject', '实际发送记录')
                    page.select_option('#communication-kind', 'sent')
                    page.click('#communication-save')
                    page.wait_for_function('Object.keys(WORKFLOW.communications).length === 2')
                    assert page.locator('#communication-list img').count() == 0
                    page.click('[data-section="reminder"]')
                    for title in ('准备材料', '后续联系'):
                        page.fill('#reminder-title', title)
                        page.fill('#reminder-due', '2026-01-01')
                        page.select_option('#reminder-project', project)
                        page.click('#reminder-save')
                        page.wait_for_function('(n) => Object.keys(WORKFLOW.reminders).length === n', arg=1 if title == '准备材料' else 2)
                    page.locator('[data-toggle-reminder]').first.click()
                    page.wait_for_function('Object.values(WORKFLOW.reminders).filter(r=>r.completed).length === 1')
                    page.locator('#only-pending').check()
                    assert page.locator('#reminder-list article').count() == 1
                    assert page.locator('#reminder-list .overdue').count() == 1
                    page.locator('#only-pending').uncheck()
                    pending = page.evaluate('Object.values(WORKFLOW.reminders).find(r=>!r.completed).id')
                    page.locator('[data-edit-reminder="' + pending + '"]').click()
                    page.fill('#reminder-due', '2026-01-02')
                    page.click('#reminder-save')
                    page.wait_for_function('(id) => WORKFLOW.reminders[id].due_date === "2026-01-02"', arg=pending)
                    assert page.evaluate('Object.values(WORKFLOW.reminders).filter(r=>r.completed).length') == 1
                    page.screenshot(path=str(out / 'desktop.png'), full_page=True)
                    page.reload(wait_until='networkidle')
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert page.locator('#communication-list article').count() == 2
                    file.unlink()
                    page.click('[data-section="material"]')
                    page.fill('#scan-root', str(materials))
                    page.click('#scan-save')
                    page.wait_for_function('Object.values(WORKFLOW.materials)[0].missing === true')
                    assert page.evaluate('Object.values(WORKFLOW.materials)[0].project_ids[0]') == project
                    with page.expect_download() as download:
                        page.click('#workflow-backup')
                    backup = root / 'backup.json'
                    download.value.save_as(str(backup))
                    data = json.loads(backup.read_text(encoding='utf-8'))
                    assert len(data['workflow']['communications']) == 2
                    page.on('dialog', lambda d: d.accept())
                    page.locator('#workflow-restore-file').set_input_files(str(backup))
                    page.wait_for_function('document.body.textContent.includes("已恢复工作台备份")')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '手机页面横向溢出'
                    page.screenshot(path=str(out / 'mobile.png'), full_page=True)
                    page.goto(base + '/applications.html?mentor=' + pid + '&panel=history', wait_until='networkidle')
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    assert page.locator('#context-mentor').inner_text()
                    assert 'panel=history' in page.locator('#back-desk').get_attribute('href')
                    assert page.locator('#communication-list article').count() == 2
                    assert not (private / 'outreach.yaml').exists(), '不应隐式修改套磁状态'
                    (private / 'workflow.yaml').write_text('version: [broken]\n', encoding='utf-8')
                    page.reload(wait_until='networkidle')
                    page.wait_for_function('document.querySelector("#message").textContent.includes("无法读取")')
                    assert page.locator('#workflow-restore').is_enabled(), '索引损坏时仍应允许恢复'
                    page.locator('#workflow-restore-file').set_input_files(str(backup))
                    page.wait_for_function('document.body.textContent.includes("已恢复工作台备份")')
                    assert page.locator('#communication-list article').count() == 2
                    assert not errors, errors
                    offline = browser.new_page()
                    offline.goto((test_site / 'applications.html').as_uri())
                    assert offline.locator('#service-hint').is_visible()
                    assert offline.locator('#project-save').is_disabled()
                    print('PASS: projects/material links/append history/multiple reminders/persistence/backup/mobile/file mode')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    main()

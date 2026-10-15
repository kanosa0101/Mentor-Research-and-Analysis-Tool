"""任务路径验收：临时私人记录与附件，不发送邮件。"""
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
    out = Path('cache/ux_v8/workflow/contact')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        materials_root = root / 'materials'
        materials_root.mkdir()
        cv = materials_root / 'cv.txt'
        cv.write_text('临时简历，不包含真实个人信息', encoding='utf-8')
        private = root / 'private'
        test_site = render_test_site(root)
        server = create_server(site=test_site, outreach=private / 'outreach.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(base + '/desk.html', wait_until='networkidle')
                    assert page.locator('h1').inner_text() == '我的申请'
                    page.wait_for_function('window.CONTACT_READY === true')
                    assert page.locator('#welcome').is_visible()
                    pid = page.evaluate('MENTOR_DATA[0].page')
                    page.goto(base + '/applications.html?mentor=' + pid, wait_until='networkidle')
                    page.wait_for_function('window.WORKFLOW_READY === true')
                    page.fill('#project-name', '真实路径验收项目')
                    page.fill('#project-year', '2027')
                    page.click('#project-save')
                    page.wait_for_function('Object.keys(WORKFLOW.projects).length === 1')
                    project = page.evaluate('Object.keys(WORKFLOW.projects)[0]')
                    page.click('[data-section="material"]')
                    page.fill('#material-path', str(cv))
                    page.select_option('#material-kind', 'cv')
                    page.click('#material-save')
                    page.wait_for_function('Object.keys(WORKFLOW.materials).length === 1')
                    page.click('#back-desk')
                    page.wait_for_url('**/desk.html?*')
                    assert page.evaluate('new URLSearchParams(location.search).get("mentor")') == pid
                    page.wait_for_function('window.CONTACT_READY === true')
                    assert page.locator('#context-name').inner_text()
                    assert page.evaluate('Object.values(FLOW.targets)[0].mentor_id') == pid
                    target = page.evaluate('Object.keys(FLOW.targets)[0]')
                    assert page.evaluate('(id)=>FLOW.targets[id].project_id', target) == project
                    page.click('[data-view="prepare"]')
                    page.fill('#draft-recipient', 'prof@example.edu')
                    page.fill('#draft-subject', '2027 硕士申请咨询')
                    page.fill('#draft-basis', '已核对官网方向，我的项目与该方向有关')
                    page.fill('#draft-body', '老师您好，这是我的真实项目介绍和申请咨询。')
                    page.locator('#draft-materials input').first.check()
                    page.click('#draft-save')
                    page.wait_for_function('Object.keys(FLOW.drafts).length === 1')
                    assert page.evaluate('Object.keys(FLOW.communications).length') == 0
                    with page.expect_download() as download:
                        page.click('#draft-export')
                    eml = root / 'draft.eml'
                    download.value.save_as(str(eml))
                    assert eml.stat().st_size > cv.stat().st_size
                    assert page.evaluate('Object.keys(FLOW.communications).length') == 0
                    assert page.locator('#draft-confirm').is_disabled()
                    # 已选附件缺失后必须可取消，而不是留下无法保存的锁定勾选。
                    cv.unlink()
                    page.evaluate('(folder)=>api("/scan",{root:folder},"POST")', str(materials_root))
                    page.reload(wait_until='networkidle')
                    page.wait_for_function('window.CONTACT_READY === true')
                    attachment = page.locator('#draft-materials input').first
                    assert attachment.is_checked()
                    assert attachment.is_enabled(), '已选缺失附件须允许取消'
                    attachment.uncheck()
                    page.click('#draft-save')
                    page.wait_for_function('Object.values(FLOW.drafts)[0].material_ids.length === 0')
                    cv.write_text('临时简历，不包含真实个人信息', encoding='utf-8')
                    page.evaluate('(folder)=>api("/scan",{root:folder},"POST")', str(materials_root))
                    page.reload(wait_until='networkidle')
                    page.wait_for_function('window.CONTACT_READY === true')
                    page.locator('#draft-materials input').first.check()
                    page.click('#draft-save')
                    page.wait_for_function('Object.values(FLOW.drafts)[0].material_ids.length === 1')
                    page.fill('#draft-body', '尚未保存的修改')
                    assert page.locator('#draft-export').is_disabled()
                    page.click('#draft-save')
                    page.wait_for_function('Object.values(FLOW.drafts)[0].body === "尚未保存的修改"')
                    page.locator('#sent-confirmed').check()
                    page.click('#draft-confirm')
                    page.wait_for_function('(id)=>FLOW.targets[id].stage === "waiting"', arg=target)
                    assert page.locator('#draft-body').is_disabled()
                    # 不同年度目标之间切换，未提交回复应可取消切换，确认后清空旧上下文。
                    other_project = page.evaluate('(pid)=>api("/projects",{name:"另一年度项目",year:2028,mentor_ids:[pid]},"POST")', pid)
                    page.evaluate('refresh()')
                    other_target = page.evaluate('(id)=>Object.values(FLOW.targets).find(t=>t.project_id===id).id', other_project['id'])
                    page.click('[data-panel="reply"]')
                    page.fill('#reply-content', '只属于第一位目标的回复')
                    page.fill('#reply-task', '第一位目标的下一步')
                    page.once('dialog', lambda d: d.dismiss())
                    page.click('[data-view="targets"]')
                    assert page.locator('#reply-content').input_value() == '只属于第一位目标的回复'
                    page.once('dialog', lambda d: d.accept())
                    page.click('[data-view="targets"]')
                    page.locator('[data-target="' + other_target + '"]').click()
                    assert page.locator('#reply-content').input_value() == ''
                    page.click('[data-view="targets"]')
                    page.locator('[data-target="' + target + '"]').click()
                    page.click('[data-panel="mail"]')
                    page.click('#draft-new')
                    page.fill('#draft-body', '必须保留的未保存内容')
                    page.once('dialog', lambda d: d.dismiss())
                    page.click('[data-view="targets"]')
                    assert page.locator('#draft-body').input_value() == '必须保留的未保存内容'
                    page.once('dialog', lambda d: d.accept())
                    page.click('#draft-new')
                    page.select_option('#draft-choice', page.evaluate('Object.keys(FLOW.drafts)[0]'))
                    page.click('[data-view="today"]')
                    assert page.locator('#waiting-list article').count() == 1
                    page.locator('[data-continue-target]').first.click()
                    assert page.locator('#reply-stage').input_value() == 'replied'
                    page.click('[data-panel="reply"]')
                    page.fill('#reply-content', '<img src=x onerror=alert(1)>请补充研究介绍')
                    page.select_option('#reply-stage', 'materials')
                    page.fill('#reply-task', '补充研究介绍')
                    page.fill('#reply-due', '2026-01-01')
                    page.click('#reply-save')
                    page.wait_for_function('(id)=>FLOW.targets[id].stage === "materials"', arg=target)
                    assert page.locator('#contact-history img').count() == 0
                    assert '请补充研究介绍' in page.locator('#contact-history').inner_text()
                    page.click('[data-view="today"]')
                    assert page.locator('#task-list article').count() == 1
                    page.screenshot(path=str(out / 'today-desktop.png'), full_page=True)
                    page.locator('[data-complete-task]').first.click()
                    page.wait_for_function('Object.values(FLOW.reminders)[0].completed === true')
                    page.click('[data-view="targets"]')
                    page.locator('[data-target]').first.click()
                    page.screenshot(path=str(out / 'prepare-desktop.png'))
                    page.reload(wait_until='networkidle')
                    page.wait_for_function('window.CONTACT_READY === true')
                    assert page.locator('#draft-body').input_value() == '尚未保存的修改'
                    assert page.locator('#draft-body').is_disabled()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), '手机横向溢出'
                    page.screenshot(path=str(out / 'prepare-mobile.png'))
                    with page.expect_download() as download:
                        page.click('#desk-backup')
                    backup = root / 'backup.json'
                    download.value.save_as(str(backup))
                    assert json.loads(backup.read_text(encoding='utf-8'))['version'] == 2
                    (private / 'workflow.yaml').write_text('broken: [', encoding='utf-8')
                    page.reload(wait_until='networkidle')
                    page.wait_for_function('document.querySelector("#desk-message").textContent.includes("无法读取")')
                    assert page.locator('#desk-restore').is_enabled()
                    page.on('dialog', lambda d: d.accept())
                    page.locator('#desk-restore-file').set_input_files(str(backup))
                    page.wait_for_function('window.CONTACT_READY === true')
                    assert page.evaluate('Object.keys(FLOW.communications).length') == 2
                    assert not (private / 'outreach.yaml').exists()
                    assert cv.read_text(encoding='utf-8') == '临时简历，不包含真实个人信息'
                    assert not errors, errors
                    offline = browser.new_page()
                    offline.goto((test_site / 'desk.html').as_uri())
                    assert offline.locator('#desk-hint').is_visible()
                    assert offline.locator('#draft-save').is_disabled()
                    print('PASS: detail context → project/material → draft → EML → explicit sent → reply/task → today → persistence/mobile/recovery/file mode')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()

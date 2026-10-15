"""Project-scoped materials/reminders actions; only temporary private records."""
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site


def main():
    out = ROOT / 'cache/ux_v11/project_actions'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        root = Path(tmp)
        folder = root / 'materials'
        folder.mkdir()
        server = create_server(site=render_test_site(root), outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/applications.html')
                page.wait_for_function('window.WORKFLOW_READY')
                a = page.evaluate('api("/projects",{name:"旧项目 A",school:"旧文本学校"},"POST")')['id']
                b = page.evaluate('api("/projects",{name:"项目 B"},"POST")')['id']
                materials = {}
                for pid, title in ((a, 'A 的简历'), (b, 'B 的材料')):
                    path = folder / (pid + '.txt')
                    path.write_text('temporary fixture', encoding='utf-8')
                    materials[pid] = page.evaluate('p=>api("/materials",p,"POST")', {'path': str(path), 'title': title, 'kind': 'cv', 'project_ids': [pid]})['id']
                    page.evaluate('p=>api("/reminders",p,"POST")', {'title': title + '提醒', 'project_id': pid, 'due_date': '2027-01-10'})
                (folder / (a + '.txt')).unlink()
                page.evaluate('root=>api("/scan",{root},"POST")', str(folder))
                page.evaluate('refresh()')
                page.goto(f'http://127.0.0.1:{server.server_port}/applications.html?project={a}&section=project')
                page.wait_for_function('window.WORKFLOW_READY')

                def open_requirements(pid):
                    page.click('[data-section="project"]')
                    page.select_option('#filter-project', '')
                    page.click(f'[data-project-requirements="{pid}"]')

                def action(pid, section):
                    return f'[data-project-section="{section}"][data-project-id="{pid}"]:not([data-edit-material])'

                open_requirements(a)
                card = page.locator(f'details:has(> [data-project-requirements="{a}"])')
                assert '结构化目标尚未完整' in card.inner_text()
                assert 'A 的简历' in card.inner_text() and 'B 的材料' not in card.inner_text()
                assert '索引标记文件缺失' in card.inner_text() and '简历' in card.inner_text()
                assert '请按官方要求核对文件内容' in card.inner_text()
                for width, height in ((1440, 1000), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), width
                    card.scroll_into_view_if_needed()
                    page.screenshot(path=str(out / f'project-actions-{width}.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                # A changed project form cannot be discarded by a shortcut silently.
                prior_url = page.url
                page.fill('#project-name', '尚未保存的项目')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.click(action(a, 'material'))
                assert page.input_value('#filter-project') == ''
                assert page.locator('#section-project').is_visible()
                assert page.input_value('#project-name') == '尚未保存的项目'
                assert page.url == prior_url
                # Accepting the same transition scopes both the list and new-file form.
                page.once('dialog', lambda dialog: dialog.accept())
                page.click(action(a, 'material'))
                assert page.input_value('#filter-project') == a
                assert page.locator('#section-material').is_visible()
                assert page.inner_text('#material-list').find('A 的简历') >= 0
                assert 'B 的材料' not in page.inner_text('#material-list')
                assert page.locator('#material-projects').evaluate('(e)=>[...e.selectedOptions].map(o=>o.value)') == [a]
                # A missing file can have its metadata/associations edited, without claiming compliance.
                open_requirements(a)
                page.click(f'[data-project-id="{a}"][data-edit-material="{materials[a]}"]')
                assert page.locator('#section-material').is_visible()
                assert page.input_value('#filter-project') == a
                assert page.input_value('#material-title') == 'A 的简历'
                assert page.locator('#material-path').get_attribute('readonly') is not None
                page.fill('#material-notes', '需要找回原文件')
                page.click('#material-save')
                page.wait_for_function('(id)=>WORKFLOW.materials[id].notes==="需要找回原文件"', arg=materials[a])
                assert page.evaluate('(id)=>WORKFLOW.materials[id].missing', materials[a])
                assert page.evaluate('(id)=>WORKFLOW.materials[id].notes', materials[b]) == ''
                open_requirements(b)
                page.click(action(b, 'material'))
                assert page.input_value('#filter-project') == b
                assert 'B 的材料' in page.inner_text('#material-list')
                assert 'A 的简历' not in page.inner_text('#material-list')
                # Cancel an edit shortcut before either scope or destination changes.
                open_requirements(a)
                page.fill('#project-name', '保留编辑')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.click(f'[data-project-id="{a}"][data-edit-material="{materials[a]}"]')
                assert page.input_value('#filter-project') == ''
                assert page.locator('#section-project').is_visible()
                assert page.input_value('#project-name') == '保留编辑'
                page.once('dialog', lambda dialog: dialog.accept())
                page.click(action(a, 'reminder'))
                assert page.locator('#section-reminder').is_visible()
                assert page.input_value('#filter-project') == a
                assert page.input_value('#reminder-project') == a
                assert 'A 的简历提醒' in page.inner_text('#reminder-list')
                assert 'B 的材料提醒' not in page.inner_text('#reminder-list')
                open_requirements(b)
                page.click(action(b, 'reminder'))
                assert page.input_value('#reminder-project') == b
                assert 'B 的材料提醒' in page.inner_text('#reminder-list')
                assert 'A 的简历提醒' not in page.inner_text('#reminder-list')
                assert f'project={b}' in page.url
                assert 'target=' not in page.url
                assert f'project={b}' in page.locator('#back-desk').get_attribute('href')
                assert 'target=' not in page.locator('#back-desk').get_attribute('href')
                page.reload()
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.input_value('#filter-project') == b
                assert page.locator('#section-reminder').is_visible()
                assert 'B 的材料提醒' in page.inner_text('#reminder-list')
                assert 'A 的简历提醒' not in page.inner_text('#reminder-list')
                # Re-enter through a real mentor target A, not just a project query.
                mentor = page.evaluate('MENTOR_DATA[0].page')
                target_a = page.evaluate('p=>api("/targets",p,"POST")', {'project_id': a, 'mentor_id': mentor})['id']
                page.evaluate('p=>api("/projects/"+p.id,{mentor_ids:[p.mentor]},"PATCH")', {'id': b, 'mentor': mentor})
                for destination in ('material', 'reminder'):
                    page.goto(f'http://127.0.0.1:{server.server_port}/applications.html?project={a}&target={target_a}&year=2029&school=pku&dept=cs&degree=phd&route=assessment&track=ordinary&section=project')
                    page.wait_for_function('window.WORKFLOW_READY')
                    assert page.input_value('#filter-project') == a
                    assert f'target={target_a}' in page.locator('#back-desk').get_attribute('href')
                    page.select_option('#filter-project', '')
                    page.click(f'[data-project-requirements="{b}"]')
                    before_url = page.url
                    before_back = page.locator('#back-desk').get_attribute('href')
                    page.fill('#project-name', '来自 A 的未保存编辑')
                    page.once('dialog', lambda dialog: dialog.dismiss())
                    page.click(action(b, destination))
                    assert page.url == before_url
                    assert page.locator('#back-desk').get_attribute('href') == before_back
                    assert page.input_value('#filter-project') == ''
                    assert page.locator('#section-project').is_visible()
                    assert page.input_value('#project-name') == '来自 A 的未保存编辑'
                    page.once('dialog', lambda dialog: dialog.accept())
                    page.click(action(b, destination))
                    assert page.input_value('#filter-project') == b
                    assert page.locator('#section-' + destination).is_visible()
                    assert f'project={b}' in page.url and 'target=' not in page.url and 'year=' not in page.url
                    back = page.locator('#back-desk').get_attribute('href')
                    assert f'project={b}' in back and 'target=' not in back and 'year=' not in back
                    assert page.input_value('#project-year') == ''
                    assert page.input_value('#project-school-id') == ''
                    page.reload()
                    page.wait_for_function('window.WORKFLOW_READY')
                    assert page.input_value('#filter-project') == b
                    assert page.locator('#section-' + destination).is_visible()
                    page.click('#back-desk')
                    page.wait_for_function('window.CONTACT_READY')
                    assert page.input_value('#target-project') == b
                    assert page.input_value('#targets-project') == b
                    assert f'target={target_a}' not in page.url
                    assert page.evaluate('target()?.project_id') in (None, b)
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    print('project_actions_v11_ui_check: PASS (project scope, missing-file edit, dirty cancellation, legacy goal, 390/1440)')


if __name__ == '__main__':
    main()

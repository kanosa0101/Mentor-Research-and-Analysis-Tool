"""Material discovery and explicit project association using temporary private data."""
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
    out = ROOT / 'cache/ux_v9/preparation'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / 'materials'
        folder.mkdir()
        for name in ('cv.txt', 'letter.txt'):
            (folder / name).write_text(name, encoding='utf-8')
        server = create_server(site=render_test_site(root), outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/applications.html?section=material')
                page.wait_for_function('window.WORKFLOW_READY')
                a = page.evaluate('api("/projects", {name:"项目 A"}, "POST")')['id']
                b = page.evaluate('api("/projects", {name:"项目 B"}, "POST")')['id']
                page.evaluate('refresh()')
                page.select_option('#filter-project', a)
                page.fill('#scan-root', str(folder))
                page.click('#scan-save')
                page.wait_for_function('Object.keys(WORKFLOW.materials).length===2')
                assert page.locator('#material-list article').count() == 0
                assert page.locator('#material-unassigned').count() == 1, 'scanned files need a visible unassigned-material entry point'
                assert '未关联任何项目' in page.inner_text('#material-feedback')
                page.click('#material-unassigned')
                assert page.locator('#material-list article').count() == 2
                assert page.evaluate('document.querySelector("#material-list").getBoundingClientRect().top < document.querySelector("#scan-form").getBoundingClientRect().top'), 'material results must precede registration forms'
                assert page.evaluate('document.activeElement.id === "material-list"'), 'view action must focus results'
                mid = page.evaluate('Object.keys(WORKFLOW.materials)[0]')
                mentor = page.evaluate('MENTOR_DATA[0].page')
                page.evaluate('({mid,mentor})=>api("/materials/"+mid,{mentor_ids:[mentor]},"PATCH")', {'mid': mid, 'mentor': mentor})
                page.evaluate('refresh()')
                assert page.locator('#material-list article').count() == 2, 'mentor-only materials are still unassigned to projects'
                page.fill('#material-title', '未保存标题')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.click('#material-current')
                assert page.locator('#material-list article').count() == 2
                assert page.input_value('#material-title') == '未保存标题'
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.click(f'[data-link-material="{mid}"]')
                assert page.input_value('#material-title') == '未保存标题'
                assert page.evaluate('(id)=>WORKFLOW.materials[id].project_ids', mid) == []
                page.once('dialog', lambda dialog: dialog.accept())
                page.click('#material-reset')
                page.route('**/api/workflow/materials/' + mid, lambda route: route.fulfill(status=400, content_type='application/json', body='{"error":"测试关联失败"}'))
                page.click(f'[data-link-material="{mid}"]')
                page.wait_for_function('document.querySelector("#material-feedback").textContent.includes("测试关联失败")')
                assert page.locator('#material-list article').count() == 2
                page.unroute('**/api/workflow/materials/' + mid)
                page.click(f'[data-link-material="{mid}"]')
                page.wait_for_function('(id)=>WORKFLOW.materials[id].project_ids.length===1', arg=mid)
                assert page.evaluate('(id)=>WORKFLOW.materials[id].mentor_ids', mid) == [mentor]
                assert page.locator('#material-list article').count() == 1
                page.click('#material-current')
                assert page.locator('#material-list article').count() == 1
                page.select_option('#filter-project', b)
                assert page.locator('#material-list article').count() == 0
                page.select_option('#filter-project', a)
                assert '手动登记' in page.inner_text('#project-context')
                assert '扫描仅登记文件' in page.inner_text('#project-context')
                page.click('#scan-save')
                page.wait_for_function('document.querySelector("#material-feedback").textContent.includes("扫描 2")')
                assert page.locator('#material-list article').count() == 1
                assert page.evaluate('(id)=>WORKFLOW.materials[id].project_ids', mid) == [a]
                assert '已登记 1' in page.inner_text('#material-summary')
                missing_path = page.evaluate('(id)=>WORKFLOW.materials[id].path', mid)
                Path(missing_path).unlink()
                page.click('#scan-save')
                page.wait_for_function('(id)=>WORKFLOW.materials[id].missing', arg=mid)
                assert '缺失 1' in page.inner_text('#material-summary')
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(out / 'materials-desktop.png'), full_page=True)
                page.set_viewport_size({'width': 390, 'height': 844})
                page.click('#material-unassigned')
                assert page.locator('#material-list').bounding_box()['y'] < 844, 'mobile result list must be immediately reachable'
                page.screenshot(path=str(out / 'materials-mobile-results.png'))
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(out / 'materials-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.select_option('#filter-project', '')
                page.click('#material-unassigned')
                assert page.locator('[data-link-material]').count() == 0
                assert '请先选择目标项目' in page.inner_text('#material-scope')
                assert not errors, errors
                browser.close()
                print('PASS: A scan 2, mentor-only unassigned discovery, explicit A association, B isolation, rescan, missing facts, dirty guard, failure feedback, 1440/390 screenshots')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()

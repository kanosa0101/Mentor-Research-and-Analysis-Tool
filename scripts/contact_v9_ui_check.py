"""Contact readiness and follow-up checks using temporary private records only."""
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site


def main():
    out = ROOT / 'cache/ux_v9/contact'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        server = create_server(site=render_test_site(root), outreach=root / 'private/outreach.yaml', port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(base + '/desk.html')
                page.wait_for_function('window.CONTACT_READY')
                ids = page.evaluate('MENTOR_DATA.slice(0,6).map(p=>p.page)')
                project = page.evaluate('api("/projects", {name:"临时联系验收",year:2027}, "POST")')
                targets = []
                for pid, stage in zip(ids, ['replied', 'materials', 'meeting', 'closed', 'waiting', 'preparing']):
                    targets.append(page.evaluate('(x)=>api("/targets", x, "POST")', {'project_id': project['id'], 'mentor_id': pid, 'stage': stage}))
                page.evaluate('(p)=>api("/reminders", {project_id:p,title:"项目级提醒",due_date:"2099-01-01"}, "POST")', project['id'])
                other = page.evaluate('api("/projects", {name:"另一申请项目",year:2028}, "POST")')
                page.evaluate('(x)=>api("/reminders", x, "POST")', {'project_id': other['id'], 'mentor_id': ids[0], 'title': '另一项目提醒', 'due_date': '2099-01-01'})
                page.evaluate('refresh()')
                assert page.locator('#unplanned-list article').count() == 3, 'reply/materials/meeting without mentor reminder must remain visible'
                page.evaluate('(id)=>chooseTarget(id)', targets[0]['id'])
                assert page.locator('#context-next').is_visible(), 'next step must be visible without expanding details'
                page.click('#draft-save')
                page.wait_for_function('!!currentDraft && !dirty && !document.getElementById("desk-workspace").disabled')
                assert page.locator('#draft-export').is_disabled()
                assert '邮件主题' in page.inner_text('#draft-readiness')
                for key, value in {'recipient': 'prof@example.edu', 'subject': '咨询', 'basis': '官网方向与真实项目', 'body': '您好，咨询研究机会。'}.items():
                    page.fill('#draft-' + key, value)
                assert '未保存' in page.inner_text('#draft-readiness')
                page.click('#draft-save')
                page.wait_for_function('!dirty && !document.getElementById("desk-workspace").disabled')
                assert page.locator('#draft-export').is_enabled()
                page.fill('#draft-body', '【待替换】')
                assert '占位' in page.inner_text('#draft-readiness')
                assert page.locator('#draft-export').is_disabled()
                page.fill('#draft-body', '真实经历。')
                (root / 'materials').mkdir()
                attachment = root / 'materials/sample.txt'
                attachment.write_text('temporary sample', encoding='utf-8')
                material = page.evaluate('(path)=>api("/materials", {title:"临时材料",path}, "POST")', str(attachment))
                page.click('#draft-save')
                page.wait_for_function('!dirty && !document.getElementById("desk-workspace").disabled')
                page.evaluate('loadDraft(currentDraft)')
                page.check('#draft-materials input[value="' + material['id'] + '"]')
                assert '附件选择尚未保存' in page.inner_text('#draft-readiness')
                assert page.locator('#draft-export').is_disabled()
                page.click('#draft-save')
                page.wait_for_function('!dirty && !document.getElementById("desk-workspace").disabled')
                attachment.unlink()
                page.evaluate('(root)=>api("/scan", {root}, "POST")', str(attachment.parent))
                page.evaluate('refresh()')
                assert '文件缺失' in page.inner_text('#draft-readiness')
                assert page.locator('#draft-export').is_disabled()
                page.uncheck('#draft-materials input[value="' + material['id'] + '"]')
                assert '文件缺失' not in page.inner_text('#draft-readiness')
                assert '未保存' in page.inner_text('#draft-readiness')
                page.click('#draft-save')
                page.wait_for_function('!dirty && !document.getElementById("desk-workspace").disabled')
                page.check('#sent-confirmed')
                page.click('#draft-confirm')
                page.wait_for_function('Object.values(FLOW.communications).some(e=>e.kind==="sent") && !document.getElementById("desk-workspace").disabled')
                assert page.locator('#draft-recipient').is_disabled()
                assert page.locator('#draft-export').is_disabled()
                page.click('[data-panel="reply"]')
                page.fill('#reply-content', '请补充材料')
                page.select_option('#reply-stage', 'materials')
                page.click('#reply-save')
                page.wait_for_function('!document.getElementById("desk-workspace").disabled')
                assert '未新增下一步' in page.inner_text('#reply-status')
                page.click('#context-task-link')
                page.fill('#task-title', '整理材料')
                page.fill('#task-due', '2099-02-01')
                page.click('#task-save')
                page.wait_for_function('!document.getElementById("desk-workspace").disabled')
                assert '整理材料' in page.inner_text('#context-next')
                assert page.locator('#unplanned-list article').count() == 2
                page.click('[data-task-toggle]')
                page.wait_for_function('!document.getElementById("desk-workspace").disabled')
                assert page.locator('#unplanned-list article').count() == 3
                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    page.click('[data-view="today"]')
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(out / f'today-{width}-viewport.png'))
                    page.screenshot(path=str(out / f'today-{width}.png'), full_page=True)
                    page.click('[data-view="prepare"]')
                    page.click('[data-panel="mail"]')
                    page.click('#draft-new')
                    assert not page.inner_text('#draft-status')
                    assert page.locator('#context-next').is_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(out / f'prepare-{width}-viewport.png'))
                    page.screenshot(path=str(out / f'prepare-{width}.png'), full_page=True)
                assert not errors, errors
                people = page.evaluate('MENTOR_DATA')
                first = people[0]
                other_person = next(p for p in people if (p['school'], p['dept']) != (first['school'], first['dept']))
                ordinary = page.evaluate('api("/projects", {name:"普通项目",year:2027,application_type:"硕士 / 推免"}, "POST")')
                ordinary_target = page.evaluate('(x)=>api("/targets", x, "POST")', {'project_id': ordinary['id'], 'mentor_id': first['page']})
                other_target = page.evaluate('(x)=>api("/targets", x, "POST")', {'project_id': ordinary['id'], 'mentor_id': other_person['page']})
                scope = dict(mentor=first['page'], school=first['school'], dept=first['dept'], year=2027, degree='master', route='recommend', track='special', program='0854|special')
                page.goto(base + '/desk.html?' + urlencode(scope))
                page.wait_for_function('window.CONTACT_READY')
                assert page.evaluate('currentTarget') == '', 'specific admission scope must not auto-select ordinary private project'
                assert page.locator('#incoming-goal').is_visible()
                page.evaluate('(id)=>chooseTarget(id)', other_target['id'])
                for url in (page.url, page.evaluate('manageUrl()')):
                    query = parse_qs(urlsplit(url).query)
                    assert query['school'] == [other_person['school']] and query['dept'] == [other_person['dept']]
                    assert 'track' not in query and 'program' not in query
                assert page.locator('#incoming-goal').is_visible()
                page.goto(base + '/desk.html?' + urlencode({**scope, 'target': other_target['id']}))
                page.wait_for_function('window.CONTACT_READY')
                assert page.evaluate('currentTarget') == other_target['id']
                assert 'program=' not in page.url
                assert parse_qs(urlsplit(page.url).query)['dept'] == [other_person['dept']]
                page.goto(base + '/desk.html?' + urlencode({**scope, 'track': 'general', 'program': ''}))
                page.wait_for_function('window.CONTACT_READY')
                assert page.evaluate('currentTarget') == '', 'general scope also cannot establish private project equivalence'
                page.goto(base + '/desk.html?' + urlencode({**scope, 'dept': 'mismatched-department'}))
                page.wait_for_function('window.CONTACT_READY')
                assert 'program=' not in page.url and 'track=' not in page.url
                assert '来访单位与当前导师不符' in page.inner_text('#incoming-goal')
                page.goto(base + '/desk.html?' + urlencode({key: value for key, value in scope.items() if key not in ('school', 'dept')}))
                page.wait_for_function('window.CONTACT_READY')
                assert 'program=' not in page.url and 'track=' not in page.url
                assert '无法确定适用院系' in page.inner_text('#incoming-goal')
                page.goto(base + '/desk.html?' + urlencode(dict(mentor=first['page'], school=first['school'], dept=first['dept'])))
                page.wait_for_function('window.CONTACT_READY')
                assert '来访申请意向：。' not in page.inner_text('#incoming-goal')
                browser.close()
                print('PASS: readiness, dirty/sent drafts, follow-up visibility, project reminder isolation, admission scope isolation, 1440/390')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    main()

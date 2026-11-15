"""Real local saves in isolated storage, plus desktop/mobile opportunity discovery."""
import json
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server
from crawler import opportunity_util
from scripts.release_page_v1_ui_check import signatures


def main():
    out = ROOT / 'cache/opportunities_v1_1_ui'
    out.mkdir(parents=True, exist_ok=True)
    before = signatures()
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [1440, 390]:
            with tempfile.TemporaryDirectory() as tmp:
                server = create_server(outreach=Path(tmp)/'private/outreach.yaml', port=0)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                base = f'http://127.0.0.1:{server.server_port}'
                page = browser.new_page(viewport={'width': width, 'height': 900})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                try:
                    page.route('**/*', lambda r: r.continue_() if r.request.url.startswith(base+'/') else r.abort())
                    page.goto(base+'/opportunities.html', wait_until='networkidle')
                    assert page.locator('[data-opportunity]').count() == sum(opportunity_util.state(o)!='closed' for o in opportunity_util.load(ROOT)['opportunities'])
                    assert '待复核' in page.locator('[data-opportunity="ihep-winter-2027"]').inner_text()
                    assert page.locator('.opportunity-state.open').count() == 0
                    assert '最近检查' in page.locator('#monitor-health').inner_text() or '尚无监测记录' in page.locator('#monitor-health').inner_text()
                    assert not list((Path(tmp)/'private').glob('*')), 'GET created private files'
                    page.screenshot(path=str(out/f'opportunities-{width}.png'), full_page=True)
                    page.locator('#opportunity-state').select_option('closed')
                    assert page.locator('[data-opportunity]').count() == 7
                    page.locator('#opportunity-state').select_option('open')
                    assert page.locator('[data-opportunity]').count() == 0
                    page.locator('#opportunity-reset').click()
                    page.locator('[data-save-opportunity="ihep-winter-2027"]').click()
                    assert page.locator('#opportunity-save').is_visible()
                    page.locator('#opportunity-name').fill('验收活动项目')
                    page.locator('#opportunity-reminder').fill(page.locator('#opportunity-reminder').get_attribute('min'))
                    page.locator('#opportunity-confirm').click()
                    page.wait_for_function("!document.querySelector('#opportunity-save').open")
                    data=page.request.get(base+'/api/workflow').json()
                    assert len(data['projects']) == len(data['reminders']) == 1
                    project=next(iter(data['projects'].values()))
                    assert project['opportunity']['id']=='ihep-winter-2027'
                    assert project['year'] is None and project['route']==''
                    assert next(iter(data['reminders'].values()))['title'].startswith('核对活动信息')
                    page.locator('#opportunity-result a').click()
                    page.wait_for_function('window.WORKFLOW_READY')
                    assert page.get_by_text('活动条件与准备材料', exact=False).is_visible()
                    assert '入选后' in page.locator('body').inner_text() or '报名时' in page.locator('body').inner_text()
                    material=Path(tmp)/'resume.txt';material.write_text('UI fixture', encoding='utf-8')
                    response=page.request.post(base+'/api/workflow/materials',data=dict(path=str(material),title='验收简历',kind='cv',project_ids=[project['id']]))
                    assert response.ok,response.text()
                    page.reload(wait_until='networkidle');page.wait_for_function('window.WORKFLOW_READY')
                    assert page.get_by_text('验收简历 · 已登记文件，不代表已提交').is_visible()
                    page.screenshot(path=str(out/f'project-{width}.png'),full_page=True)
                    backup=page.request.get(base+'/api/workflow/backup').json()
                    assert page.request.post(base+'/api/workflow/restore',data=backup).ok
                    restored=page.request.get(base+'/api/workflow').json()
                    assert restored['projects'][project['id']]['opportunity']==project['opportunity']
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    assert not errors,errors
                    results.append(dict(width=width,passed=True,private_project_count=1,reminder_count=1,errors=errors))
                finally:
                    page.close();server.shutdown();server.server_close()
        browser.close()
    assert signatures()==before
    (out/'results.json').write_text(json.dumps({'passed':True,'private_unchanged':True,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS opportunities 1440/390: source states, history, save, reminder, materials, backup/restore, private boundary')


if __name__=='__main__':main()

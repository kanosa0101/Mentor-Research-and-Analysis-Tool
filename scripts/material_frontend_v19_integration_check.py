"""Real public-policy v19 UI/API integration, with temporary projects and material files only."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.request import Request,urlopen
from jinja2 import Environment,FileSystemLoader
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.serve import create_server


def main():
    public=json.loads((ROOT/'site/admissions-data.js').read_text(encoding='utf-8-sig').split('=',1)[1].strip().rstrip(';'))
    selected=[]
    for degree in (sys.argv[1:] or ['master','phd']):
        candidates=[p for p in public['policies'] if p.get('degree')==degree and p.get('material_actions')]
        assert candidates,f'Build merged {degree} policies before running integration'
        selected.append(next((p for p in candidates if p.get('dept') and not p.get('applies_if')),candidates[0]))
    output=ROOT/'cache/policy_v19/material_frontend';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);site=root/'site';site.mkdir()
        for name in ['workflow.js','material-actions.js','data.js','admissions-data.js','admissions-core.js','admissions.js','ui.css']:
            shutil.copyfile(ROOT/'site'/name,site/name)
        env=Environment(loader=FileSystemLoader(ROOT/'site/templates'))
        for name in ['applications','admissions']:(site/(name+'.html')).write_text(env.get_template(name+'.html.j2').render(),encoding='utf-8')
        server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0)
        threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
        def request(path='',body=None,method=None):
            raw=None if body is None else json.dumps(body).encode()
            req=Request(base+'/api/workflow'+path,data=raw,method=method or ('GET' if body is None else 'POST'),headers={'Content-Type':'application/json','Origin':base})
            with urlopen(req) as response:return json.load(response)
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                for policy in selected:
                    dept=policy.get('dept') or next(u['dept'] for u in public['units'] if u['school']==policy['school'])
                    goal=dict(school_id=policy['school'],dept_id=dept,year=policy['year'],degree=policy['degree'],route=policy['route'],track='ordinary' if policy.get('track','general')=='general' else policy['track'],program_code=policy.get('program_code',''),program_name=policy.get('program',''))
                    project=request('/projects',dict(name='临时UI验证'+policy['degree'],**goal));pid=project['id']
                    material=root/(policy['degree']+'-cv.txt');material.write_text('private temporary fixture',encoding='utf-8')
                    request('/materials',dict(title='临时验证简历',path=str(material),kind='cv',project_ids=[pid],mentor_ids=[],notes='测试文件'))
                    page.goto(base+'/applications.html?project='+pid+'&section=preparation');page.wait_for_function('window.WORKFLOW_READY')
                    page.wait_for_selector('[data-material-action]',state='attached')
                    views=request('/material-tasks')['actions'][pid];index=next(i for i,v in enumerate(views) if v['can_record']);row=views[index]
                    form=page.locator(f'[data-material-action="{index}"]')
                    form.locator('xpath=..').locator(':scope > summary').click()
                    form.locator('[name="material_ids"]').check();form.locator('[name="status"]').select_option('prepared');form.locator('[name="notes"]').fill('仅临时UI验证，未发送材料')
                    if row['conditions']:form.locator('[name="confirmed_conditions"]').check()
                    form.locator('[type="submit"]').click();page.wait_for_function('!MaterialPreparation.isDirty()');page.wait_for_load_state('networkidle')
                    snapshot=request('/material-tasks');record=next(r for r in snapshot['records'].values() if r['project_id']==pid)
                    assert record['status']=='prepared' and record['files'][0]['state']=='unchanged'
                    page.wait_for_function('(i)=>document.querySelector(`[data-material-action="${i}"]`).closest(".preparation-action").textContent.includes("最近人工登记：已准备")',arg=index)
                    if policy['degree']=='master':
                        conditional_index=next(i for i,v in enumerate(views) if v['conditions'])
                        condition=views[conditional_index]['conditions'][0]['evidence']
                        page.locator(f'[data-material-action="{conditional_index}"]').locator('xpath=..').locator(':scope > summary').click()
                        assert condition['text'] in page.locator(f'[data-material-action="{conditional_index}"]').locator('xpath=..').locator('xpath=..').inner_text()
                        assert condition['quote'] in page.locator(f'[data-material-action="{conditional_index}"]').locator('xpath=..').locator('xpath=..').inner_text()
                        assert not page.locator(f'[data-material-action="{conditional_index}"] [name="confirmed_conditions"]').is_checked()
                        assert '6112' in page.inner_text('#preparation-list')
                    if row['events']:
                        history=page.locator(f'[data-material-action="{index}"]').locator('xpath=..').locator('[data-material-history]')
                        if not history.evaluate('e=>e.open'):history.locator(':scope > summary').click()
                        history.locator('[data-material-reminder]').click()
                        page.wait_for_function('document.querySelector("#preparation-feedback").textContent.includes("登记项目提醒")')
                        reminder=next(r for r in request()['reminders'].values() if r['project_id']==pid)
                        assert row['events'][0]['event']['at'] in reminder['notes']
                        assert row['events'][0]['source_url'] in reminder['notes']
                        assert row['events'][0]['event']['quote'] in reminder['notes']
                    # Verify the actual original-source link opens its exact registered destination.
                    # Navigation response is stubbed; source authenticity/content is audited separately.
                    source_id=row['action']['instruction'].get('source_ids',[policy['source_id']])[0]
                    source_url=public['sources'][source_id]['url']
                    source_link=page.locator(f'[data-material-action="{index}"]').locator('xpath=..').locator(f'a[href="{source_url}"]').first
                    assert source_link.get_attribute('target')=='_blank'
                    page.context.route(source_url,lambda route:route.fulfill(content_type='text/html',body='<title>Official source navigation fixture</title>'))
                    with page.expect_popup() as popup_info:source_link.click()
                    popup=popup_info.value;popup.wait_for_load_state();assert popup.url==source_url;popup.close()
                    page.context.unroute(source_url)
                    page.screenshot(path=str(output/(policy['degree']+'-real-1440.png')),full_page=True)
                    page.evaluate('scrollTo(0,0)');page.screenshot(path=str(output/(policy['degree']+'-real-1440-viewport.png')))
                    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/(policy['degree']+'-real-390.png')),full_page=True)
                    page.evaluate('scrollTo(0,0)');page.screenshot(path=str(output/(policy['degree']+'-real-390-viewport.png')))
                    page.locator('.preparation-action').first.scroll_into_view_if_needed();page.screenshot(path=str(output/(policy['degree']+'-real-390-actions-viewport.png')))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    backup=request('/backup');assert backup['version']==4 and record['id'] in backup['workflow']['material_tasks']
                    material.write_text('changed temporary fixture bytes',encoding='utf-8')
                    page.evaluate('refresh()');page.wait_for_timeout(100)
                    changed=request('/material-tasks')['records'][record['id']];assert changed['review_required'] and changed['files'][0]['state']=='changed'
                    request('/restore',backup);restored=request('/material-tasks')['records'][record['id']];assert restored['files'][0]['state']=='changed'
                    page.set_viewport_size({'width':1440,'height':1000})
                # Public page uses actual merged materials actions; no private API access.
                private=[];page.on('request',lambda r:private.append(r.url) if '/api/workflow' in r.url else None)
                page.goto(base+'/admissions.html');page.wait_for_selector('.material-actions');assert not private
                assert page.locator('.material-actions').count()>=2
                assert not errors,errors
                browser.close()
        finally:server.shutdown();server.server_close()
    print('PASS real master/phd: prepare/save/history/file-version/backup-restore at 1440/390; public actions without private API')


if __name__=='__main__':main()

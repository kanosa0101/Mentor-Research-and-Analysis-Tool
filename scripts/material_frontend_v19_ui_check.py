"""v19 front-end fixture regression: temporary static site, intercepted private API only."""
import copy
import json
import shutil
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent


def main():
    output=ROOT/'cache/policy_v19/material_frontend';output.mkdir(parents=True,exist_ok=True)
    public=json.loads((ROOT/'site/admissions-data.js').read_text(encoding='utf-8-sig').split('=',1)[1].strip().rstrip(';'))
    policy=public['policies'][0]
    goal=dict(school_id=policy['school'],dept_id=policy.get('dept',''),year=policy['year'],degree=policy['degree'],route=policy['route'],track=policy.get('track','ordinary'),program_code='',program_name='')
    workflow=dict(version=3,projects={pid:dict(id=pid,name='申请项目'+pid,status='planned',mentor_ids=[],notes='',deadlines=[],**goal) for pid in ['A','B']},materials={'file':dict(id='file',title='同一份简历',path='C:/fixture/cv.pdf',size=12,mtime='2026-10-15',missing=False,project_ids=['A','B'],mentor_ids=[],kind='cv',notes='')},communications={},reminders={})
    instruction=dict(text='在申请系统上传合并PDF，面试时另带原件。',quote='上传合并PDF',locator='测试第二段')
    action=dict(id='upload',label='上传申请PDF',stage='application',instruction=instruction)
    event=dict(label='材料截止',at='2027-01-05',kind='deadline',quote='1月5日前',locator='测试日期')
    def view(a):
        return dict(policy_id=policy['id'],policy_title='合成材料政策',action_id=a['id'],action=a,action_fingerprint='original-'+a['id'],goal_snapshot=goal,conditions=[],program_pending=False,quality=dict(state='checked',label='测试来源版本一致'),events=[dict(event_index=0,event=event,source_url='https://example.edu/notice')],latest_record_id=None)
    second=dict(action,id='originals',label='携带原件',stage='interview')
    data=dict(version=1,actions={pid:[view(action),view(second)] for pid in ['A','B']},records={})
    writes=[];conflict=[False];offline=[False]
    def route_api(route):
        request=route.request;path=request.url.split('/api/workflow',1)[1]
        if path=='':result=workflow
        elif path=='/material-tasks' and request.method=='GET':
            if offline[0]:route.fulfill(status=503,json={'error':'fixture offline'});return
            result=data
        elif path=='/material-tasks':
            body=request.post_data_json;writes.append(body)
            if conflict[0]:route.fulfill(status=409,json={'error':'action changed'});return
            assert body['expected_action'].startswith('original-')
            rid='record-'+str(len(writes));row=next(v for v in data['actions'][body['project_id']] if v['action_id']==body['action_id'])
            result=dict(body,id=rid,created_at='2026-10-15T12:00:00',action=row['action'],policy_title=row['policy_title'],goal_snapshot=goal,source_snapshot={},files=[dict(material_id='file',title='同一份简历',path='C:/fixture/cv.pdf',size=12,mtime='2026-10-15',sha256='a'*64,state='unchanged')],applicable=True,review_required=False,review_reasons=[])
            data['records'][rid]=result;row['latest_record_id']=rid
        elif path.endswith('/reminders'):
            assert request.post_data_json['event_index']==0
            writes.append(dict(reminder=request.post_data_json))
            result=dict(id='reminder-fixture',duplicate=False)
        else:raise AssertionError(path)
        route.fulfill(json=copy.deepcopy(result))
    with tempfile.TemporaryDirectory() as tmp:
        site=Path(tmp)
        for name in ['workflow.js','material-actions.js','data.js','admissions-data.js','admissions-core.js','ui.css']:
            shutil.copyfile(ROOT/'site'/name,site/name)
        env=Environment(loader=FileSystemLoader(ROOT/'site/templates'))
        (site/'public-material.html').write_text('<div id="public"></div><script src="admissions-data.js"></script><script src="admissions-core.js"></script><script src="material-actions.js"></script>',encoding='utf-8')
        (site/'applications.html').write_text(env.get_template('applications.html.j2').render(),encoding='utf-8')
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=tmp))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                for width in [1440,390]:
                    page=browser.new_page(viewport={'width':width,'height':1000});errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/api/workflow**',route_api)
                    page.goto(f'http://127.0.0.1:{server.server_port}/applications.html?section=preparation');page.wait_for_function('window.WORKFLOW_READY')
                    page.select_option('#filter-project','A');page.wait_for_selector('[data-material-action="0"]',state='attached')
                    form=page.locator('[data-material-action="0"]')
                    form.locator('xpath=..').locator(':scope > summary').click()
                    form.locator('[name="material_ids"]').check();form.locator('[name="notes"]').fill('未保存甲')
                    page.once('dialog',lambda d:d.dismiss());page.click('[data-section="reminder"]');assert page.locator('#section-preparation').is_visible()
                    page.once('dialog',lambda d:d.dismiss());page.select_option('#filter-project','B');assert page.input_value('#filter-project')=='A'
                    # Unrelated refresh cannot overwrite inputs or silently update their expected fingerprint.
                    data['actions']['A'][0]['action_fingerprint']='changed-upload'
                    page.evaluate('refresh()');page.wait_for_timeout(150);assert form.locator('[name="notes"]').input_value()=='未保存甲'
                    conflict[0]=True;form.locator('[type="submit"]').click();page.wait_for_function('document.querySelector("#preparation-feedback").textContent.includes("输入已保留")');assert writes[-1]['expected_action']=='original-upload'
                    assert form.locator('[name="notes"]').input_value()=='未保存甲'
                    conflict[0]=False;data['actions']['A'][0]['action_fingerprint']='original-upload'
                    form.locator('[type="submit"]').click();page.wait_for_function('!MaterialPreparation.isDirty()');page.wait_for_timeout(100)
                    assert data['records'][next(reversed(data['records']))]['project_id']=='A'
                    # Current record can create only an explicitly bound event reminder.
                    history=page.locator('.preparation-action').first.locator('[data-material-history]')

                    if not history.evaluate('e=>e.open'):history.locator(':scope > summary').click()
                    history.locator('[data-material-reminder]').last.click()
                    page.wait_for_function('document.querySelector("#preparation-feedback").textContent.includes("登记项目提醒")')
                    assert 'reminder' in writes[-1]
                    record=data['records'][next(reversed(data['records']))];record['files'][0]['state']='missing';record['review_reasons']=['files_changed'];record['review_required']=True
                    page.evaluate('refresh()');page.wait_for_timeout(100)
                    history=page.locator('.preparation-action').first.locator('[data-material-history]')
                    if not history.evaluate('e=>e.open'):history.locator(':scope > summary').click()
                    assert '所用文件版本需复核' in history.inner_text()
                    assert history.locator('[data-material-reminder]').last.is_enabled()
                    assert '文件仍需复核' in history.locator('[data-material-reminder]').last.inner_text()
                    # Saving one action must preserve unsaved input in a second action.
                    page.locator('[data-material-action="0"] [name="notes"]').fill('只保存本动作')
                    page.locator('[data-material-action="1"]').locator('xpath=..').locator(':scope > summary').click()
                    page.locator('[data-material-action="1"] [name="notes"]').fill('另一个动作未保存')
                    page.locator('[data-material-action="0"] [type="submit"]').click();page.wait_for_timeout(150)
                    assert page.locator('[data-material-action="1"] [name="notes"]').input_value()=='另一个动作未保存'
                    assert page.evaluate('MaterialPreparation.isDirty()')
                    page.once('dialog',lambda d:d.accept());page.click('#preparation-reload');page.wait_for_timeout(100)
                    # Same file does not transfer state to another action or project.
                    assert page.locator('[data-material-action="1"] [name="status"]').input_value()=='todo'
                    page.select_option('#filter-project','B');page.wait_for_timeout(100)
                    page.locator('[data-material-action="0"]').locator('xpath=..').locator(':scope > summary').click()
                    assert page.locator('[data-material-action="0"] [name="status"]').input_value()=='todo'
                    assert not page.locator('[data-material-action="0"] [name="material_ids"]').is_checked()
                    # Conditions explicit; unknown scope/source block saving.
                    data['actions']['B'][0]['conditions']=[dict(scope='action',evidence=dict(text='仅限指定身份',quote='指定身份',locator='第3段'))]
                    data['actions']['B'][1]['program_pending']=True
                    page.evaluate('refresh()');page.wait_for_timeout(100)
                    assert not page.locator('[data-material-action="0"] [name="confirmed_conditions"]').is_checked()
                    assert page.locator('[data-material-action="1"] [type="submit"]').is_disabled()
                    data['actions']['B'][0]['quality']=dict(state='changed',label='来源原文已变化')
                    page.evaluate('refresh()');page.wait_for_timeout(100)
                    assert page.locator('[data-material-action="0"] [type="submit"]').is_disabled()
                    page.screenshot(path=str(output/f'preparation-{width}.png'),full_page=True)
                    page.evaluate('scrollTo(0,0)');page.screenshot(path=str(output/f'preparation-{width}-viewport.png'))
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
                    # Empty project and degraded API preserve existing workflow.
                    page.select_option('#filter-project','');page.wait_for_timeout(100);assert '先选择一个申请项目' in page.inner_text('#preparation-list')
                    offline[0]=True;page.evaluate('refresh()');page.wait_for_function('document.querySelector("#preparation-feedback").textContent.includes("暂不可用")');offline[0]=False
                    assert page.locator('.section-tabs [data-section="project"]').is_enabled()
                    assert not errors,errors
                    page.close()
                # Public rendering must not access private API or browser persistence.
                public_page=browser.new_page();private_requests=[]
                public_page.route('**/api/**',lambda route:(private_requests.append(route.request.url),route.abort()))
                public_page.goto(f'http://127.0.0.1:{server.server_port}/public-material.html')
                markup=public_page.evaluate('args=>MaterialPreparation.publicActions({...ADMISSIONS_DATA.policies[0],material_actions:[args.action]},ADMISSIONS_DATA)',dict(action=action))
                assert '上传申请PDF' in markup and not private_requests
                assert public_page.evaluate('localStorage.length')==0
                public_page.close()
                browser.close()
        finally:server.shutdown();server.server_close()
    print('PASS material frontend: 1440/390, two projects/actions, checkbox files, dirty guards, refresh/409 input preservation, conditional/unknown scope, empty/503, no overflow')


if __name__=='__main__':main()

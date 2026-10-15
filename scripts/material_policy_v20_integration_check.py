"""Real v20 conditional-policy flows; all workflow writes stay in a temporary directory."""
import hashlib
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.serve import create_server

CASES=[
 ('tsinghua-2027-master-registration-v20north','submit-graduate-permission','tsinghua'),
 ('bit-2027-master-testcenter1107-v20north','submit-required-corrections','bit'),
 ('buaa-2027-master-testcenter1106-v20north','submit-testcenter-corrections','buaa'),
]

def main():
    output=ROOT/'cache/policy_v20/live_flow';output.mkdir(parents=True,exist_ok=True)
    public=json.loads((ROOT/'site/admissions-data.js').read_text(encoding='utf-8-sig').split('=',1)[1].strip().rstrip(';'))
    policies={p['id']:p for p in public['policies']}
    assert all(pid in policies for pid,_,_ in CASES),'Build v20 first'
    protected=[ROOT/'data/workflow.json',ROOT/'data/outreach.yaml']
    def signatures():return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in protected}
    before=signatures();results=[]
    with tempfile.TemporaryDirectory(prefix='policy-v20-') as tmp:
        root=Path(tmp);site=root/'site';site.mkdir()
        for name in ['workflow.js','material-actions.js','data.js','admissions-data.js','admissions-core.js','admissions.js','ui.css']:
            shutil.copyfile(ROOT/'site'/name,site/name)
        env=Environment(loader=FileSystemLoader(ROOT/'site/templates'))
        for name in ['applications','admissions']:(site/(name+'.html')).write_text(env.get_template(name+'.html.j2').render(),encoding='utf-8')
        server=create_server(site=site,outreach=root/'private/outreach.yaml',workflow=root/'private/workflow.json',port=0)
        threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}'
        def request(path='',body=None,method=None,expect=200):
            raw=None if body is None else json.dumps(body).encode()
            req=Request(base+'/api/workflow'+path,data=raw,method=method or ('GET' if body is None else 'POST'),headers={'Content-Type':'application/json','Origin':base})
            try:
                with urlopen(req) as r:code=r.status;value=json.load(r)
            except HTTPError as e:code=e.code;value=json.load(e)
            assert code==expect,(path,code,expect,value)
            return value
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                for policy_id,action_id,school in CASES:
                    policy=policies[policy_id]
                    goal=dict(school_id=school,dept_id='cs',year=2027,degree='master',route='exam',track='ordinary',program_code='',program_name='')
                    project=request('/projects',dict(name='临时v20条件核验-'+school,**goal));pid=project['id']
                    views=request('/material-tasks')['actions'][pid]
                    index,row=next((i,v) for i,v in enumerate(views) if v['policy_id']==policy_id and v['action_id']==action_id)
                    assert row['conditions'] and row['can_record'] and row['events']
                    body=dict(project_id=pid,expected_goal=row['goal_snapshot'],policy_id=policy_id,action_id=action_id,expected_action=row['action_fingerprint'],status='prepared',material_ids=[],notes='临时验证，未向学校提交',confirmed_conditions=False)
                    count=len(request('/material-tasks')['records'])
                    denied=request('/material-tasks',body,expect=400)
                    assert len(request('/material-tasks')['records'])==count
                    event=row['events'][0]['event'];source_url=row['events'][0]['source_url']
                    deadline={**event,'origin':'policy','policy_id':policy_id,'source_url':source_url}
                    deadline['source_ids']=event.get('source_ids',[policy['source_id']])
                    # Conditional policy events must never be imported automatically into the project.
                    import_denied=request('/projects/'+pid,dict(deadlines=[deadline]),method='PATCH',expect=400)
                    assert request()['projects'][pid]['deadlines']==[]
                    if school in ['tsinghua','buaa']:
                        page.goto(base+'/applications.html?project='+pid+'&section=preparation');page.wait_for_load_state('networkidle');page.wait_for_function('window.WORKFLOW_READY')
                        form=page.locator(f'[data-material-action="{index}"]');form.wait_for(state='attached')
                        form.locator('xpath=..').locator(':scope > summary').click()
                        assert not form.locator('[name="confirmed_conditions"]').is_checked()
                        article=form.locator('xpath=..')
                        for c in row['conditions']:
                            assert c['evidence']['text'] in article.inner_text()
                            assert c['evidence']['quote'] in article.inner_text()
                        # Original instruction quote is in the collapsible source disclosure.
                        assert row['action']['instruction']['quote'] in article.text_content()
                        sid=row['action']['instruction'].get('source_ids',[policy['source_id']])[0]
                        link=article.locator(f'a[href="{public["sources"][sid]["url"]}"]').first
                        assert link.get_attribute('target')=='_blank'
                        if school=='buaa':
                            channel_index=next(i for i,v in enumerate(views) if v['policy_id']==policy_id and v['action_id']=='follow-designated-verification-channel')
                            channel=page.locator(f'[data-material-action="{channel_index}"]').locator('xpath=..')
                            channel.locator(':scope > summary').click()
                            assert '无需在网上报名系统上传' in channel.text_content()
                            assert '提交材料网址' in channel.text_content()
                        # Browser validity and server both reject unconfirmed conditions.
                        form.locator('[type="submit"]').click();assert not form.evaluate('f=>f.checkValidity()')
                        assert len(request('/material-tasks')['records'])==count
                        form.locator('[name="confirmed_conditions"]').check();form.locator('[name="status"]').select_option('prepared')
                        form.locator('[name="notes"]').fill('仅临时浏览器验证，未发送材料');form.locator('[type="submit"]').click()
                        page.wait_for_function('!MaterialPreparation.isDirty()');page.wait_for_load_state('networkidle')
                        record=next(r for r in request('/material-tasks')['records'].values() if r['project_id']==pid and r['policy_id']==policy_id and r['action_id']==action_id)
                        form=page.locator(f'[data-material-action="{index}"]');history=form.locator('xpath=..').locator('[data-material-history]')
                        if not history.evaluate('e=>e.open'):history.locator(':scope > summary').click()
                        history.locator('[data-material-reminder]').click();page.wait_for_function('document.querySelector("#preparation-feedback").textContent.includes("登记项目提醒")')
                        for width,height in [(1440,1000),(390,844)]:
                            page.set_viewport_size({'width':width,'height':height});form.scroll_into_view_if_needed()
                            page.screenshot(path=str(output/f'{school}-{width}-viewport.png'))
                            page.screenshot(path=str(output/f'{school}-{width}-full.png'),full_page=True)
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        (output/f'{school}-dom.html').write_text(page.content(),encoding='utf-8')
                        page.set_viewport_size({'width':1440,'height':1000})
                    else:
                        body['confirmed_conditions']=True;request('/material-tasks',body)
                        record=next(r for r in request('/material-tasks')['records'].values() if r['project_id']==pid and r['policy_id']==policy_id and r['action_id']==action_id)
                        request('/material-tasks/'+record['id']+'/reminders',dict(expected_goal=row['goal_snapshot'],expected_action=row['action_fingerprint'],event_index=row['events'][0]['event_index']))
                    reminders=[r for r in request()['reminders'].values() if r['project_id']==pid]
                    assert len(reminders)==1
                    reminder=reminders[0]
                    for value in [event['at'],event['quote'],source_url]:assert value in reminder['notes'],(value,reminder)
                    assert request()['projects'][pid]['deadlines']==[]
                    assert record['confirmed_conditions'] and record['status']=='prepared' and record['events']==row['events']
                    request('/projects/'+pid,dict(school_id='sdu',dept_id='cs'),method='PATCH')
                    invalid=request('/material-tasks')['records'][record['id']]
                    assert invalid['review_required'] and not invalid['applicable'] and 'goal_changed' in invalid['review_reasons']
                    request('/material-tasks/'+record['id']+'/reminders',dict(expected_goal=row['goal_snapshot'],expected_action=row['action_fingerprint'],event_index=row['events'][0]['event_index']),expect=409)
                    assert len([r for r in request()['reminders'].values() if r['project_id']==pid])==1
                    results.append(dict(policy_id=policy_id,action_id=action_id,api_condition_rejected=denied,automatic_date_import_rejected=import_denied,condition_default_unchecked=school in ['tsinghua','buaa'],ui_viewports=[1440,390] if school in ['tsinghua','buaa'] else [],record_snapshot=record,reminder=reminder,project_deadlines_untouched=True,changed_goal_record=invalid))
                assert not errors,errors
                browser.close()
        finally:server.shutdown();server.server_close()
    assert signatures()==before,'Real private files changed'
    (output/'results.json').write_text(json.dumps(dict(passed=True,cases=results,browser_errors=errors,real_private_signatures_unchanged=True,protected_signatures=before,all_writes_temporary=True,public_source_links_exact_urls_only=True),ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS 3 real conditional policies API; Tsinghua/BUAA UI1440/390; exact reminder provenance; import rejection; changed-goal isolation; temporary writes only')

if __name__=='__main__':main()

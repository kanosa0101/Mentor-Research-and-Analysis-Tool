"""Project review UI regression; all private writes use a temporary directory."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.serve import create_server

def main():
    out=ROOT/'cache/policy_v16/review_ui';out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);site=root/'site';site.mkdir()
        for file in ['data.js','search.js','compare-data.js','discovery.js','discovery-core.js','ui.css','workflow.js','admissions-data.js','admissions-core.js']:
            shutil.copyfile(ROOT/'site'/file,site/file)
        (site/'p').mkdir()
        for file in (ROOT/'site/p').glob('*.html'):(site/'p'/file.name).write_text('fixture',encoding='utf-8')
        env=Environment(loader=FileSystemLoader(ROOT/'site/templates'))
        for name in ['discovery','applications']:(site/(name+'.html')).write_text(env.get_template(name+'.html.j2').render(),encoding='utf-8')
        server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/discovery.html');page.wait_for_function('window.DISCOVERY_READY')
                assert not (root/'private/discovery.yaml').exists()
                mentor=page.evaluate('MENTOR_DATA.find(p=>p.school==="pku"&&p.dept==="cs")||MENTOR_DATA[0]')
                goal=dict(school_id=mentor['school'],dept_id=mentor['dept'],year=2027,degree='master',route='exam',track='special',program_code='',program_name='测试正式专业')
                def request(path,body=None,method='POST'):
                    return page.evaluate('async a=>{const r=await fetch(a.path,{method:a.method,headers:{"Content-Type":"application/json"},...(a.body?{body:JSON.stringify(a.body)}:{})});return {status:r.status,data:await r.json()}}',dict(path=path,body=body,method=method))
                a=request('/api/workflow/projects',dict(name='隔离项目甲',**goal))['data'];b=request('/api/workflow/projects',dict(name='隔离项目乙',**goal))['data']
                assert a.get('id'),a
                reply=request('/api/workflow/communications',dict(project_id=a['id'],mentor_id=mentor['page'],kind='replied',date='2026-10-15',subject='已收到回复',content='测试原文：本年度接收该专业申请。'))['data']
                draft=request('/api/workflow/communications',dict(project_id=a['id'],mentor_id=mentor['page'],kind='draft',date='2026-10-15',subject='私人草稿',content='仅草稿'))['data']
                page.goto(base+'/discovery.html?project='+a['id']);page.wait_for_function('window.DISCOVERY_READY')
                assert '隔离项目甲' in page.inner_text('#review-project-goal')
                assert page.evaluate('publicScope().get("program")')=='|测试正式专业'
                assert 'project=' not in page.evaluate('publicScope().toString()')
                assert page.locator('#mode-opportunity').is_enabled()
                page.fill('#intent-name',mentor['name']);page.click('#apply-criteria');page.wait_for_function('view.length>0')
                def open_review():
                    summary=page.locator(f'[data-candidate="{mentor["page"]}"] .candidate-application summary')
                    if not summary.evaluate('(e)=>e.parentElement.open'):summary.click()
                    page.locator(f'[data-review="{mentor["page"]}"]').click()
                open_review();page.select_option('#review-opportunity','pass');page.select_option('#opportunity-evidence-kind','reply')
                assert '私人草稿' not in page.inner_text('#opportunity-evidence-reply')
                page.select_option('#opportunity-evidence-reply',reply['id']);page.fill('#opportunity-evidence-quote','本年度接收该专业申请');page.fill('#opportunity-evidence-scope','2027硕士统考测试正式专业的招生机会')
                page.select_option('#review-eligibility','pass');page.fill('#eligibility-evidence-url','https://example.edu/requirements');page.fill('#eligibility-evidence-quote','测试本人条件符合');page.fill('#eligibility-evidence-scope','已逐项核对本人条件，适用此项目')
                page.check('#review-confirmed');page.click('#review-save');page.wait_for_function('document.querySelector("#review-panel").hidden&&document.querySelector("#discovery-message").textContent.includes("已保存在本机")')
                assert page.evaluate('view.find(r=>r.p.page===%s).result.checks.find(c=>c.key==="opportunity").state'%json.dumps(mentor['page']))=='pass'
                # Delay the actual save request, then keep typing in the same project/mentor form.
                open_review();page.fill('#opportunity-evidence-scope','提交时的说明');page.check('#review-confirmed')
                pending=[]
                def hold_save(route):
                    if route.request.method=='POST':pending.append(route)
                    else:route.continue_()
                page.route('**/api/discovery/project-reviews',hold_save)
                page.evaluate('message("")');page.click('#review-save');page.wait_for_timeout(100)
                assert pending
                page.fill('#opportunity-evidence-scope','提交后继续编辑的未保存说明')
                pending[0].continue_();page.wait_for_function('document.querySelector("#discovery-message").textContent.includes("已保存")')
                assert page.locator('#review-panel').is_visible()
                assert page.input_value('#opportunity-evidence-scope')=='提交后继续编辑的未保存说明'
                assert page.evaluate('reviewDirty')
                page.unroute('**/api/discovery/project-reviews',hold_save)
                page.once('dialog',lambda d:d.accept());page.click('#review-cancel')
                # Pause the successful POST's following GET, reopen the same form, then finish the refresh.
                open_review();page.check('#review-confirmed');pending=[];after_post=[False]
                def hold_refresh(route):
                    if route.request.method=='POST':after_post[0]=True;route.continue_()
                    elif after_post[0]:pending.append(route)
                    else:route.continue_()
                page.route('**/api/discovery/project-reviews',hold_refresh);page.click('#review-save')
                page.wait_for_function('document.querySelector("#review-panel").hidden');page.wait_for_timeout(100);assert pending
                open_review();page.fill('#opportunity-evidence-scope','刷新期间重开表单后的新输入')
                pending[0].continue_();page.wait_for_function('!savingReview')
                assert page.locator('#review-panel').is_visible() and page.input_value('#opportunity-evidence-scope')=='刷新期间重开表单后的新输入'
                page.unroute('**/api/discovery/project-reviews',hold_refresh);page.once('dialog',lambda d:d.accept());page.click('#review-cancel')
                # A committed POST followed by failed GET must say saved, and retain a newly opened form.
                open_review();page.check('#review-confirmed');pending=[];after_post[0]=False;page.route('**/api/discovery/project-reviews',hold_refresh);page.evaluate('message("")');page.click('#review-save')
                page.wait_for_function('document.querySelector("#review-panel").hidden');page.wait_for_timeout(100);assert pending
                open_review();page.fill('#opportunity-evidence-scope','刷新失败时也须保留的新输入')
                pending[0].fulfill(status=503,content_type='application/json',body='{"error":"测试刷新失败"}');page.wait_for_function('!savingReview')
                assert '已保存，刷新失败' in page.inner_text('#discovery-message')
                assert page.locator('#review-panel').is_visible() and page.input_value('#opportunity-evidence-scope')=='刷新失败时也须保留的新输入'
                page.unroute('**/api/discovery/project-reviews',hold_refresh);page.once('dialog',lambda d:d.accept());page.click('#review-cancel')
                page.locator('#advanced-criteria summary').click();page.select_option('#mode-opportunity','hard');page.uncheck('#keep-unknown');page.click('#apply-criteria');page.wait_for_function('view.length===1');page.select_option('#mode-opportunity','soft');page.check('#keep-unknown');page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled');
                open_review();page.evaluate('el("review-panel").scrollIntoView({block:"start",behavior:"instant"})');page.locator('#review-panel').screenshot(path=str(out/'desktop-form.png'));page.set_viewport_size({'width':390,'height':844});page.evaluate('el("review-panel").scrollIntoView({block:"start",behavior:"instant"})');page.locator('#review-panel').screenshot(path=str(out/'mobile-form.png'));assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.set_viewport_size({'width':1440,'height':1000});page.click('#review-cancel')
                page.select_option('#review-project',b['id']);page.wait_for_function('!document.querySelector("#apply-criteria").disabled&&view.every(r=>!r.result.review)')
                open_review();page.select_option('#review-opportunity','fail');page.fill('#opportunity-evidence-url','https://example.edu/full');page.fill('#opportunity-evidence-quote','测试本项目本年度不接收');page.fill('#opportunity-evidence-scope','此项目招生机会');page.check('#review-confirmed');page.click('#review-save');page.wait_for_function('document.querySelector("#review-panel").hidden&&document.querySelector("#discovery-message").textContent.includes("已保存在本机")')
                page.wait_for_function('(id)=>view.find(r=>r.p.page===id)?.result.checks.find(c=>c.key==="opportunity").state==="fail"',arg=mentor['page'])
                page.select_option('#review-project',a['id']);page.wait_for_function('view.some(r=>r.result.review?.project_id===%s)'%json.dumps(a['id']))
                open_review();page.fill('#opportunity-evidence-scope','尚未保存的修改')
                page.once('dialog',lambda d:d.dismiss());page.select_option('#review-project',b['id']);assert page.input_value('#review-project')==a['id'];assert page.input_value('#opportunity-evidence-scope')=='尚未保存的修改'
                # Another page changes the goal while this form retains its expected snapshot.
                changed={**goal,'program_name':'其他正式专业'};assert request('/api/workflow/projects/'+a['id'],changed,'PATCH')['status']==200
                page.check('#review-confirmed');page.click('#review-save');page.wait_for_function('document.querySelector("#discovery-message").textContent.includes("未保存")')
                assert page.locator('#review-panel').is_visible()
                page.evaluate('refreshProjectStatus()')
                assert page.evaluate('view.every(r=>r.result.checks.filter(c=>["opportunity","eligibility"].includes(c.key)).every(c=>c.state==="unknown"))')
                assert page.input_value('#opportunity-evidence-scope')=='尚未保存的修改'
                assert page.locator('#mode-opportunity').is_disabled()
                page.once('dialog',lambda d:d.accept());page.click('#review-project-confirm');page.wait_for_function('document.querySelector("#review-panel").hidden&&matchesCurrent()&&!document.querySelector("#apply-criteria").disabled')
                assert page.evaluate('view.every(r=>!r.result.review)')
                page.screenshot(path=str(out/'desktop.png'))
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                # School multi-selection immediately suspends project conclusions.
                page.evaluate('changeSchool(MENTOR_DATA.find(p=>p.school!==currentProject().goal_snapshot.school_id).school,true)')
                page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                assert page.locator('#mode-opportunity').is_disabled()
                assert page.evaluate('view.every(r=>r.result.checks.filter(c=>["opportunity","eligibility"].includes(c.key)).every(c=>c.state==="unknown"))')
                # Existing generic judgments cannot leak through a missing project or unavailable project API.
                generic=dict(mentor_id=mentor['page'],year=2027,degree='master',route='exam',opportunity='pass',eligibility='fail',source_url='https://example.edu/generic',quote='通用历史测试依据',confirmed=True)
                assert request('/api/discovery/reviews',generic)['status']==200
                page.goto(base+'/discovery.html?project=missing&year=2027&degree=master&route=exam');page.wait_for_function('window.DISCOVERY_READY')
                assert page.evaluate('view.every(r=>r.result.checks.filter(c=>["opportunity","eligibility"].includes(c.key)).every(c=>c.state==="unknown"))')
                assert page.locator('#mode-opportunity').is_disabled()
                page.route('**/api/discovery/project-reviews',lambda r:r.fulfill(status=503,content_type='application/json',body='{"error":"临时不可用"}'))
                page.reload();page.wait_for_function('window.DISCOVERY_READY')
                assert page.evaluate('view.every(r=>r.result.checks.filter(c=>["opportunity","eligibility"].includes(c.key)).every(c=>c.state==="unknown"))')
                assert all('project=' not in href and '隔离项目' not in href for href in page.locator('a[href^="https:"]').evaluate_all('(els)=>els.map(e=>e.href)'))
                page.select_option('#review-project','');page.wait_for_function('!projectScoped');assert page.evaluate('view.some(r=>r.result.review?.opportunity==="pass")')
                page.fill('#intent-name',mentor['name']);page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
                open_review();page.fill('#review-quote','提交的通用原文');page.check('#review-confirmed');pending=[]
                page.route('**/api/discovery/reviews',hold_save);page.evaluate('message("")');page.click('#review-save');page.wait_for_timeout(100);assert pending
                page.fill('#review-quote','通用提交后继续编辑，尚未保存');pending[0].continue_();page.wait_for_function('!savingReview')
                assert page.locator('#review-panel').is_visible() and page.input_value('#review-quote')=='通用提交后继续编辑，尚未保存'
                assert page.evaluate('reviewDirty')
                page.unroute('**/api/discovery/reviews',hold_save)
                page.once('dialog',lambda d:d.accept());page.click('#review-cancel')
                assert not errors,errors
                browser.close()
        finally:server.shutdown();server.server_close()
    print('PASS isolated project review UI, opposite outcomes, reply/draft, conflict, refresh, scope and 390 layout')
if __name__=='__main__':main()

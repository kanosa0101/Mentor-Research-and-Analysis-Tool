"""Delayed read-only material GET regression in a temporary browser fixture."""
import json,shutil,tempfile,threading
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
def main():
 out=ROOT/'cache/policy_v21/east/material-loading';out.mkdir(parents=True,exist_ok=True)
 wf={'projects':{p:{'id':p,'name':'Project '+p} for p in ['A','B']},'materials':{}}
 def payload(label='Action A'):
  action={'id':'one','label':label,'stage':'application','instruction':{'text':'Official requirement','quote':'Requirement','locator':'Clause 1'}}
  row={'policy_id':'p','policy_title':'Policy','action_id':'one','action':action,'quality':{'state':'checked','label':'Checked'},'can_record':True,'conditions':[],'events':[],'action_fingerprint':'original','goal_snapshot':{}}
  return {'actions':{'A':[row],'B':[]},'records':{}}
 with tempfile.TemporaryDirectory() as tmp:
  site=Path(tmp);shutil.copyfile(ROOT/'site/material-actions.js',site/'material-actions.js')
  (site/'index.html').write_text('<meta charset="utf-8"><div id="preparation-feedback"></div><button id="preparation-reload">Reload</button><div id="preparation-list"></div><script>window.AdmissionsRules={checklist:()=>({ready:true})};window.ADMISSIONS_DATA={sources:{},policies:[]};</script><script src="material-actions.js"></script>',encoding='utf8')
  server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=tmp));threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch();page=browser.new_page();pending=[];writes=[];errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def intercept(route):
     if route.request.method!='GET':writes.append(route.request.method);route.fulfill(json={})
     else:pending.append(route)
    page.route('**/api/workflow/material-tasks**',intercept)
    page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
    page.evaluate('(wf)=>{window.fixture=wf;MaterialPreparation.init({reload:()=>MaterialPreparation.refresh(fixture,"A")});MaterialPreparation.refresh(wf,"A");}',wf)
    page.wait_for_timeout(80);assert len(pending)==1
    text=page.locator('#preparation-list').inner_text();assert '当前目标尚无' not in text,text
    assert '正在读取' in text,text
    pending.pop(0).fulfill(json=payload());page.wait_for_selector('.preparation-action')
    page.locator('[data-prepare-detail] > summary').first.click();page.fill('[name="notes"]','unsaved')
    page.evaluate('()=>{MaterialPreparation.refresh(fixture,"A");}');page.wait_for_timeout(80)
    assert page.input_value('[name="notes"]')=='unsaved'
    pending.pop(0).fulfill(json=payload('Changed action'));page.wait_for_timeout(80)
    assert page.input_value('[name="notes"]')=='unsaved'
    assert 'Action A' in page.locator('#preparation-list').inner_text()
    page.once('dialog',lambda d:d.accept());page.evaluate('MaterialPreparation.discard()')
    page.evaluate('()=>{MaterialPreparation.refresh(fixture,"B");}');page.wait_for_timeout(80)
    text=page.locator('#preparation-list').inner_text();assert '正在读取' in text and '当前目标尚无' not in text and 'Action A' not in text,text
    assert page.locator('[data-material-action], [data-material-history]').count()==0
    pending.pop(0).fulfill(json=payload());page.wait_for_timeout(80)
    assert '当前目标尚无' in page.locator('#preparation-list').inner_text()
    page.evaluate('()=>{MaterialPreparation.refresh(fixture,"A");}');page.wait_for_timeout(80)
    assert '正在读取' in page.locator('#preparation-list').inner_text()
    pending.pop(0).fulfill(status=503,json={'error':'fixture offline'});page.wait_for_timeout(80)
    assert '暂不可用' in page.locator('#preparation-feedback').inner_text()
    assert '当前目标尚无' not in page.locator('#preparation-list').inner_text()
    assert page.locator('[data-material-action]').count()==0
    page.click('#preparation-reload');page.wait_for_timeout(80);pending.pop(0).fulfill(json=payload());page.wait_for_selector('.preparation-action')
    assert 'Action A' in page.locator('#preparation-list').inner_text()
    page.locator('[data-prepare-detail] > summary').first.click()
    assert page.locator('[type="submit"]').is_enabled()
    assert not page.locator('#preparation-feedback').inner_text(), 'successful retry must clear unavailable feedback'
    for key,value in {'school_id':'test','dept_id':'cs','year':2028,'degree':'phd','route':'exam','track':'ordinary','program_code':'081200','program_name':'Computer science'}.items():
     page.evaluate('([key,value])=>{fixture.projects.A[key]=value;MaterialPreparation.refresh(fixture,"A");}',[key,value]);page.wait_for_timeout(40)
     assert '正在读取' in page.locator('#preparation-list').inner_text()
     assert page.locator('[data-material-action], [data-material-history]').count()==0
     pending.pop(0).fulfill(json=payload());page.wait_for_selector('.preparation-action')
    page.evaluate('()=>{MaterialPreparation.refresh(fixture,"A");fixture.projects.A.year=2029;MaterialPreparation.refresh(fixture,"A");}');page.wait_for_timeout(80)
    assert len(pending)==2
    pending.pop(0).fulfill(json=payload('Stale action'));page.wait_for_timeout(40)
    assert '正在读取' in page.locator('#preparation-list').inner_text()
    pending.pop(0).fulfill(json=payload('Current action'));page.wait_for_selector('.preparation-action')
    assert 'Current action' in page.locator('#preparation-list').inner_text() and 'Stale action' not in page.locator('#preparation-list').inner_text()
    assert not writes and not errors,(writes,errors)
    page.locator('[data-prepare-detail] > summary').first.click();page.fill('[name="notes"]','explicit fixture save');page.click('[type="submit"]');page.wait_for_timeout(80)
    assert writes==['POST'] and len(pending)==1
    assert '已保存' in page.locator('#preparation-feedback').inner_text()
    pending.pop(0).fulfill(json=payload('Current action'));page.wait_for_timeout(80)
    assert '已保存' in page.locator('#preparation-feedback').inner_text(), 'post-save refresh must preserve confirmation'
    page.screenshot(path=str(out/'retry-success.png'))
    browser.close()
   result={'delayed_get_no_false_empty':True,'new_project_hides_old_actions':True,'true_empty_after_response':True,'same_project_dirty_preserved':True,'eight_goal_fields_invalidate_loaded_scope':True,'stale_response_ignored':True,'error_retry_recovers':True,'save_confirmation_survives_refresh':True,'automatic_writes':0,'explicit_mock_saves':len(writes),'console_errors':errors}
   (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result))
  finally:server.shutdown();server.server_close()
if __name__=='__main__':main()

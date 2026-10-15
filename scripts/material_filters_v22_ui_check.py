"""v22 filters: isolated browser fixture, no real private data writes."""
import copy,json,shutil,tempfile,threading
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'cache/policy_v22/ui'

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 goal=dict(school_id='zju',dept_id='cs',year=2027,degree='master',route='exam',track='ordinary',program_code='',program_name='Computer science')
 wf={'projects':{p:dict(id=p,name='Project '+p,**goal) for p in ['A','B']},'materials':{}}
 rows=[];records={}
 specs=[('none','application',None,{}),('todo','screening','todo',{}),('prepared','interview','prepared',{}),('submitted','admission','submitted',{}),('revision','enrollment','needs_revision',{}),('stale','other','prepared',{'quality':{'state':'stale'}}),('changed','application','submitted',{'quality':{'state':'changed'}}),('filechanged','interview','prepared',{'review_required':True}),('failed','application','prepared',{'quality':{'state':'error'}}),('oldtarget','interview',None,{}),('pending','screening','prepared',{'program_pending':True}),('blocked','other','prepared',{'can_record':False}),('conditional','application',None,{'conditions':[{'text':'Only if applicable'}]})]
 for i,(name,stage,status,extra) in enumerate(specs):
  action=dict(id=name,label=name,stage=stage,instruction=dict(text='Official requirement',quote='Requirement',locator='Clause 1'))
  row=dict(policy_id='p',policy_title='Policy',action_id=name,action=action,quality=dict(state='checked',label='Checked'),can_record=True,conditions=[],events=[],action_fingerprint='fingerprint-'+name,goal_snapshot=goal,latest_record_id=None)
  if status:
   rid='record-'+name;row['latest_record_id']=rid;records[rid]=dict(id=rid,project_id='A',policy_id='p',action_id=name,status=status,applicable=True,review_required=extra.pop('review_required',False),goal_snapshot=goal,created_at='2026-10-15',action=action)
  row.update(extra);rows.append(row)
 records['old']=dict(records['record-prepared'],id='old',action_id='oldtarget',status='submitted',review_required=True,review_reasons=['goal_changed'])
 records['history']=dict(records['old'],id='history',action_id='removed')
 data=dict(actions={'A':rows,'B':rows},records=records)
 with tempfile.TemporaryDirectory() as tmp:
  site=Path(tmp)
  for f in ['material-actions.js','ui.css']:shutil.copyfile(ROOT/'site'/f,site/f)
  (site/'index.html').write_text('<meta charset="utf-8"><link rel="stylesheet" href="ui.css"><div id="preparation-feedback"></div><button id="preparation-reload">Reload</button><div id="preparation-list"></div><script>window.AdmissionsRules={checklist:()=>({ready:true})};window.ADMISSIONS_DATA={sources:{},policies:[]};</script><script src="material-actions.js"></script>',encoding='utf8')
  server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=tmp));threading.Thread(target=server.serve_forever,daemon=True).start()
  results=[]
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch()
    for width in [1440,390]:
     page=browser.new_page(viewport={'width':width,'height':950});writes=[];errors=[];pending=[];delay=[False]
     page.on('pageerror',lambda e:errors.append(str(e)))
     def intercept(route):
      if route.request.method=='GET':
       if delay[0]:pending.append(route)
       else:route.fulfill(json=copy.deepcopy(data))
      else:writes.append(route.request.post_data_json);route.fulfill(json={})
     page.route('**/api/workflow/material-tasks**',intercept)
     page.goto(f'http://127.0.0.1:{server.server_port}/index.html')
     page.evaluate('(wf)=>{window.fixture=wf;MaterialPreparation.init({reload:()=>MaterialPreparation.refresh(fixture,"A")});MaterialPreparation.refresh(wf,"A");}',wf)
     page.wait_for_selector('.preparation-action')
     assert page.locator('#preparation-stage-filter').count()==1,'Missing preparation stage filter'
     assert page.locator('#preparation-status-filter option').all_text_contents()==['全部登记状态','待处理','已准备','已登记提交']
     assert page.locator('#preparation-stage-filter option').count()==7
     assert page.locator('.preparation-action').count()==13
     assert '显示13/13项已整理事项，条件事项须核对适用' in page.locator('#preparation-list').inner_text()
     page.select_option('#preparation-status-filter','pending')
     assert set(page.locator('.preparation-action > h4').all_text_contents())=={name for name,_,_,_ in specs if name not in ['prepared','submitted']}
     page.select_option('#preparation-status-filter','prepared');assert page.locator('.preparation-action > h4').all_text_contents()==['prepared']
     assert page.locator('[data-material-action]').get_attribute('data-material-action')=='2'
     page.locator('[data-prepare-detail] > summary').first.click();page.fill('[name="notes"]','unsaved')
     page.evaluate('window.originalForm=document.querySelector("[data-material-action]")')
     page.once('dialog',lambda d:d.dismiss());page.select_option('#preparation-stage-filter','application')
     assert page.input_value('#preparation-stage-filter')==''
     assert page.input_value('[name="notes"]')=='unsaved' and page.evaluate('originalForm===document.querySelector("[data-material-action]")')
     page.once('dialog',lambda d:d.accept());page.select_option('#preparation-stage-filter','application')
     assert page.locator('.preparation-action').count()==0
     assert '清除筛选' in page.locator('#preparation-list').inner_text() and '没有要求' not in page.locator('#preparation-list').inner_text()
     assert '当前清单之外的历史记录' in page.locator('#preparation-list').inner_text()
     page.click('[data-preparation-clear]');assert page.locator('.preparation-action').count()==13
     page.select_option('#preparation-stage-filter','interview');page.select_option('#preparation-status-filter','prepared')
     assert page.locator('[data-prepare-detail]').first.evaluate('e=>e.open'),'open action must survive filtering'
     page.fill('[name="notes"]','save correct original index');page.click('[type="submit"]');page.wait_for_timeout(100)
     assert writes[-1]['action_id']=='prepared' and writes[-1]['expected_action']=='fingerprint-prepared'
     assert page.input_value('#preparation-stage-filter')=='interview' and page.input_value('#preparation-status-filter')=='prepared'
     assert len(writes)==1
     page.select_option('#preparation-status-filter','submitted');page.select_option('#preparation-stage-filter','admission');assert page.locator('.preparation-action > h4').all_text_contents()==['submitted']
     page.screenshot(path=str(OUT/f'filters-{width}.png'),full_page=True)
     for key,value in dict(school_id='new',dept_id='new',year=2028,degree='phd',route='recommendation',track='special',program_code='081200',program_name='New').items():
      page.evaluate('([k,v])=>{fixture.projects.A[k]=v;MaterialPreparation.refresh(fixture,"A");}',[key,value]);page.wait_for_timeout(50)
      assert page.input_value('#preparation-stage-filter')=='' and page.input_value('#preparation-status-filter')==''
      page.select_option('#preparation-status-filter','pending');page.select_option('#preparation-stage-filter','other')
     page.evaluate('()=>{MaterialPreparation.refresh(fixture,"B");}');page.wait_for_timeout(50)
     assert page.input_value('#preparation-stage-filter')=='' and page.input_value('#preparation-status-filter')==''
     page.select_option('#preparation-stage-filter','interview')
     page.evaluate('()=>{MaterialPreparation.refresh(fixture,"");}');page.wait_for_timeout(50)
     page.evaluate('()=>{MaterialPreparation.refresh(fixture,"B");}');page.wait_for_timeout(50)
     assert page.input_value('#preparation-stage-filter')==''
     delay[0]=True
     page.evaluate('()=>{MaterialPreparation.refresh(fixture,"A");}');page.wait_for_timeout(50)
     assert '正在读取' in page.locator('#preparation-list').inner_text() and page.locator('[data-material-action]').count()==0
     pending.pop().fulfill(json=data);page.wait_for_selector('.preparation-action')
     delay[0]=False
     page.select_option('#preparation-stage-filter','interview');page.select_option('#preparation-status-filter','prepared')
     page.locator('[data-prepare-detail]').first.evaluate('e=>e.open=true');page.fill('[name="notes"]','dirty across goal refresh')
     page.evaluate('()=>{fixture.projects.A.year=2030;MaterialPreparation.refresh(fixture,"A");}');page.wait_for_timeout(50)
     page.evaluate('window.keptForm=document.querySelector("[data-material-action]")')
     page.once('dialog',lambda d:d.dismiss());page.select_option('#preparation-stage-filter','application')
     assert page.input_value('#preparation-stage-filter')=='interview' and page.input_value('#preparation-status-filter')=='prepared'
     assert page.input_value('[name="notes"]')=='dirty across goal refresh' and page.evaluate('keptForm===document.querySelector("[data-material-action]")')
     page.once('dialog',lambda d:d.accept());page.evaluate('MaterialPreparation.discard()')
     page.evaluate('()=>{MaterialPreparation.refresh(fixture,"A");}');page.wait_for_selector('.preparation-action')
     assert page.input_value('#preparation-stage-filter')=='' and page.input_value('#preparation-status-filter')==''
     assert not errors,errors
     results.append(dict(width=width,mixed_states=True,raw_index_post=True,dirty_cancel_keeps_dom=True,dirty_goal_refresh_cancel_keeps_dom=True,dirty_confirm=True,eight_goal_resets=True,project_reset=True,same_scope_refresh_keeps_filters=True,history_preserved=True,loading_boundary=True,filter_writes=0,explicit_saves=len(writes),console_errors=errors))
     page.close()
    browser.close()
   (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(results))
  finally:server.shutdown();server.server_close()
def live_trial():
 import sys,hashlib
 from urllib.request import Request,urlopen
 from jinja2 import Environment,FileSystemLoader
 sys.path.insert(0,str(ROOT))
 from scripts.serve import create_server
 out=OUT/'zju-live';out.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='v22-filters-live-') as tmp:
  temporary=Path(tmp);site=temporary/'site';site.mkdir()
  for name in ['workflow.js','material-actions.js','data.js','admissions-data.js','admissions-core.js','ui.css']:
   shutil.copyfile(ROOT/'site'/name,site/name)
  env=Environment(loader=FileSystemLoader(ROOT/'site/templates'))
  (site/'applications.html').write_text(env.get_template('applications.html.j2').render(),encoding='utf8')
  private=temporary/'private/workflow.yaml'
  server=create_server(site=site,outreach=temporary/'private/outreach.yaml',workflow=private,port=0)
  threading.Thread(target=server.serve_forever,daemon=True).start()
  base=f'http://127.0.0.1:{server.server_port}'
  body=dict(name='浙江CS普通硕士筛选试用',school_id='zju',dept_id='cs',year=2027,degree='master',route='exam',track='ordinary',program_code='',program_name='')
  request=Request(base+'/api/workflow/projects',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
  with urlopen(request) as response:project=json.load(response)
  before=hashlib.sha256(private.read_bytes()).hexdigest()
  with urlopen(base+'/api/workflow/material-tasks') as response:payload=json.load(response)
  rows=payload['actions'][project['id']];results=[]
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch()
    for width in [1440,390]:
     page=browser.new_page(viewport={'width':width,'height':950});writes=[];errors=[]
     page.on('request',lambda req:writes.append(req.url) if req.method=='POST' else None)
     page.on('pageerror',lambda e:errors.append(str(e)))
     page.goto(base+'/applications.html?section=preparation&project='+project['id'])
     page.wait_for_selector('[data-material-action]',state='attached');page.wait_for_load_state('networkidle')
     assert page.locator('.preparation-action').count()==len(rows)
     page.select_option('#preparation-stage-filter','application')
     wanted=[str(i) for i,row in enumerate(rows) if row['action']['stage']=='application']
     assert page.locator('[data-material-action]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.materialAction)')==wanted
     page.select_option('#preparation-status-filter','pending')
     assert page.locator('.preparation-action').count()==len(wanted)
     page.screenshot(path=str(out/f'application-pending-{width}.png'),full_page=True)
     page.select_option('#preparation-status-filter','prepared')
     assert page.locator('.preparation-action').count()==0 and page.locator('[data-preparation-clear]').count()==1
     page.screenshot(path=str(out/f'prepared-empty-{width}.png'),full_page=True)
     page.click('[data-preparation-clear]');assert page.locator('.preparation-action').count()==len(rows)
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'horizontal overflow'
     assert not writes and not errors,(writes,errors)
     results.append(dict(width=width,total=len(rows),application=len(wanted),stages=sorted({r['action']['stage'] for r in rows}),original_indexes=wanted,automatic_posts=len(writes),console_errors=errors))
     page.close()
    browser.close()
   after=hashlib.sha256(private.read_bytes()).hexdigest();assert before==after
   (out/'results.json').write_text(json.dumps(dict(results=results,temporary_workflow_unchanged=before==after),ensure_ascii=False,indent=2),encoding='utf8')
  finally:server.shutdown();server.server_close()
if __name__=='__main__':
 main()
 live_trial()

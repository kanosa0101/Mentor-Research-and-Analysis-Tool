"""Actual TJU public policies and temporary project/date/reminder roundtrips."""
import sys,json,shutil,tempfile,threading,yaml
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.serve import create_server

def main():
 out=ROOT/'cache/policy_v18/integration/tju-ui';out.mkdir(parents=True,exist_ok=True);results=[]
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);site=root/'site';site.mkdir()
  for name in ['admissions.html','applications.html','discovery.html','admissions-data.js','admissions-core.js','admissions.js','workflow.js','discovery.js','discovery-core.js','data.js','search.js','compare-data.js','ui.css']:shutil.copy2(ROOT/'site'/name,site/name)
  server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}/'
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True)
    for width,height in [(1440,1000),(390,844)]:
     for dept,code,name in [('cs','081200','计算机科学与技术'),('software','083500','软件工程'),('cyber','083900','网络空间安全'),('ai','140500','智能科学与技术')]:
      page=browser.new_page(viewport={'width':width,'height':height});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
      query=dict(school='tju',dept=dept,year=2027,degree='phd',route='assessment',track='ordinary',program=code+'|'+name);pid=f'tju-{dept}-2027-phd-assessment-v18'
      page.goto(base+'admissions.html?'+urlencode(query),wait_until='networkidle');page.wait_for_function('window.ADMISSIONS_READY');assert page.locator(f'[data-policy="{pid}"]').count()==1
      materials=page.locator('[data-checklist-field="materials"]').inner_text();assert name in page.locator('#application-checklist').inner_text() and '原文' in materials
      page.locator('#checklist-project').click();page.wait_for_function('window.WORKFLOW_READY');assert page.input_value('#project-program-code')==code
      ids=page.evaluate('applicableEvents(projectForm()).map(r=>r.policy.id)');assert ids and all(x==pid for x in ids),ids
      buttons=page.locator('[data-add-policy-date]');assert buttons.count()>0;buttons.first.click()
      title=f'TJU-{dept}-{width}';page.fill('#project-name',title);page.click('#project-save');page.wait_for_function('(n)=>Object.values(WORKFLOW.projects).some(p=>p.name===n)',arg=title)
      saved=page.evaluate('(n)=>Object.values(WORKFLOW.projects).find(p=>p.name===n)',title);assert saved['deadlines'][0]['policy_id']==pid
      page.locator('[data-project-requirements="'+saved['id']+'"]').click();assert '原文' in page.locator('#project-list').inner_text()
      page.click('[data-section="reminder"]');page.fill('#reminder-title','核对官方材料');page.fill('#reminder-due','2026-10-22');page.select_option('#reminder-project',saved['id']);page.click('#reminder-save');page.wait_for_function('(id)=>Object.values(WORKFLOW.reminders).some(r=>r.project_id===id)',arg=saved['id'])
      page.screenshot(path=str(out/f'{dept}-{width}.png'),full_page=True)
      for program in ['', '085400|电子信息']:
       bad={**query,'program':program};page.goto(base+'applications.html?'+urlencode(bad),wait_until='networkidle');page.wait_for_function('window.WORKFLOW_READY');assert page.evaluate('applicableEvents(projectForm()).length')==0
      if dept!='cs':
       page.goto(base+'discovery.html?'+urlencode(query),wait_until='networkidle');page.wait_for_function('window.DISCOVERY_READY === true');assert '尚未采集' in page.locator('body').inner_text();expected=yaml.safe_load((ROOT/'sites/tju'/f'{dept}.yaml').read_text(encoding='utf8'))['list']['public_url'];assert page.locator('#unit-roster-direct').get_attribute('href')==expected
      assert not errors,errors;assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1');page.close();results.append(dict(dept=dept,width=width,scope=code,project=True,date=True,reminder=True,wrong_program_isolated=True))
    browser.close()
  finally:server.shutdown();server.server_close();thread.join(timeout=2)
 (out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8');print('PASS',len(results),'TJU exact-program project/date/reminder flows; no-program and 085400 isolated')
if __name__=='__main__':main()

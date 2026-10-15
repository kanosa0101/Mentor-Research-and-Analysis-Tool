"""Real v14 policy application flow with isolated private data."""
import json,sys,tempfile,threading
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site

def main():
 out=ROOT/'cache/policy_v14/integration';out.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp);site=render_test_site(root);server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(f'http://127.0.0.1:{server.server_port}/applications.html');page.wait_for_function('window.WORKFLOW_READY')
    page.fill('#project-name','北理工2027硕士统考（隔离验证）');page.fill('#project-year','2027')
    for selector,value in [('school-id','bit'),('dept-id','cs'),('degree','master'),('route','exam'),('track','ordinary')]:page.select_option('#project-'+selector,value)
    assert '提供真实材料' in page.inner_text('#project-form') or page.evaluate('projectChecklist(projectForm()).policies.some(p=>p.id==="bit-2027-master-exam")')
    index=page.evaluate('applicableEvents(projectForm()).findIndex(x=>x.policy.id==="bit-2027-master-exam"&&x.event.kind==="deadline")');assert index>=0
    assert page.evaluate('''(()=>{const p=ADMISSIONS_DATA.policies.find(p=>p.id==="bit-2027-master-exam");const original=p.events[0].label;p.events[0].label=original+String.fromCharCode(34,39);renderGoalEditor();const button=document.querySelector("[data-add-policy-date]");renderGoalEditor();const stable=button===document.querySelector("[data-add-policy-date]");p.events[0].label=original;renderGoalEditor();return stable})()''')
    assert page.evaluate('document.activeElement.id')=='project-year'
    # A pending year change on blur must not replace an identical official-event button mid-click.
    page.click(f'[data-add-policy-date="{index}"]');assert page.evaluate('projectDates.length')==1;page.click('#project-save');page.wait_for_function('Object.values(WORKFLOW.projects).some(p=>p.name.includes("隔离验证"))')
    project=page.evaluate('Object.values(WORKFLOW.projects).find(p=>p.name.includes("隔离验证"))');event=project['deadlines'][0]
    assert event['at']=='2026-10-24T22:00:00+08:00' and event['kind']=='deadline' and event['origin']=='policy'
    assert event['source_ids']==['bit_2027_master_registration_v14'] and event['source_url'].startswith('https://grd.bit.edu.cn/')
    assert all(event.get(k) for k in ['quote','locator','policy_id'])
    page.locator('[data-project-requirements]').first.click();assert '报考点审核' in page.inner_text('#project-list')
    page.locator('[data-project-reminder]').first.click();page.wait_for_function('Object.keys(WORKFLOW.reminders).length===1');reminder=page.evaluate('Object.values(WORKFLOW.reminders)[0]')
    assert reminder['due_date']=='2026-10-24' and reminder['project_id']==project['id'] and not reminder['mentor_id']
    assert event['source_url'] in reminder['notes'] and event['at'] in reminder['notes']
    # Personal material is linked only to the temporary project; source requirements remain visible.
    page.wait_for_function('!document.querySelector("#workspace").disabled');page.locator('[data-project-requirements]').first.click()
    cv=root/'临时简历.txt';cv.write_text('temporary fixture',encoding='utf8')
    page.locator(f'[data-project-section="material"][data-project-id="{project["id"]}"]:not([data-edit-material])').click()
    assert page.locator('#section-material').is_visible()
    assert page.locator('#material-projects').evaluate('(e)=>[...e.selectedOptions].map(o=>o.value)')==[project['id']]
    page.fill('#material-path',str(cv));page.fill('#material-title','临时简历');page.select_option('#material-kind','cv');page.click('#material-save');page.wait_for_function('Object.values(WORKFLOW.materials).some(m=>m.title==="临时简历")')
    page.click('[data-section="project"]');page.locator('[data-project-requirements]').first.click();assert '临时简历' in page.inner_text('#project-list')
    # Two BIT recommendation records are program-specific and historical, not generic CS eligibility.
    assert page.evaluate('ADMISSIONS_DATA.policies.filter(p=>p.school==="bit"&&p.dept==="cs"&&p.route==="recommend").every(p=>p.level==="program"&&p.program&&p.events.every(e=>e.at<"2026-10-15"))')
    for width,height in [(1440,1000),(390,844)]:
     page.set_viewport_size({'width':width,'height':height});page.locator('#project-list h4').first.scroll_into_view_if_needed();page.screenshot(path=str(out/f'bit-policy-project-{width}.png'));assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
     page.locator('#project-list h4',has_text='材料要求与已有文件').evaluate('e=>scrollTo(0,scrollY+e.getBoundingClientRect().top-110)');page.screenshot(path=str(out/f'bit-policy-materials-{width}.png'))
    assert not errors,errors
    (out/'real-policy-flow.json').write_text(json.dumps({'project':project,'official_event':event,'reminder':reminder,'private':'isolated temporary','widths':[1440,390],'errors':errors},ensure_ascii=False,indent=2),encoding='utf8')
    browser.close();print('PASS real BIT policy -> structured project -> materials -> exact cutoff -> source reminder; 1440/390')
  finally:server.shutdown();server.server_close()

if __name__=='__main__':main()

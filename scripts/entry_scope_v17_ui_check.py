"""v17 public entry scope and first-project flow; isolated site/private directory."""
import json
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
import yaml
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from admissions_v15_ui_check import fixture
from crawler.admissions_entries import load_catalog
from build_site import template_environment, write_html, render_discovery_page
from serve import create_server

def main():
    out=ROOT/'cache/v19/entry_scope';out.mkdir(parents=True,exist_ok=True)
    data=fixture();data.update(yaml.safe_load((ROOT/'data/admissions.yaml').read_text(encoding='utf-8')))
    data['entries']=yaml.safe_load((ROOT/'data/admissions_entries.yaml').read_text(encoding='utf-8'))['entries']
    data['checks']=json.loads((ROOT/'data/admissions_checks.json').read_text(encoding='utf-8'))
    # Use the actual registered unit catalog, including pending units, not only mentor-bearing fixture units.
    schools, units=load_catalog(ROOT);data['schools']=schools
    data['units']=[dict(school=s,dept=d,school_name=s,dept_name=d,groups=[],count=0,coverage={'source_dates':{'known':0,'unknown':0}},roster_pending='待补',roster_url='https://example.edu/',notice_url='') for s,ds in units.items() for d in ds]
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);site=root/'site';site.mkdir()
        for name in ['data.js','search.js','compare-data.js','admissions.js','admissions-core.js','discovery.js','discovery-core.js','discovery-data.js','school-catalog.js','browser-library-core.js','browser-library.js','material-actions.js','workflow.js','ui.css']:
            shutil.copyfile(ROOT/'site'/name,site/name)
        (site/'p').mkdir()
        for name in (ROOT/'site/p').glob('*.html'):(site/'p'/name.name).write_text('fixture',encoding='utf-8')
        (site/'admissions-data.js').write_text('window.ADMISSIONS_DATA='+json.dumps(data,ensure_ascii=False)+';',encoding='utf-8')
        for name in ['admissions','applications']:write_html(site/(name+'.html'),template_environment().get_template(name+'.html.j2').render())
        write_html(site/'discovery.html',render_discovery_page(site))
        server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0)
        threading.Thread(target=server.serve_forever,daemon=True).start();base=f'http://127.0.0.1:{server.server_port}/'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);page=browser.new_page();errors=[]
                # This fixture deliberately compares the Oct 16 deadline, Oct 17 exam and Sep deadline.
                # Fix only the isolated browser clock so future/past assertions do not drift with today.
                page.clock.install(time=datetime(2026,10,15,4,tzinfo=timezone.utc))
                page.on('pageerror',lambda e:errors.append(str(e)))
                writes=[];page.on('request',lambda r:writes.append(r.url) if r.method in ('POST','PUT','DELETE') else None)
                target='school=tsinghua&dept=cs&year=2027&degree=phd&route=assessment&track=ordinary'
                if '--workflow-timing-only' in sys.argv:
                    for width in (1440,390):
                        page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                        page.goto(base+'applications.html?school=nudt&dept=ai&year=2027&degree=phd&route=assessment&track=ordinary');page.wait_for_function('window.WORKFLOW_READY')
                        preview=page.inner_text('#project-policy-dates')
                        assert '考核安排，仅适用已达本轮条件者；不代表新报名' in preview
                        assert '该事项已截止；不表示整轮招生结束' in preview
                        buttons=page.locator('[data-add-policy-date]');count=buttons.count()
                        assert count==4
                        for i in range(count):page.locator(f'[data-add-policy-date="{i}"]').click()
                        name=f'隔离国防科大博士时间语义-{width}';page.fill('#project-name',name);page.click('#project-save')
                        page.wait_for_function('name=>Object.values(WORKFLOW.projects).some(p=>p.name===name)',arg=name)
                        project=page.evaluate('name=>Object.values(WORKFLOW.projects).find(p=>p.name===name)',name)
                        assert len(project['deadlines'])==4
                        card=page.locator('#project-list article').filter(has=page.locator(f'[data-edit-project="{project["id"]}"]'))
                        card.locator('details').evaluate_all('(nodes)=>nodes.forEach(n=>n.open=true)')
                        text=card.inner_text();assert '考核安排，仅适用已达本轮条件者；不代表新报名' in text and '报名是否开放仍须核实' not in text
                        exam_index=next(i for i,d in enumerate(project['deadlines']) if d['kind']=='exam')
                        page.locator(f'[data-project-reminder="{project["id"]}"][data-date-index="{exam_index}"]').click()
                        page.wait_for_function('pid=>Object.values(WORKFLOW.reminders).some(r=>r.project_id===pid)',arg=project['id'])
                        reminder=page.evaluate('pid=>Object.values(WORKFLOW.reminders).find(r=>r.project_id===pid)',project['id'])
                        assert '具体事项时刻请查来源' in reminder['notes'] and '具体截止时刻' not in reminder['notes']
                        assert project['deadlines'][exam_index]['quote'] in reminder['notes']
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(out/f'nudt-project-timing-{width}.png'),full_page=True)
                        results.append({'case':f'nudt-project-timing-{width}','project_saved_in_temporary_private':True,'official_dates':4,'reminder_item_wording':True,'overflow':False})
                for width in (() if '--workflow-timing-only' in sys.argv else (1440,390)):
                    page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                    page.goto(base+'admissions.html?school=nudt&dept=ai&year=2027&degree=phd&route=assessment&track=ordinary');page.wait_for_function('window.ADMISSIONS_READY')
                    page.locator('[data-checklist-field="timeline"] > details > summary').click()
                    events=page.locator('#checklist-events');text=events.inner_text()
                    assert '考核安排，仅适用已达本轮条件者；不代表新报名' in text
                    assert '该事项截止（报名/材料/准考证等）；不表示接受新报名' in text
                    assert '该事项已截止；不表示整轮招生结束' in text
                    assert '报名是否开放仍须核实' not in text and '该轮次已截止' not in text
                    cards=page.locator('[data-policy]')
                    assert '是否开放' not in cards.inner_text() if cards.count()==1 else all('是否开放' not in t for t in cards.all_inner_texts())
                    assert '不表示接受新报名' in events.inner_text()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    results.append({'case':f'nudt-event-timing-{width}','exam_not_registration':True,'item_deadline_only':True,'overflow':False})
                    page.screenshot(path=str(out/f'nudt-event-timing-{width}.png'),full_page=True)
                for width in (() if any(flag in sys.argv for flag in ('--timing-only','--workflow-timing-only')) else (1440,390)):

                    page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                    # Check empty project discovery before admissions assertions, to reproduce original missing action.
                    page.goto(base+'discovery.html?'+target+'&name=PRIVATE_NAME&notes=PRIVATE_NOTE');page.wait_for_function('window.DISCOVERY_READY')
                    if page.locator('#workflow-tools').get_attribute('open') is None:page.locator('#workflow-tools > summary').click()
                    if page.locator('#project-options').get_attribute('open') is None:page.locator('#project-options > summary').click()
                    assert page.locator('#review-project-create').is_visible(), 'empty project selector must offer creation'
                    assert '尚未创建申请项目' in page.inner_text('#review-project-api')
                    href=page.get_attribute('#review-project-create','href');assert 'PRIVATE_' not in href and 'project=' not in href
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(out/f'empty-create-{width}-viewport.png'))
                    page.click('#review-project-create');page.wait_for_function('window.WORKFLOW_READY')
                    assert page.input_value('#project-year')=='2027' and page.input_value('#project-degree')=='phd'
                    assert page.input_value('#project-route')=='assessment'
                    assert not writes,'viewing/prefill must not save'
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    results.append({'case':f'empty-project-{width}','href':href,'no_writes':True})
                    page.screenshot(path=str(out/f'empty-prefill-{width}.png'),full_page=True)
                    for tag,query in [('school-degree','school=tsinghua&degree=phd'),('without-track',target.replace('&track=ordinary',''))]:
                        page.goto(base+'admissions.html?'+query);page.wait_for_function('window.ADMISSIONS_READY')
                        page.locator('#official-entry-details > summary').click()
                        box=page.locator('#unit-entries');text=box.inner_text()
                        assert '候选政策原文，补全目标后核对适用' in text and '本目标政策原文' not in text
                        ids=box.locator('[data-policy-entry]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.policyEntry)')
                        assert 'tsinghua-2027-phd-assessment-v16pilot' in ids
                        assert all('phd' in id for id in ids)
                        if tag=='school-degree':assert ids==['tsinghua-2027-phd-assessment-v16pilot'], 'school-only must not imply a specific department'
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        results.append({'case':f'partial-{tag}-{width}','candidate_only':True,'policies':ids,'overflow':False})
                        page.screenshot(path=str(out/f'partial-{tag}-{width}-viewport.png'))
                    for school in ['tsinghua','zju']:
                        page.goto(base+'admissions.html?'+target.replace('tsinghua',school));page.wait_for_function('window.ADMISSIONS_READY')
                        page.locator('#official-entry-details > summary').click()
                        box=page.locator('#unit-entries');assert '本目标政策原文' in box.inner_text()
                        assert box.locator('[data-policy-entry]').count()>0
                        assert all('phd' in x for x in box.locator('[data-policy-entry]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.policyEntry)'))
                        assert box.locator('a[href="https://yz.chsi.com.cn/bsmlcx/"]').count()==1
                        assert box.locator('a[href="https://yz.chsi.com.cn/zsml/index.html"]').count()==0
                        if school=='tsinghua':
                            assert not page.locator('[data-entry-source="school_page"]').is_visible()
                            page.locator('#other-scope-entries summary').click();assert page.locator('[data-entry-source="school_page"]').is_visible()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(out/f'phd-{school}-{width}.png'),full_page=True)
                        page.screenshot(path=str(out/f'phd-{school}-{width}-viewport.png'))
                        results.append({'case':f'phd-{school}-{width}','overflow':False})
                    page.goto(base+'discovery.html?'+target.replace('tsinghua','nankai')+'&name=PRIVATE_NAME&notes=PRIVATE_NOTE');page.wait_for_function('window.DISCOVERY_READY')
                    page.fill('#intent-name','不存在的隔离回归姓名');page.click('#apply-criteria')
                    page.wait_for_function('view.length===0')
                    assert page.locator('#candidate-list .results-card').count()==0
                    link=page.locator('#empty-unit-official');assert link.is_visible()
                    href=link.get_attribute('href');assert 'school=nankai' in href and 'dept=cs' in href and 'degree=phd' in href and 'PRIVATE_' not in href
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    results.append({'case':f'empty-unit-{width}','href':href,'overflow':False})
                    page.screenshot(path=str(out/f'empty-unit-{width}-viewport.png'))
                    page.route('**/api/discovery**',lambda r:r.fulfill(status=503,content_type='application/json',body='{"error":"service unavailable"}'))
                    page.goto(base+'discovery.html?'+target);page.wait_for_function('window.DISCOVERY_READY')
                    if page.locator('#workflow-tools').get_attribute('open') is None:page.locator('#workflow-tools > summary').click()
                    if page.locator('#project-options').get_attribute('open') is None:page.locator('#project-options > summary').click()
                    assert page.locator('#review-project-create').is_visible()
                    assert '本机服务不可用' in page.inner_text('#review-project-api')
                    for control in ['save-criteria','discovery-backup','discovery-restore']:
                        assert page.locator('#'+control).is_disabled(), 'unavailable storage must not enable writes'
                    assert page.locator('#candidate-list .results-card').count()>0
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    results.append({'case':f'service-unavailable-{width}','still_browsable':True,'overflow':False})
                    page.unroute('**/api/discovery**')
                assert not errors,errors
                assert len(writes)==4 if '--workflow-timing-only' in sys.argv else not writes,writes
                browser.close()
        finally:server.shutdown();server.server_close()
    (out/('workflow-timing-results.json' if '--workflow-timing-only' in sys.argv else 'timing-results.json' if '--timing-only' in sys.argv else 'results.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print('PASS v17 UI:',len(results),'cases')

if __name__=='__main__':main()

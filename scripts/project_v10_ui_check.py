"""Structured project targets, policy dates and private workflow UI regression."""
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server
from scripts.workflow_v8_ui_check import render_test_site


def main():
    out = ROOT / 'cache/ux_v10/project'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = render_test_site(root)
        shutil.copyfile(ROOT / 'site/admissions-core.js', site / 'admissions-core.js')
        server = create_server(site=site, outreach=root / 'private/outreach.yaml', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                base = f'http://127.0.0.1:{server.server_port}'
                page.goto(base + '/applications.html')
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.evaluate('reminderDay("2026-10-20T23:30:00-05:00")') == '2026-10-21'
                assert page.evaluate('dateStatus({at:new Date().toLocaleDateString("sv-SE",{timeZone:"Asia/Shanghai"}),kind:"deadline",origin:"policy"})').find('已截止') == -1
                assert '登记时来源' in page.evaluate('snapshotLinks({source_ids:[Object.keys(ADMISSIONS_DATA.sources)[0]],source_url:"https://example.org/historical",origin:"policy"})')
                assert page.locator('#project-school-id').count() == 1, 'explicit target school selector required'
                legacy = page.evaluate('api("/projects", {name:"旧文本项目", school:"北京大学", college:"计算机学院", application_type:"硕士 / 统考",year:2026}, "POST")')
                page.evaluate('refresh()')
                assert '结构化目标尚未完整' in page.inner_text('#project-list')
                page.click('[data-edit-project="' + legacy['id'] + '"]')
                assert page.input_value('#project-school-id') == '', 'legacy free text must not infer a target'
                page.select_option('#project-school-id', 'pku')
                page.select_option('#project-dept-id', 'cs')
                page.select_option('#project-degree', 'master')
                page.select_option('#project-route', 'recommend')
                page.select_option('#project-track', 'ordinary')
                page.click('#project-save')
                page.wait_for_function('(id)=>WORKFLOW.projects[id].school_id==="pku"', arg=legacy['id'])
                assert '目标与要求' in page.inner_text('#project-list')
                page.click('[data-edit-project="' + legacy['id'] + '"]')
                assert page.input_value('#project-school-id') == 'pku'
                page.fill('#project-date-label', '个人计划：核对材料')
                page.fill('#project-date-at', '2026-10-20')
                page.click('#project-add-date')
                page.click('#project-save')
                page.wait_for_function('(id)=>WORKFLOW.projects[id].deadlines.length===1', arg=legacy['id'])
                page.locator('[data-project-requirements]').first.click()
                assert '个人计划' in page.inner_text('#project-list')
                assert '参考来源未核验' in page.inner_text('#project-list')
                page.locator('[data-project-reminder]').first.click()
                page.wait_for_function('Object.keys(WORKFLOW.reminders).length===1')
                page.locator('[data-project-requirements]').first.click()
                page.locator('[data-project-reminder]').first.click()
                assert page.evaluate('Object.keys(WORKFLOW.reminders).length') == 1
                # Import an exact official event without changing its kind or evidence.
                candidate = page.evaluate('ADMISSIONS_DATA.policies.find(p=>p.dept&&p.track!=="special"&&p.fields.materials&&p.events?.some(e=>e.kind==="deadline"))')
                assert candidate, 'fixture requires an exact department policy event'
                fields = {'school_id': candidate['school'], 'dept_id': candidate['dept'], 'year': candidate['year'], 'degree': candidate['degree'], 'route': candidate['route'], 'track': 'ordinary', 'program_code': candidate.get('program_code', ''), 'program_name': candidate.get('program', '')}
                page.evaluate('({id,fields})=>api("/projects/"+id,fields,"PATCH")', {'id': legacy['id'], 'fields': fields})
                page.evaluate('refresh()')
                cv = root / '个人简历.txt'
                cv.write_text('temporary UI test resume', encoding='utf-8')
                page.evaluate('({id,path})=>api("/materials",{path,title:"个人简历（临时测试）",kind:"cv",project_ids:[id]},"POST")', {'id': legacy['id'], 'path': str(cv)})
                page.evaluate('refresh()')
                page.click('[data-edit-project="' + legacy['id'] + '"]')
                event_index = page.evaluate('applicableEvents(projectForm()).findIndex(row=>row.event.kind==="deadline")')
                page.click(f'[data-add-policy-date="{event_index}"]')
                page.click('#project-save')
                page.wait_for_function('(id)=>WORKFLOW.projects[id].deadlines.some(d=>d.origin==="policy")', arg=legacy['id'])
                saved = page.evaluate('(id)=>WORKFLOW.projects[id]', legacy['id'])
                official = next(d for d in saved['deadlines'] if d['origin'] == 'policy')
                assert official['kind'] in ('deadline', 'exam', 'qualification')
                assert official['quote'] and official['locator'] and official['source_url']
                assert official['source_url'] == page.evaluate('(id)=>ADMISSIONS_DATA.sources[id].url', official['source_ids'][0])
                page.evaluate('(id)=>{window.testPolicies=ADMISSIONS_DATA.policies;ADMISSIONS_DATA.policies=ADMISSIONS_DATA.policies.filter(p=>p.id!==id);render();}', official['policy_id'])
                page.locator('[data-project-requirements]').first.click()
                assert '原政策已变化 / 未找到' in page.inner_text('#project-list')
                page.evaluate('ADMISSIONS_DATA.policies=window.testPolicies;render()')
                assert page.evaluate('document.querySelector("#project-list").getBoundingClientRect().top < document.querySelector("#project-form").getBoundingClientRect().top')
                page.locator('[data-project-requirements]').first.click()
                for width, height in ((1440, 1000), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.evaluate('window.scrollTo(0,0)')
                    page.screenshot(path=str(out / f'project-policy-{width}-viewport.png'))
                    page.screenshot(path=str(out / f'project-policy-{width}-full.png'), full_page=True)
                    page.locator('#project-list h4').first.evaluate('node=>window.scrollTo(0,window.scrollY+node.getBoundingClientRect().top-110)')
                    page.screenshot(path=str(out / f'project-requirements-{width}-viewport.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.evaluate('window.testUnits=ADMISSIONS_DATA.units;ADMISSIONS_DATA.units=[];render()')
                page.click('[data-edit-project="' + legacy['id'] + '"]')
                assert page.input_value('#project-school-id') == fields['school_id']
                assert page.input_value('#project-dept-id') == fields['dept_id']
                assert '目录未收录，需核对' not in page.locator('#project-school-id option:checked').inner_text(), '学校目录独立于院系列表'
                assert '目录未收录，需核对' in page.locator('#project-dept-id option:checked').inner_text()
                page.click('#project-save')
                page.wait_for_function('document.querySelector("#project-save").textContent==="新增项目"')
                page.wait_for_function('!document.querySelector("#workspace").disabled')
                assert page.evaluate('(id)=>WORKFLOW.projects[id].school_id', legacy['id']) == fields['school_id']
                page.evaluate('ADMISSIONS_DATA.units=window.testUnits;render()')
                page.click('[data-edit-project="' + legacy['id'] + '"]')
                page.fill('#project-year', '2028')
                page.evaluate('()=>{window.confirmMessages=[];window.confirm=message=>{window.confirmMessages.push(message);return false}}')
                page.locator('#project-form').evaluate('form=>form.requestSubmit()')
                assert page.evaluate('window.confirmMessages.length') == 1, page.evaluate('({messages:window.confirmMessages,editing,projectDates,form:projectForm(),projects:WORKFLOW.projects,valid:document.querySelector("#project-form").checkValidity()})')
                assert page.input_value('#project-year') == '2028'
                assert page.evaluate('(id)=>WORKFLOW.projects[id].year', legacy['id']) == fields['year']
                page.evaluate('()=>{window.confirm=message=>{window.confirmMessages.push(message);return true}}')
                page.locator('#project-form').evaluate('form=>form.requestSubmit()')
                page.wait_for_function('(id)=>WORKFLOW.projects[id].year===2028', arg=legacy['id'])
                assert page.evaluate('(id)=>WORKFLOW.projects[id].deadlines.map(d=>d.origin)', legacy['id']) == ['manual']
                # Saved project scope wins over conflicting incoming URL and mentor unit.
                mentor = page.evaluate('(school)=>MENTOR_DATA.find(p=>p.school!==school).page', fields['school_id'])
                target = page.evaluate('({id,mentor})=>api("/targets",{project_id:id,mentor_id:mentor},"POST")', {'id': legacy['id'], 'mentor': mentor})
                page.goto(base + '/desk.html?target=' + target['id'] + '&year=2029&school=other&dept=other&track=special')
                page.wait_for_function('window.CONTACT_READY')
                assert page.evaluate('forwardedGoal().year') == 2028
                assert page.evaluate('forwardedGoal().school') == fields['school_id']
                assert '与项目目标单位不同' in page.inner_text('#incoming-goal')
                other = page.evaluate('api("/projects",{name:"第二项目",school_id:"pku",dept_id:"cs",year:2027,degree:"phd",route:"assessment",track:"ordinary"},"POST")')
                page.goto(base + '/applications.html?project=' + other['id'])
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.input_value('#filter-project') == other['id']
                page.locator('[data-project-requirements]').first.click()
                desk_link = page.locator('#project-list a[href*="desk.html"]').get_attribute('href')
                assert 'project=' + other['id'] in desk_link
                assert all(other['id'] not in href for href in page.locator('#project-list a[href*="admissions.html"], #project-list a[href*="discovery.html"]').evaluate_all('(nodes)=>nodes.map(n=>n.href)'))
                page.goto(base + '/' + desk_link.replace('year=2027', 'year=2029') + '&mentor=' + mentor)
                page.wait_for_function('window.CONTACT_READY')
                assert page.input_value('#target-project') == other['id']
                assert page.input_value('#targets-project') == other['id']
                assert page.evaluate('forwardedGoal().year') == 2027
                assert page.evaluate('forwardedGoal().school') == 'pku'
                page.click('#target-save')
                page.wait_for_function('(id)=>Object.values(FLOW.targets).some(t=>t.project_id===id)', arg=other['id'])
                assert page.evaluate('target().project_id') == other['id']
                manage = page.evaluate('manageUrl()')
                assert 'project=' + other['id'] in manage
                page.goto(base + '/' + manage)
                page.wait_for_function('window.WORKFLOW_READY')
                assert page.input_value('#filter-project') == other['id']
                page.goto(base + '/desk.html?view=targets&project=not-a-real-project&year=2028&mentor=' + mentor)
                page.wait_for_function('window.CONTACT_READY')
                assert page.evaluate('currentTarget') == ''
                assert page.input_value('#target-project') == ''
                page.goto(base + '/applications.html')
                page.wait_for_function('window.WORKFLOW_READY')
                page.locator('[data-project-requirements]').first.click()
                for width, height in ((1440, 1000), (390, 844)):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.evaluate('window.scrollTo(0,0)')
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'horizontal overflow'
                    page.screenshot(path=str(out / f'project-{width}.png'), full_page=True)
                    page.screenshot(path=str(out / f'project-{width}-viewport.png'))
                assert not errors, errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    print('Project v10 UI checks passed; only temporary private records used.')


if __name__ == '__main__':
    main()

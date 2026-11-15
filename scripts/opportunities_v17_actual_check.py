"""Actual public catalog and isolated local application/material/reminder flow."""
import copy
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from crawler import opportunity_util
from scripts import build_site,serve,serve_public
from scripts.release_page_v1_ui_check import signatures


def main():
    output=ROOT/'cache/v17/opportunity-actual';output.mkdir(parents=True,exist_ok=True)
    catalog=opportunity_util.load(ROOT);before=signatures();results=[]
    cibr=next(o for o in catalog['opportunities'] if o['school_id']=='cibr')
    rolling=next(o for o in catalog['opportunities'] if opportunity_util.state(o)=='rolling')
    assert len(catalog['opportunities'])==18
    with tempfile.TemporaryDirectory(prefix='opportunity-actual-v17-') as directory:
        root=Path(directory);site=root/'site';site.mkdir()
        for file in list((ROOT/'site').glob('*.js'))+list((ROOT/'site').glob('*.css')):
            shutil.copyfile(file,site/file.name)
        for name in ('opportunities','applications','local'):
            (site/(name+'.html')).write_text(build_site.template_environment().get_template(name+'.html.j2').render(),encoding='utf-8')
        (site/'opportunities-data.js').write_text('window.OPPORTUNITIES='+json.dumps(catalog,ensure_ascii=False).replace('<','\\u003c')+';',encoding='utf-8')
        with patch.object(opportunity_util,'observed',side_effect=lambda root:copy.deepcopy(catalog)),sync_playwright() as pw:
            browser=pw.chromium.launch()
            try:
                for mode in ('public','local'):
                    for width in (1440,390):
                        private=root/f'private-{width}'
                        server=serve_public.create_server(root,'127.0.0.1',0) if mode=='public' else serve.create_server(site,private/'outreach.yaml',0,private/'workflow.yaml')
                        threading.Thread(target=server.serve_forever,daemon=True).start()
                        base=f'http://127.0.0.1:{server.server_port}'
                        context=browser.new_context(viewport={'width':width,'height':950});page=context.new_page();errors=[];writes=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.on('request',lambda req:writes.append(req.url) if req.method not in ('GET','HEAD','OPTIONS') else None)
                        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                        def flow():
                            response=context.request.get(base+'/api/workflow');assert response.ok,response.text();return response.json()
                        try:
                            page.goto(base+'/opportunities.html',wait_until='networkidle');page.wait_for_function('opportunityModeReady')
                            counts=page.evaluate('Object.fromEntries(["open","open_month","rolling","upcoming","review","closed"].map(s=>[s,opportunityRows.filter(o=>OpportunityRules.state(o)===s).length]))')
                            assert counts=={'open':1,'open_month':1,'rolling':6,'upcoming':1,'review':1,'closed':8},counts
                            page.locator('#opportunity-state').select_option('open')
                            card=page.locator(f'[data-opportunity="{cibr["id"]}"]')
                            assert '2026-11-30T17:00:00+08:00' in card.locator('.opportunity-facts').inner_text()
                            assert '原文未明确毕业届别' in card.locator('.opportunity-cohort').inner_text()
                            card.locator('summary').filter(has_text='材料与报名方式').click()
                            assert card.get_by_text(cibr['materials'][2],exact=True).is_visible()
                            assert '独立完成' in cibr['materials'][2] and 'AI协助' in cibr['materials'][2]
                            attachment=card.locator('details').filter(has=page.locator('summary',has_text='官方申请表与核验依据')).nth(1)
                            attachment.locator('summary').click()
                            assert 'DOCX个人陈述说明' in attachment.inner_text() and 'AI协助' in attachment.inner_text()
                            assert '核对 2026-11-15' in attachment.inner_text()
                            card.evaluate('(el)=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY-110)')
                            page.screenshot(path=str(output/f'{mode}-cibr-{width}.png'))
                            attachment.evaluate('(el)=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY-110)')
                            page.screenshot(path=str(output/f'{mode}-docx-{width}.png'))
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                            if mode=='public':
                                assert not page.locator('[data-save-opportunity]').count()
                                assert card.locator('a[href^="local.html?id="]').count()==1
                                page.locator('#opportunity-state').select_option('open_month')
                                assert '2027-01（具体日期未公布）' in page.locator('.opportunity-facts').inner_text()
                                page.locator('#opportunity-state').select_option('rolling')
                                assert page.locator('[data-opportunity]').count()==6
                                assert page.locator('.research-direction').first.is_visible()
                                assert not writes,writes
                                results.append({'mode':mode,'width':width,'counts':counts,'cibr_unknown_graduation_preserved':True,'docx_independent_statement_visible':True,'no_writes':True,'page_errors':errors})
                                continue
                            saved_ids=[]
                            for item in (cibr,rolling):
                                page.goto(base+'/opportunities.html?id='+item['id'],wait_until='networkidle');page.wait_for_function('opportunityModeReady')
                                page.locator('[data-save-opportunity]').click()
                                page.locator('#opportunity-name').fill('隔离验收 · '+item['title'])
                                reminder=page.locator('#opportunity-reminder').get_attribute('min')
                                page.locator('#opportunity-reminder').fill(reminder)
                                assert page.locator('#opportunity-reminder').get_attribute('max')==(item['deadline'][:10] if item==cibr else '')
                                page.locator('#opportunity-confirm').click()
                                page.wait_for_function('!document.getElementById("opportunity-save").open')
                                saved=flow();project=next(p for p in saved['projects'].values() if p['opportunity']['id']==item['id']);pid=project['id'];saved_ids.append(pid)
                                assert project['opportunity']==item
                                assert project['year'] is None and project['degree']=='' and project['route']==''
                                assert project['opportunity']['graduation_year'] is None
                                if item==cibr:assert project['school_id']=='' and project['dept_id']=='' and project['school']==item['school_name']
                                page.locator('#opportunity-result a').click();page.wait_for_function('window.WORKFLOW_READY')
                                assert item['materials'][0] in page.locator('#project-list').inner_text()
                                if item==cibr:
                                    assert 'AI协助' in page.locator('#project-list').inner_text()
                                    assert page.locator('#project-list a').filter(has_text='官方申请材料附件').count()==2
                                else:assert item['application_window']['quote'] in page.locator('#project-list').inner_text()
                                page.locator('[data-section="material"]').click()
                                material=private/(item['id']+'.pdf');material.parent.mkdir(parents=True,exist_ok=True);material.write_bytes(b'%PDF-1.4\n% isolated metadata-only fixture\n%%EOF\n')
                                page.locator('#material-path').fill(str(material.resolve()))
                                page.locator('#material-title').fill('验收材料 · '+item['id'])
                                page.locator('#material-kind').select_option('application')
                                page.locator('#material-projects').select_option(pid)
                                page.locator('#material-save').click()
                                page.wait_for_function('title=>Object.values(WORKFLOW.materials).some(m=>m.title===title)',arg='验收材料 · '+item['id'])
                                page.locator('[data-section="reminder"]').click()
                                page.locator('#reminder-title').fill('核对材料与官方余位 · '+item['id'])
                                page.locator('#reminder-due').fill(reminder)
                                page.locator('#reminder-project').select_option(pid)
                                page.locator('#reminder-save').click()
                                page.wait_for_function('id=>Object.values(WORKFLOW.reminders).filter(r=>r.project_id===id).length===2',arg=pid)
                                before_duplicate=(private/'workflow.yaml').read_bytes()
                                duplicate=context.request.post(base+'/api/workflow/opportunities',data={'opportunity_id':item['id'],'name':'不覆盖已有项目','reminder_date':reminder})
                                assert duplicate.ok and duplicate.json()=={'project_id':pid,'duplicate':True},duplicate.text()
                                assert (private/'workflow.yaml').read_bytes()==before_duplicate
                                current=flow();assert current['projects'][pid]['opportunity']==item
                                assert len([m for m in current['materials'].values() if pid in m['project_ids']])==1
                                assert len([r for r in current['reminders'].values() if r['project_id']==pid])==2
                                page.locator('[data-section="project"]').click()
                                assert '关联文件 1' in page.locator('#project-list').inner_text()
                                page.locator('#project-list').scroll_into_view_if_needed();page.screenshot(path=str(output/f'local-project-{item["school_id"]}-{width}.png'))
                                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                            assert len(flow()['projects'])==2 and len(flow()['materials'])==2 and len(flow()['reminders'])==4
                            results.append({'mode':mode,'width':width,'projects':saved_ids,'materials':2,'reminders':4,'duplicates_preserve_file':True,'unknown_cibr_goal_preserved':True,'snapshots_equal_actual_catalog':True,'page_errors':errors})
                        finally:
                            context.close();server.shutdown();server.server_close()
                        assert not errors,errors
            finally:browser.close()
    assert signatures()==before,'Actual private files changed'
    (output/'results.json').write_text(json.dumps({'passed':True,'private_files_unchanged':True,'cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True))


if __name__=='__main__':main()

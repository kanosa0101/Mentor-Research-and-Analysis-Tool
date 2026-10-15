"""Real NWPU public policies; all project writes isolated in a temporary private directory."""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
import yaml
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.admissions_v15_ui_check import fixture
from scripts.build_site import template_environment, write_html
from scripts.serve import create_server
from scripts import serve
from unittest.mock import patch

def main():
    out=ROOT/'cache/policy_v18/charters/ui';out.mkdir(parents=True,exist_ok=True)
    fragment=yaml.safe_load((out.parent/'policies.fragment.yaml').read_text(encoding='utf-8'))
    point=next(p for p in fragment['policies'] if p.get('applies_if'))
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);site=root/'site';site.mkdir()
        for name in ('admissions.js','admissions-core.js','ui.css','workflow.js'):
            shutil.copy2(ROOT/'site'/name,site/name)
        data=fixture();data.update(policies=fragment['policies'],sources=fragment['sources'],checks=json.loads((out.parent/'checks.fragment.json').read_text(encoding='utf-8')),entries=[])
        (site/'admissions-data.js').write_text('window.ADMISSIONS_DATA='+json.dumps(data,ensure_ascii=False)+';',encoding='utf-8')
        (site/'data.js').write_text('window.MENTOR_DATA=[];',encoding='utf-8')
        for name in ('admissions','applications'):
            write_html(site/(name+'.html'),template_environment().get_template(name+'.html.j2').render())
        server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0)
        context={'units': {u['school']: {v['dept'] for v in data['units'] if v['school']==u['school']} for u in data['units']}, 'policies':data['policies'], 'sources':data['sources']}
        context_patch=patch.object(serve.projects,'load_context',return_value=context);context_patch.start()
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)+'/'
        query='school=nwpu&dept=cs&year=2027&degree=master&route=exam&track=ordinary'
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                for width,height in ((1440,1000),(390,844)):
                    page=browser.new_page(viewport={'width':width,'height':height});errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(base+'admissions.html?'+query,wait_until='networkidle');page.wait_for_function('window.ADMISSIONS_READY')
                    card=page.locator('[data-policy="'+point['id']+'"]')
                    assert '条件性参考：仅适用于' in card.inner_text()
                    assert '学校层条件要求' in card.locator('span.scope').inner_text()
                    assert '范围：须满足上列适用条件' in card.locator('p.scope').inner_text()
                    assert '条件性参考：仅适用于' in page.locator('[data-policy-entry="'+point['id']+'"]').inner_text()
                    assert '条件性参考：仅适用于' in page.locator('[data-checklist-field="materials"]').inner_text()
                    assert '学校规则已整理 · 1 条摘要' in page.locator('#policy-layer-coverage').inner_text()
                    assert '条件性参考 2 条' in page.locator('#policy-layer-coverage').inner_text()
                    page.screenshot(path=str(out/f'nwpu-policy-{width}.png'),full_page=True)
                    card.scroll_into_view_if_needed();page.screenshot(path=str(out/f'nwpu-policy-{width}-viewport.png'))
                    card.locator('summary').click();card.get_by_role('link',name='建立申请项目 →').click();page.wait_for_function('window.WORKFLOW_READY')
                    assert page.input_value('#project-school-id')=='nwpu'
                    assert page.input_value('#project-dept-id')=='cs'
                    ids=page.evaluate('applicableEvents(projectForm()).map(row=>row.policy.id)')
                    assert point['id'] not in ids and len(ids)==3,ids
                    assert '2026-10-31' not in page.locator('#project-policy-dates').inner_text()
                    page.fill('#project-date-label','个人准备计划');page.fill('#project-date-at','2026-10-22');page.click('#project-add-date')
                    # A historical saved snapshot is retained; making it conditional does not silently delete private records.
                    page.evaluate('(id)=>{const p=ADMISSIONS_DATA.policies.find(p=>p.id===id);projectDates.push(policyDate({policy:p,event:p.events[0]}));renderGoalEditor()}',point['id'])
                    assert '条件待本人核对' in page.locator('#project-dates').inner_text()
                    page.evaluate('projectDates.pop();renderGoalEditor()')
                    page.fill('#project-name','西工大临时申请'+str(width))
                    page.click('#project-save');page.wait_for_function('(name)=>Object.values(WORKFLOW.projects).some(p=>p.name===name)',arg='西工大临时申请'+str(width))
                    saved=page.evaluate('(name)=>Object.values(WORKFLOW.projects).find(p=>p.name===name)','西工大临时申请'+str(width))
                    assert [d['origin'] for d in saved['deadlines']]==['manual']
                    req=page.locator('[data-project-requirements="'+saved['id']+'"]');req.click()
                    body=page.locator('#project-list').inner_text()
                    assert '条件性参考：仅适用于' in body and '未确认专业适用' not in body
                    page.screenshot(path=str(out/f'nwpu-project-{width}.png'),full_page=True)
                    req.scroll_into_view_if_needed();page.screenshot(path=str(out/f'nwpu-project-{width}-viewport.png'))
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
                    assert not errors,errors
                    page.close()
                browser.close()
            print('PASS 1440/390 real NWPU policy → project prefill; conditional source/cards/materials, no 6112 auto date; manual and historical snapshots retained')
        finally:
            context_patch.stop();server.shutdown();server.server_close();thread.join(timeout=2)

if __name__=='__main__':main()

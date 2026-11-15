"""Browser plan handoff on real APIs, isolated private files, desktop and phone."""
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
from scripts import serve,serve_public,build_site
from scripts.release_page_v1_ui_check import signatures
from crawler import opportunity_util


def main():
    out=ROOT/'cache/v16/journey';out.mkdir(parents=True,exist_ok=True)
    before=signatures();results=[]
    catalog=opportunity_util.load(ROOT)
    mentor='pku-cs-zhangshanghang'
    if not (ROOT/'site/p'/f'{mentor}.html').exists():mentor=next((ROOT/'site/p').glob('pku-cs-*.html')).stem
    with sync_playwright() as pw, tempfile.TemporaryDirectory(prefix='mentor-journey-v16-') as directory:
        root=Path(directory);site=root/'site';site.mkdir();(site/'p').mkdir()
        for file in list((ROOT/'site').glob('*.js'))+list((ROOT/'site').glob('*.css')):shutil.copy2(file,site/file.name)
        if (ROOT/'site/mentor-parts').exists():shutil.copytree(ROOT/'site/mentor-parts',site/'mentor-parts')
        for name in ('start','local','desk','applications'):
            build_site.write_html(site/(name+'.html'),build_site.template_environment().get_template(name+'.html.j2').render())
        shutil.copy2(ROOT/'site/p'/f'{mentor}.html',site/'p'/f'{mentor}.html')
        (site/'school-catalog.js').write_text('window.SCHOOL_CATALOG='+json.dumps({'schools':[{'id':'pku','name':'北京大学'},{'id':'tsinghua','name':'清华大学'}],'units':[{'school':'pku','school_name':'北京大学','dept':'cs','dept_name':'计算机学院'},{'school':'tsinghua','school_name':'清华大学','dept':'cs','dept_name':'计算机系'}]},ensure_ascii=False)+';',encoding='utf-8')
        (root/'data').mkdir();(root/'data/opportunities.json').write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
        browser=pw.chromium.launch()
        try:
            for width in (1440,390):
                private=root/f'private-{width}'
                server=serve.create_server(site,private/'outreach.yaml',0,private/'workflow.yaml')
                threading.Thread(target=server.serve_forever,daemon=True).start()
                base=f'http://127.0.0.1:{server.server_port}'
                context=browser.new_context(viewport={'width':width,'height':950})
                page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                def api(path):
                    r=context.request.get(base+path);assert r.ok,r.text();return r.json()
                with patch.object(serve.opportunities,'observed',return_value=catalog):
                    try:
                        page.goto(base+'/start.html',wait_until='networkidle');page.wait_for_function('window.START_READY')
                        assert not (private/'workflow.yaml').exists()
                        page.locator('#target-interest').fill('系统安全')
                        page.locator('.school-directory summary').click()
                        for school in ('pku','tsinghua'):page.locator('#start-school-options input[value='+school+']').check()
                        page.locator('#target-form button[type=submit]').click()
                        target=page.evaluate('BrowserLibraryCore.read(localStorage).targets[0]')
                        page.locator('#tab-todos').click();page.locator('#todo-title').fill('准备成绩单');page.locator('#todo-date').fill('2030-12-01');page.locator('#todo-target').select_option(target['id']);page.locator('#todo-form button[type=submit]').click()
                        page.locator('#todo-title').fill('整理研究经历');page.locator('#todo-form button[type=submit]').click()
                        page.locator('#tab-targets').click();page.locator('[data-plan-kind=target] [data-plan-convert]').click()
                        page.locator('#plan-confirm').click();assert '一所学校' in page.locator('#plan-status').inner_text();assert not (private/'workflow.yaml').exists()
                        page.locator('#plan-school').select_option('pku');page.locator('#plan-notes').fill('验收个人备注');page.locator('#plan-confirm').click()
                        page.locator('#plan-status a').first.wait_for()
                        flow=api('/api/workflow');pid=next(iter(flow['projects']));project=flow['projects'][pid]
                        assert project['year'] is None and project['route']=='recommend' and project['school_id']=='pku'
                        assert '本科毕业届别：2028' in project['notes'] and '整理研究经历' in project['notes'] and len(flow['reminders'])==1
                        page.locator('#plan-cancel').click();awaiting=(private/'workflow.yaml').read_bytes()
                        page.locator('[data-plan-kind=target] [data-plan-convert]').click();page.locator('#plan-school').select_option('pku');page.locator('#plan-confirm').click();page.wait_for_function("document.getElementById('plan-status').textContent.includes('已有对应项目')")
                        assert (private/'workflow.yaml').read_bytes()==awaiting
                        page.locator('#plan-cancel').click();page.locator('#local-overview').scroll_into_view_if_needed();assert '准备成绩单' in page.locator('#local-next-actions').inner_text()
                        page.screenshot(path=str(out/f'overview-{width}.png'))
                        page.goto(base+'/local.html',wait_until='networkidle');page.goto(base+'/start.html',wait_until='networkidle');assert page.locator('#target-interest').input_value()=='系统安全';assert page.locator('#target-school-chips button').count()==2
                        for kind,url,title in [('mentor','p/'+mentor+'.html?school=pku&dept=cs','导师收藏'),('notice','notices.html?notice_cycle=all&school=pku&dept=cs&q=test','招生通知收藏'),('opportunity','opportunities.html?id='+catalog['opportunities'][0]['id'],'机会收藏')]:
                            page.evaluate("item=>{const saved=BrowserLibraryCore.bookmark(BrowserLibraryCore.read(localStorage),item);BrowserLibraryCore.write(localStorage,saved.data);window.dispatchEvent(new StorageEvent('storage',{key:BrowserLibraryCore.KEY}));}",{'kind':kind,'url':url,'title':title})
                            page.locator('#tab-bookmarks').click();row=page.locator('[data-plan-kind=bookmark]').filter(has_text=title);row.locator('[data-plan-convert]').click();page.locator('#plan-confirm').click();page.locator('#plan-status a').first.wait_for();page.locator('#plan-cancel').click()
                        flow=api('/api/workflow');assert len(flow['projects'])==4
                        assert any(p['mentor_ids']==[mentor] and p['dept_id']=='cs' for p in flow['projects'].values())
                        assert any(p.get('opportunity')==catalog['opportunities'][0] for p in flow['projects'].values())
                        assert any(p['name']=='招生通知收藏' and p['school_id']=='pku' and p['dept_id']=='cs' for p in flow['projects'].values())
                        page.locator('#tab-targets').click();page.locator('[data-plan-kind=target] [data-plan-convert]').click();page.screenshot(path=str(out/f'transfer-{width}.png'));assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.locator('#plan-cancel').click()
                        other=context.request.post(base+'/api/workflow/projects',data={'name':'另一个项目','mentor_ids':[mentor]}).json()
                        reminder=context.request.post(base+'/api/workflow/reminders',data={'title':'其他项目的任务','project_id':other['id'],'due_date':'2030-12-02'})
                        assert reminder.ok,reminder.text()
                        page.goto(base+'/desk.html?project='+pid,wait_until='networkidle')
                        page.wait_for_function("document.getElementById('overview-scope').textContent.includes('当前项目')")
                        assert page.locator('#stat-preparing').inner_text()=='0'
                        assert '其他项目的任务' not in page.locator('#future-task-list').inner_text()
                        assert '准备成绩单' in page.locator('#future-task-list').inner_text()
                        page.screenshot(path=str(out/f'project-scope-{width}.png'))
                        assert not errors,errors
                        results.append({'width':width,'project_task_scope':True,'target_transfer':True,'all_three_bookmarks':True,'duplicate_safe':True,'graduation_not_entry':True,'todo_context_preserved':True,'draft_restored_after_navigation':True,'page_errors':errors})
                    finally:context.close();server.shutdown();server.server_close()
            public=serve_public.create_server(root,'127.0.0.1',0);threading.Thread(target=public.serve_forever,daemon=True).start()
            try:
                base=f'http://127.0.0.1:{public.server_port}';context=browser.new_context();page=context.new_page();writes=[]
                page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None)
                page.goto(base+'/start.html',wait_until='networkidle');page.locator('#target-form button[type=submit]').click();page.locator('[data-plan-convert]').click()
                assert '导出' in page.locator('#library-status').inner_text();assert not page.locator('#plan-transfer-dialog').is_visible();assert not writes
                results.append({'public_handoff_readonly':True,'public_writes':writes});context.close()
            finally:public.shutdown();public.server_close()
        finally:browser.close()
    assert signatures()==before,'Real private files changed'
    (out/'results.json').write_text(json.dumps({'passed':True,'cases':results,'private_files_unchanged':True},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False))


if __name__=='__main__':main()

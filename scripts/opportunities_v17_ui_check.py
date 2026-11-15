"""Isolated rolling/month opportunity UI and read-only production checks."""
import argparse
import copy
import json
import shutil
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_site import template_environment


def fixtures():
    base={'id':'rolling-fixture','kind':'research_program','title':'校内科研实践申请',
          'school_name':'示例大学','unit':'计算机学院','cycle':'current','source_state':'verified',
          'published_at':'2026-11-01','checked_at':'2026-11-15','verified_at':'2026-11-15',
          'registration_start':'2026-11-01','deadline':'','deadline_note':'具体截止未公布',
          'event_start':'','event_end':'','graduation_year':None,'camp_year':2026,'admission_year':None,
          'eligibility':['面向本科三年级学生','仅限本校在读学生，不能作为面向全国的招生公告'],
          'materials':['申请人本人完成研究陈述；不得使用AI代写'],
          'application_method':'填写官方申请表后按原文提交','application_url':'https://example.edu/apply',
          'contact':'项目办公室：office@example.edu','admission_note':'不保证获得录取或导师名额',
          'source_url':'https://example.edu/notice','source_note':'测试用官方资料快照','evidence':[],
          'application_window':{'mode':'rolling','end_month':'','quote':'本项目长期接受申请，请先联系确认余位'},
          'research_directions':[{'department':'智能系统组','direction':'人工智能与系统安全','contact':'张老师',
          'email':'teacher@example.edu','source_url':'https://example.edu/notice','source_locator':'方向表第1行','verified_at':'2026-11-15'}],
          'source_attachments':[{'url':'https://example.edu/application.docx','sha256':'a'*64,'checked_at':'2026-11-15',
          'field_evidence':{'materials':{'quote':'不得使用AI代写','locator':'申请表第2段'}}}]}
    month=copy.deepcopy(base);month.update(id='month-fixture',title='科研实习月度受理',application_window={'mode':'month','end_month':'2026-12','quote':'申请受理至2026年12月'})
    current=copy.deepcopy(month);current.update(id='current-month-fixture',title='截止当月需核对',application_window={'mode':'month','end_month':'2026-11','quote':'申请受理至2026年11月'})
    exact=copy.deepcopy(base);exact.update(id='exact-fixture',title='有明确截止的科研活动',deadline='2026-11-20');exact.pop('application_window')
    return {'version':1,'checked_at':'2026-11-15','coverage_note':'UI边界测试夹具，不是实际招生数据','mode':'local','opportunities':[base,month,current,exact]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--output',type=Path,default=ROOT/'cache/v17/opportunity-ui')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='opportunity-v17-') as directory:
        server=None
        try:
            if args.base:
                base=args.base.rstrip('/');catalog=None
            else:
                site=Path(directory);catalog=fixtures()
                for name in ('opportunities-core.js','opportunities.js','opportunity-push.js','browser-library-core.js','browser-library.js','ui.css'):
                    shutil.copyfile(ROOT/'site'/name,site/name)
                (site/'opportunities.html').write_text(template_environment().get_template('opportunities.html.j2').render(),encoding='utf-8')
                (site/'opportunities-data.js').write_text('window.OPPORTUNITIES='+json.dumps(catalog,ensure_ascii=False)+';',encoding='utf-8')
                server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(site)))
                threading.Thread(target=server.serve_forever,daemon=True).start()
                base=f'http://127.0.0.1:{server.server_port}'
            with sync_playwright() as pw:
                browser=pw.chromium.launch()
                try:
                    for width in (1440,390):
                        context=browser.new_context(viewport={'width':width,'height':950})
                        page=context.new_page();errors=[];writes=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        def readonly(route):
                            req=route.request
                            if req.method not in ('GET','HEAD','OPTIONS'):
                                writes.append(req.url);route.abort();return
                            if catalog and '/api/' in req.url:
                                path=req.url.split('/api/',1)[1]
                                value=catalog if path=='opportunities' else {'projects':{}} if path=='workflow' else {'enabled':False} if path=='push/config' else {'events':[]}
                                route.fulfill(json=value);return
                            route.continue_()
                        context.route('**/*',readonly)
                        if catalog:page.clock.set_fixed_time('2026-11-15T12:00:00+08:00')
                        page.goto(base+'/opportunities.html',wait_until='networkidle')
                        page.wait_for_function('opportunityModeReady')
                        if catalog:
                            assert '1 条明确日期且在报名时间内' in page.locator('#opportunity-count').inner_text()
                            assert '1 条受理期内但截止仅到月份' in page.locator('#opportunity-count').inner_text()
                            assert '1 条长期 / 滚动受理' in page.locator('#opportunity-count').inner_text()
                            for kind,expected in [('rolling','rolling-fixture'),('open_month','month-fixture'),('open','exact-fixture'),('unknown','current-month-fixture')]:
                                page.locator('#opportunity-state').select_option(kind)
                                assert page.locator('[data-opportunity]').count()==1
                                assert page.locator('[data-opportunity]').get_attribute('data-opportunity')==expected
                            page.locator('#opportunity-state').select_option('rolling')
                            card=page.locator('[data-opportunity="rolling-fixture"]')
                            assert '仅限本校' in card.locator('.opportunity-eligibility').inner_text()
                            assert '原文未明确毕业届别' in card.locator('.opportunity-cohort').inner_text()
                            assert card.locator('.research-direction').first.is_visible()
                            assert card.locator('a[href^="mailto:"]').first.is_visible()
                            assert card.locator('.opportunity-apply').is_visible()
                            assert card.locator('.opportunity-actions a[href$=".docx"]').is_visible()
                            card.locator('summary').filter(has_text='官方申请表与核验依据').click()
                            attachment=card.locator('details').filter(has=page.locator('summary',has_text='官方申请表与核验依据'))
                            assert '申请表第2段' in attachment.inner_text() and '不得使用AI代写' in attachment.inner_text()
                            assert '2026-11-15' in attachment.inner_text() and 'PDF' not in attachment.inner_text()
                            assert not page.get_by_role('button',name='AI代写').count()
                            card.evaluate('(el)=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY-110)')
                            page.screenshot(path=str(args.output/f'rolling-{width}.png'))
                            attachment.evaluate('(el)=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY-110)')
                            page.screenshot(path=str(args.output/f'attachment-{width}.png'))
                            for kind,id in [('rolling','rolling-fixture'),('open_month','month-fixture'),('open','exact-fixture')]:
                                page.locator('#opportunity-state').select_option(kind)
                                page.locator(f'[data-opportunity="{id}"] [data-save-opportunity]').click()
                                assert page.locator('#opportunity-reminder').get_attribute('max')==('2026-11-20' if kind=='open' else '')
                                if kind!='open':assert '个人' in page.locator('#opportunity-save-hint').inner_text()
                                page.locator('#opportunity-cancel').click()
                            page.locator('#opportunity-state').select_option('unknown')
                            assert '已到官方截止月份' in page.locator('[data-opportunity]').inner_text()
                        else:
                            actual=page.evaluate('opportunityRows.map(o=>({id:o.id,state:OpportunityRules.state(o),window:o.application_window,attachments:(o.source_attachments||[]).length}))')
                            for kind in ('rolling','open_month'):
                                expected=[o for o in actual if o['state']==kind]
                                if not expected:continue
                                page.locator('#opportunity-state').select_option(kind)
                                assert page.locator('[data-opportunity]').count()==len(expected)
                                card=page.locator('[data-opportunity]').first
                                assert card.locator('.opportunity-eligibility').is_visible()
                                assert '官方受理说明' in card.inner_text()
                                assert not card.locator('.opportunity-facts').get_by_text('具体日期待确认',exact=True).count()
                                card.evaluate('(el)=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY-110)')
                                page.screenshot(path=str(args.output/f'{kind}-{width}.png'))
                            results.append({'width':width,'actual_catalog':actual})
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        assert not errors and not writes,(errors,writes)
                        results.append({'width':width,'fixture':bool(catalog),'passed':True,'no_horizontal_overflow':True,'js_errors':errors,'non_read_requests':writes})
                        context.close()
                finally:browser.close()
        finally:
            if server:server.shutdown();server.server_close()
    (args.output/'results.json').write_text(json.dumps({'passed':True,'cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True))


if __name__=='__main__':main()

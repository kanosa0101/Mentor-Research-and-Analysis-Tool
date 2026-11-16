import copy
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright, expect

from scripts import build_site


@pytest.mark.parametrize('hang_api',[False,True])
def test_open_snapshot_downgrades_on_api_failure_and_recovers_without_anonymous_write(hang_api):
    root=build_site.ROOT
    html=build_site.template_environment().get_template('opportunities.html.j2').render()
    source=json.loads((root/'site/opportunities-data.js').read_text(encoding='utf-8').split('=',1)[1].strip().removesuffix(';'))
    row=copy.deepcopy(next(r for r in source['opportunities'] if r['content_classification']['scope']=='institutional_activity'))
    today=datetime.now(timezone(timedelta(hours=8))).date()
    row.update(cycle='current',registration_start=(today-timedelta(days=1)).isoformat(),deadline=(today+timedelta(days=10)).isoformat(),
               checked_at=today.isoformat(),verified_at=today.isoformat(),event_start='',event_end='',source_state='verified')
    catalog=dict(source,opportunities=[row],other_contents=[],mode='public')
    calls={'api':0,'snapshot':0};writes=[];errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        page=browser.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(request):
            path=urlsplit(request.request.url).path
            if request.request.method!='GET':
                writes.append(path);return request.abort()
            if path=='/opportunities.html':return request.fulfill(content_type='text/html; charset=utf-8',body=html)
            if path=='/api/opportunities':
                calls['api']+=1
                if hang_api and calls['api']==1:return
                return request.fulfill(status=503 if calls['api']==1 else 200,content_type='application/json',body=json.dumps(catalog))
            if path=='/opportunities-data.js':
                calls['snapshot']+=1
                return request.fulfill(content_type='text/javascript',body='window.OPPORTUNITIES='+json.dumps(catalog)+';')
            if path.startswith('/api/'):
                data={'authenticated':False,'user':None} if path=='/api/auth/me' else {'enabled':False,'events':[]}
                return request.fulfill(content_type='application/json',body=json.dumps(data))
            target=root/'site'/path.lstrip('/')
            assert target.resolve().is_relative_to(root/'site') and target.is_file()
            return request.fulfill(content_type='text/css' if target.suffix=='.css' else 'text/javascript',body=target.read_bytes())
        page.route('**/*',route)
        try:
            page.goto('http://mentor-test.invalid/opportunities.html')
            page.wait_for_function('catalogLoaded&&!document.getElementById("monitor-refresh").disabled')
            expect(page.locator('.opportunity-state')).to_have_text('待复核')
            expect(page.locator('[data-save-opportunity]')).to_be_disabled()
            expect(page.locator('#opportunity-count')).not_to_contain_text('报名窗口内')
            page.locator('#monitor-details > summary').click()
            page.locator('#monitor-refresh').click()
            page.wait_for_function('opportunityModeReady&&!document.getElementById("monitor-refresh").disabled')
            expect(page.locator('.opportunity-state')).to_have_text('明确日期 · 报名时间内')
            expect(page.locator('.opportunity-actions a').filter(has_text='登录后加入申请')).to_have_count(1)
            expect(page.locator('[data-save-opportunity]')).to_have_count(0)
            assert calls=={'api':2,'snapshot':1} and not writes and not errors
        finally:
            browser.close()


def test_hanging_static_fallback_releases_retry_control_and_can_recover():
    root=build_site.ROOT
    html=build_site.template_environment().get_template('opportunities.html.j2').render()
    calls=[];errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch();page=browser.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        def route(request):
            path=urlsplit(request.request.url).path
            assert request.request.method=='GET'
            if path=='/opportunities.html':return request.fulfill(content_type='text/html; charset=utf-8',body=html)
            if path=='/api/opportunities':
                calls.append(path)
                return request.fulfill(status=503 if len(calls)==1 else 200,content_type='application/json',body='{"mode":"public","opportunities":[],"other_contents":[]}')
            if path=='/opportunities-data.js':return  # Browser receives neither headers nor a load/error event.
            if path.startswith('/api/'):
                data={'authenticated':False,'user':None} if path=='/api/auth/me' else {'enabled':False,'events':[]}
                return request.fulfill(content_type='application/json',body=json.dumps(data))
            target=root/'site'/path.lstrip('/')
            assert target.resolve().is_relative_to(root/'site') and target.is_file()
            return request.fulfill(content_type='text/css' if target.suffix=='.css' else 'text/javascript',body=target.read_bytes())
        page.route('**/*',route)
        try:
            # A stalled async script keeps window.load pending; the UI must still
            # recover, so measure the user's usable DOM instead of that event.
            page.goto('http://mentor-test.invalid/opportunities.html',wait_until='domcontentloaded')
            page.wait_for_function('!document.getElementById("monitor-refresh").disabled',timeout=15000)
            expect(page.locator('#opportunity-count')).to_contain_text('暂时无法读取')
            page.locator('#monitor-details > summary').click();page.locator('#monitor-refresh').click()
            page.wait_for_function('opportunityModeReady&&!document.getElementById("monitor-refresh").disabled')
            assert len(calls)==2 and not errors
        finally:
            browser.close()


def test_requirement_clauses_preserve_every_restriction_and_escape_markup():
    # Execute the actual renderer in a browser DOM; splitting must not omit an
    # exception, alter numbers, or turn source text into executable markup.
    code=(build_site.ROOT/'site/admissions.js').read_text(encoding='utf-8')
    begin=code.index('function requirementPreview(')
    end=code.index('\nfunction checklistItem(',begin)
    renderer=code[begin:end]
    text='仅限本校本科生；英语六级不得低于425分。非全日制不接受；另需提交<script>window.injected=true</script>原文证明。'
    with sync_playwright() as pw:
        browser=pw.chromium.launch();page=browser.new_page()
        page.set_content('<main id="result"></main>')
        page.evaluate("window.esc=value=>String(value).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"+renderer)
        page.evaluate('text=>document.getElementById("result").innerHTML=requirementPreview(text)',text)
        assert ''.join(page.locator('#result li').all_text_contents())==text
        assert page.locator('#result script').count()==0
        assert page.evaluate('typeof window.injected')=='undefined'
        browser.close()

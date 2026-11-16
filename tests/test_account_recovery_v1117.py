"""Real-browser read recovery preserves inputs and never replays a failed write."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
from scripts import build_site

ROOT=Path(__file__).resolve().parents[1]
EMPTY=dict(version=1,targets=[],bookmarks=[],todos=[])


def page_html():
    def script(name):return '<script>'+(ROOT/'site'/name).read_text(encoding='utf8')+'</script>'
    return ('<!doctype html><html><head><meta charset="utf-8">'+script('account-session.js')+script('cloud-library.js')+
        '</head><body><main><a data-account-link>登录 / 注册</a><input id="draft"><div data-candidate="test"><h2><a href="p/test.html">测试导师</a></h2></div>'+
        '<button id="protected">保存申请</button><p id="result"></p></main>'+script('browser-library-core.js')+script('browser-library.js')+
        '<script>window.initialAccount=OnlineAccount.ready;window.initialLibrary=CloudLibrary.ready;document.getElementById("protected").onclick=async()=>{try{const r=await fetch("/api/workflow/projects",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:document.getElementById("draft").value})});document.getElementById("result").textContent=r.ok?"已保存":"保存未完成";}catch(e){document.getElementById("result").textContent=e.message;}};</script></body></html>')


@pytest.mark.parametrize('failure',['account_timeout','library_error'])
def test_same_page_read_recovery_allows_one_explicit_bookmark_and_protected_save(failure):
    calls=[];writes=[];errors=[];library=EMPTY.copy();revision=7
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-proxy-server']);page=browser.new_page()
        page.on('pageerror',lambda e:errors.append(str(e)))
        def route_request(route):
            nonlocal library,revision
            request=route.request;path=urlsplit(request.url).path;calls.append((path,request.method))
            if path=='/discovery.html':return route.fulfill(content_type='text/html;charset=utf-8',body=page_html())
            if path=='/api/auth/me':
                if failure=='account_timeout' and calls.count((path,'GET'))==1:return
                return route.fulfill(content_type='application/json',body=json.dumps(dict(authenticated=True,user={'id':'test','username':'测试'},csrf_token='recovered-csrf')))
            if path=='/api/library' and request.method=='GET':
                if failure=='library_error' and calls.count((path,'GET'))==1:return route.fulfill(status=503,content_type='application/json',body='{"error":"临时不可用"}')
                return route.fulfill(content_type='application/json',body=json.dumps(dict(library=library,revision=revision)))
            if request.method!='GET':
                writes.append(dict(path=path,csrf=request.headers.get('x-csrf-token'),body=request.post_data_json))
                if path=='/api/library':
                    assert request.post_data_json['revision']==revision
                    library=request.post_data_json['library'];revision+=1
                    return route.fulfill(content_type='application/json',body=json.dumps(dict(library=library,revision=revision)))
                return route.fulfill(content_type='application/json',body='{"ok":true}')
            return route.abort()
        page.route('**/*',route_request)
        try:
            page.goto('http://mentor-test.invalid/discovery.html',wait_until='domcontentloaded')
            page.locator('#draft').fill('保留我的未保存申请')
            selector='#account-connection-message' if failure=='account_timeout' else '#library-connection-message'
            page.locator(selector).wait_for(timeout=12000)
            page.locator('[data-browser-bookmark]').click()
            page.wait_for_function('document.querySelector(".browser-library-action span").textContent.includes("未保存")')
            assert writes==[]
            if failure=='account_timeout':
                page.locator('#protected').click()
                page.wait_for_function('document.getElementById("result").textContent.includes("超时")')
                assert writes==[]
            page.locator(selector+' button').click()
            page.wait_for_function('window.CloudLibrary && !document.getElementById("account-connection-message") && !document.getElementById("library-connection-message")')
            page.evaluate('CloudLibrary.ready')
            assert page.locator('#draft').input_value()=='保留我的未保存申请'
            assert page.evaluate('initialLibrary!==CloudLibrary.ready')
            if failure=='account_timeout':assert page.evaluate('initialAccount!==OnlineAccount.ready')
            assert writes==[]  # Read recovery itself never replays the failed save.
            page.locator('[data-browser-bookmark]').click()
            page.wait_for_function('document.querySelector("[data-browser-bookmark]").textContent==="已收藏"')
            page.locator('#protected').click();page.wait_for_function('document.getElementById("result").textContent==="已保存"')
            assert [row['path'] for row in writes]==['/api/library','/api/workflow/projects']
            assert all(row['csrf']=='recovered-csrf' for row in writes)
            assert writes[-1]['body']['name']=='保留我的未保存申请' and len(library['bookmarks'])==1
            assert errors==[]
        finally:browser.close()


@pytest.mark.parametrize('expire',[False,True])
def test_anonymous_and_expired_sessions_keep_login_behavior(expire):
    writes=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-proxy-server']);page=browser.new_page()
        def handle(route):
            request=route.request;path=urlsplit(request.url).path
            if path=='/discovery.html':return route.fulfill(content_type='text/html;charset=utf-8',body=page_html())
            if path=='/account.html':return route.fulfill(content_type='text/html;charset=utf-8',body='<h1>登录后继续</h1>')
            if path=='/api/auth/me':return route.fulfill(content_type='application/json',body=json.dumps(dict(authenticated=expire,user={'id':'test'} if expire else None,csrf_token='old-token' if expire else '')))
            if path=='/api/library':return route.fulfill(content_type='application/json',body=json.dumps(dict(library=EMPTY,revision=0)))
            if request.method!='GET':writes.append(path);return route.fulfill(status=401,content_type='application/json',body='{"error":"登录已失效"}')
            return route.abort()
        page.route('**/*',handle)
        try:
            page.goto('http://mentor-test.invalid/discovery.html');page.evaluate('CloudLibrary.ready')
            if expire:
                page.locator('#protected').click();page.locator('#account-expired-message').wait_for()
                assert not page.evaluate('OnlineAccount.state.authenticated')
                assert writes==['/api/workflow/projects']
            page.locator('[data-browser-bookmark]').click();page.wait_for_url('**/account.html?next=**')
            assert page.locator('h1').inner_text()=='登录后继续'
            assert writes==(['/api/workflow/projects'] if expire else [])
        finally:browser.close()


def test_real_start_initializers_resume_without_losing_target_draft():
    auth_reads=0;library=EMPTY.copy();revision=2;writes=[];errors=[]
    html=build_site.render_start_page()
    with sync_playwright() as pw:
        browser=pw.chromium.launch(args=['--no-proxy-server']);page=browser.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        def handle(route):
            nonlocal auth_reads,library,revision
            request=route.request;path=urlsplit(request.url).path
            if path=='/start.html':return route.fulfill(content_type='text/html;charset=utf-8',body=html)
            if path=='/api/auth/me':
                auth_reads+=1
                if auth_reads==1:return route.fulfill(status=503,content_type='application/json',body='{}')
                return route.fulfill(content_type='application/json',body=json.dumps(dict(authenticated=True,user={'id':'test'},csrf_token='new-session')))
            if path=='/api/library':
                if request.method=='PUT':
                    writes.append((path,request.headers.get('x-csrf-token')));library=request.post_data_json['library'];revision+=1
                return route.fulfill(content_type='application/json',body=json.dumps(dict(library=library,revision=revision)))
            if path=='/api/workflow':return route.fulfill(content_type='application/json',body='{"projects":{},"targets":{},"materials":{},"reminders":{}}')
            if path=='/api/workflow/browser-transfer':
                writes.append((path,request.headers.get('x-csrf-token')))
                return route.fulfill(content_type='application/json',body='{"project_id":"test-project","duplicate":false}')
            return route.abort()
        page.route('**/*',handle)
        try:
            page.goto('http://mentor-test.invalid/start.html')
            page.locator('#account-connection-message').wait_for()
            page.locator('#target-interest').fill('尚未保存的机器学习方向')
            page.locator('#account-connection-message button').click()
            page.wait_for_function('window.START_READY===true')
            assert page.locator('#target-interest').input_value()=='尚未保存的机器学习方向'
            assert writes==[]
            page.locator('#target-form button[type=submit]').click()
            page.locator('[data-plan-convert]').wait_for()
            assert page.locator('[data-plan-convert]').first.inner_text()=='建立申请项目'
            page.locator('[data-plan-convert]').first.click()
            page.locator('#plan-confirm').click()
            page.wait_for_function('document.getElementById("plan-status").textContent.includes("已建立申请项目")')
            assert writes==[('/api/library','new-session'),('/api/workflow/browser-transfer','new-session')]
            assert errors==[]
        finally:browser.close()

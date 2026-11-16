"""Verify a deployed online site with two explicitly identifiable QA accounts.

Credentials exist only in memory. The report records account IDs so an operator
can remove precisely these synthetic accounts after the check.
"""
import argparse
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    if not base.startswith('https://'):
        raise ValueError('Deployment verification requires HTTPS')
    args.output.mkdir(parents=True, exist_ok=True)
    result = {'base_url': base, 'accounts': [], 'checks': [], 'passed': False}
    name = 'qa_v1116_' + str(int(time.time()))
    result['planned_usernames'] = [name + '_a', name + '_b']
    password = secrets.token_urlsafe(24)

    def api(page, path, method='GET', body=None):
        return page.evaluate('''async ({path,method,body})=>{
            const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},
                ...(body===null?{}:{body:JSON.stringify(body)})});
            const text=await r.text();let data;try{data=JSON.parse(text)}catch{data=text}
            return {status:r.status,data};
        }''', {'path': path, 'method': method, 'body': body})

    def sign_in(page, username, register=False, current_page=False):
        if not current_page:
            page.goto(base + '/account.html?next=/applications.html', wait_until='networkidle')
        if register:
            page.locator('[data-account-mode=register]').click()
        page.locator('#account-username').fill(username)
        page.locator('#account-password').fill(password)
        if register:
            page.locator('#account-confirm').fill(password)
        page.locator('#account-submit').click()
        destination = '/desk.html' if current_page else '/applications.html'
        page.wait_for_url(lambda url: urlsplit(url).path == destination)
        state = api(page, '/api/auth/me')['data']
        if register:
            if state['user'] not in result['accounts']:
                result['accounts'].append(state['user'])
            save()
        page.wait_for_function('window.CONTACT_READY' if current_page else 'window.WORKFLOW_READY')
        return state

    def save():
        (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    save()
    try:
        with sync_playwright() as pw:
            # Verify the public endpoint directly, without workstation system proxies.
            browser = pw.chromium.launch(args=['--no-proxy-server'])
            contexts = [browser.new_context(viewport={'width': width, 'height': 960}) for width in (1440, 390, 390)]
            errors = []
            result['browser_errors'] = errors
            result['failed_requests'] = []
            result['core_asset_responses'] = []
            pages = [context.new_page() for context in contexts]
            for page in pages:
                page.on('pageerror', lambda error: errors.append(str(error.stack)))
                page.on('requestfailed', lambda request: result['failed_requests'].append({'url': request.url, 'error': request.failure}))
                page.on('response', lambda response: result['core_asset_responses'].append({'url': response.url, 'status': response.status}) if '/browser-library-core.js' in response.url else None)
            a, same, other = pages
            a.goto(base + '/discovery.html?school=ruc', wait_until='networkidle')
            a.wait_for_function('window.DISCOVERY_READY')
            card = a.locator('[data-candidate]').first
            mentor = card.get_attribute('data-candidate')
            mentor_name = card.locator('h2').inner_text()
            card.locator('a[href^="desk.html"]').click()
            a.wait_for_url(lambda url: urlsplit(url).path == '/account.html')
            sign_in(a, name + '_a', register=True, current_page=True)
            assert a.evaluate('incomingMentor') == mentor
            cookies = contexts[0].cookies()
            cookie = next(c for c in cookies if c['name'] == 'mentor_session')
            assert cookie['secure'] and cookie['httpOnly'] and cookie['sameSite'] == 'Lax'
            result['checks'].append('https_registration_secure_cookie')
            a.locator('#prepare-empty a').click()
            a.wait_for_function('window.WORKFLOW_READY')
            assert a.locator('nav[aria-label="主导航"] a[aria-current="page"]').inner_text() == '我的申请'
            a.locator('#project-name').fill('部署验收项目')
            a.locator('#project-save').click()
            a.wait_for_function('Object.keys(WORKFLOW.projects).length===1')
            project_id = a.evaluate('Object.keys(WORKFLOW.projects)[0]')
            assert mentor in a.evaluate('Object.values(WORKFLOW.projects)[0].mentor_ids')
            assert a.locator('#filter-project').input_value() == project_id
            a.locator('#project-next [data-section=material]').click()
            assert a.locator('#material-projects').evaluate('(node)=>[...node.selectedOptions].map(o=>o.value)') == [project_id]
            a.locator('#material-file').set_input_files({'name': 'deployment-check.txt', 'mimeType': 'text/plain', 'buffer': b'online-account-material-check'})
            a.locator('#material-save').click()
            a.wait_for_function('Object.keys(WORKFLOW.materials).length===1')
            material_id = a.evaluate('Object.keys(WORKFLOW.materials)[0]')
            a.screenshot(path=str(args.output / 'materials-desktop.png'), full_page=True)
            a.locator('.section-tabs [data-section=communication]').click()
            assert a.locator('#communication-project').input_value() == project_id
            assert a.evaluate('chosen.communication') == [mentor]
            a.locator('#communication-kind').select_option('replied')
            a.locator('#communication-subject').fill('部署验收')
            a.locator('#communication-content').fill('部署验收沟通记录')
            a.locator('#communication-materials').select_option(material_id)
            a.locator('#communication-save').click()
            a.wait_for_function('Object.keys(WORKFLOW.communications).length===1')
            a.screenshot(path=str(args.output / 'communication-desktop.png'), full_page=True)
            result['checks'].append('create_project_upload_and_record_communication_without_reselecting_project_or_mentor')
            a.locator('#back-desk').click()
            a.wait_for_function('window.CONTACT_READY')
            a.locator('.tabs [data-view=targets]').click()
            a.locator('#target-project').select_option(project_id)
            a.locator('#target-reason').fill('部署验收：保留所选导师和申请项目')
            a.locator('#target-save').click()
            a.wait_for_function('Object.keys(FLOW.targets).length===1')
            assert mentor_name in a.locator('#context-name').inner_text()
            result['checks'].append('discovery_registration_project_creation_and_target_use_ui_and_preserve_context')
            reminder = api(a, '/api/workflow/reminders', 'POST', {'title': '验收提醒', 'project_id': project_id, 'due_date': time.strftime('%Y-%m-%d')})
            assert reminder['status'] == 200, reminder
            a.goto(base + '/start.html', wait_until='networkidle')
            a.wait_for_function('window.START_READY')
            a.locator('#target-interest').fill('部署验收研究目标')
            a.locator('#target-form button[type=submit]').click()
            a.wait_for_function('CloudLibrary.read().targets.length===1')
            result['checks'].append('project_material_communication_reminder_and_target_saved')
            sign_in(same, name + '_a')
            data = api(same, '/api/workflow')['data']
            assert project_id in data['projects'] and material_id in data['materials']
            assert len(data['communications']) == 1 and len(data['reminders']) == 1
            assert api(same, '/api/materials/' + material_id + '/download') == {'status': 200, 'data': 'online-account-material-check'}
            assert len(api(same, '/api/library')['data']['library']['targets']) == 1
            result['checks'].append('independent_mobile_browser_same_account_reads_same_records_and_file')
            sign_in(other, name + '_b', register=True)
            assert not api(other, '/api/workflow')['data']['projects']
            assert api(other, '/api/materials/' + material_id + '/download')['status'] == 404
            assert api(other, '/api/workflow/projects/' + project_id, 'PATCH', {'name': 'forbidden'})['status'] != 200
            result['checks'].append('other_account_cannot_read_or_modify_records')
            assert api(other, '/api/auth/logout', 'POST', {})['status'] == 200
            assert contexts[2].request.get(base + '/api/workflow').status == 401
            result['checks'].append('logout_revokes_private_access')
            anonymous = browser.new_context()
            response = anonymous.request.get(base + '/download/mentor-assistant-v1.10.0-local.zip')
            assert response.status == 410
            for path in ('/api/public-data', '/api/public-data/check', '/api/public-data/archive/' + 'a' * 64, '/public-data.js'):
                assert anonymous.request.get(base + path).status == 410, path
            assert anonymous.request.get(base + '/api/workflow').status == 401
            for path in ('/review.html', '/api/review', '/var/accounts/accounts.sqlite3', '/data/workflow.yaml'):
                assert anonymous.request.get(base + path).status == 404, path
            legacy = anonymous.request.get(base + '/local.html?id=legacy-id')
            assert '/opportunities.html?id=legacy-id' in legacy.url
            result['checks'].append('local_download_retired_and_private_maintenance_files_hidden')
            same.goto(base + '/account.html', wait_until='networkidle')
            assert same.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            same.screenshot(path=str(args.output / 'account-mobile.png'))
            assert not errors, errors
            result['checks'].append('no_browser_errors_or_account_horizontal_overflow')
            public = anonymous.new_page()
            public.on('pageerror', lambda error: errors.append(str(error)))
            public.goto(base + '/opportunities.html?year=2028', wait_until='networkidle')
            public.wait_for_function('opportunityModeReady')
            public.locator('#opportunity-year').select_option('2028')
            assert public.evaluate('''[...document.querySelectorAll('[data-opportunity]')].every(node=>
                opportunityRows.find(row=>row.id===node.dataset.opportunity)?.graduation_year===2028)''')
            if not public.locator('[data-opportunity]').count():
                assert '明确面向 2028 届' in public.locator('.opportunity-empty').inner_text()
                public.locator('#opportunity-unknown-year').click()
            else:
                public.locator('#opportunity-year').select_option('unknown')
            assert public.locator('[data-opportunity]').count() >= 1
            public.screenshot(path=str(args.output / 'opportunities-public.png'), full_page=True)
            result['checks'].append('explicit_cohort_excludes_unknown_and_retains_unknown_activity_access')
            public.goto(base + '/admissions.html?school=bit&dept=cs&year=2027&degree=master&route=recommend&track=ordinary', wait_until='networkidle')
            public.wait_for_function('window.ADMISSIONS_READY')
            assert public.locator('.policy-cycle').count() > 0
            assert all('历史参考' in text for text in public.locator('.policy-cycle').all_text_contents())
            public.locator('#policy-year').fill('2028')
            public.locator('#policy-year').dispatch_event('change')
            assert '不表示学校尚未发布' in public.locator('#policy-list').inner_text()
            result['checks'].append('historical_recommendation_policy_and_current_cohort_gap_are_explicit')
            public.set_viewport_size({'width': 390, 'height': 844})
            for path in ('opportunities.html', 'admissions.html', 'notices.html'):
                public.goto(base + '/' + path, wait_until='networkidle')
                assert public.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), path
            assert not errors, errors
            result['checks'].append('public_content_pages_fit_mobile_without_script_errors')
            result['passed'] = True
            browser.close()
    finally:
        save()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

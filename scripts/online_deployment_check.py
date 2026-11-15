"""Verify a deployed online site with two explicitly identifiable QA accounts.

Credentials exist only in memory. The report records account IDs so an operator
can remove precisely these synthetic accounts after the check.
"""
import argparse
import json
import secrets
import time
from pathlib import Path

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
    name = 'qa_v111_' + str(int(time.time()))
    result['planned_usernames'] = [name + '_a', name + '_b']
    password = secrets.token_urlsafe(24)

    def api(page, path, method='GET', body=None):
        return page.evaluate('''async ({path,method,body})=>{
            const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},
                ...(body===null?{}:{body:JSON.stringify(body)})});
            const text=await r.text();let data;try{data=JSON.parse(text)}catch{data=text}
            return {status:r.status,data};
        }''', {'path': path, 'method': method, 'body': body})

    def sign_in(page, username, register=False):
        page.goto(base + '/account.html?next=/applications.html', wait_until='networkidle')
        if register:
            page.locator('[data-account-mode=register]').click()
        page.locator('#account-username').fill(username)
        page.locator('#account-password').fill(password)
        if register:
            page.locator('#account-confirm').fill(password)
        page.locator('#account-submit').click()
        page.wait_for_url(lambda url: url.split('?')[0].endswith('/applications.html'))
        state = api(page, '/api/auth/me')['data']
        if register:
            result['accounts'].append(state['user'])
            save()
        page.wait_for_function('window.WORKFLOW_READY')
        return state

    def save():
        (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            contexts = [browser.new_context(viewport={'width': width, 'height': 960}) for width in (1440, 390, 390)]
            errors = []
            result['browser_errors'] = errors
            pages = [context.new_page() for context in contexts]
            for page in pages:
                page.on('pageerror', lambda error: errors.append(str(error)))
            a, same, other = pages
            sign_in(a, name + '_a', register=True)
            cookies = contexts[0].cookies()
            cookie = next(c for c in cookies if c['name'] == 'mentor_session')
            assert cookie['secure'] and cookie['httpOnly'] and cookie['sameSite'] == 'Lax'
            result['checks'].append('https_registration_secure_cookie')
            project = api(a, '/api/workflow/projects', 'POST', {'name': '部署验收项目', 'notes': 'Synthetic QA only', 'mentor_ids': ['ruc-info-dongjinhao']})
            assert project['status'] == 200, project
            project_id = project['data']['id']
            reminder = api(a, '/api/workflow/reminders', 'POST', {'title': '验收提醒', 'project_id': project_id, 'due_date': time.strftime('%Y-%m-%d')})
            assert reminder['status'] == 200, reminder
            a.goto(base + '/applications.html?section=material', wait_until='networkidle')
            a.wait_for_function('window.WORKFLOW_READY')
            a.locator('#material-file').set_input_files({'name': 'deployment-check.txt', 'mimeType': 'text/plain', 'buffer': b'online-account-material-check'})
            a.locator('#material-projects').select_option(project_id)
            a.locator('#material-save').click()
            a.wait_for_function('Object.keys(WORKFLOW.materials).length===1')
            material_id = a.evaluate('Object.keys(WORKFLOW.materials)[0]')
            communication = api(a, '/api/workflow/communications', 'POST', {'project_id': project_id, 'mentor_id': 'ruc-info-dongjinhao',
                'kind': 'note', 'date': time.strftime('%Y-%m-%d'), 'subject': '部署验收', 'content': '部署验收沟通记录', 'material_ids': [material_id]})
            assert communication['status'] == 200, communication
            a.evaluate('scrollTo(0,0)')
            a.screenshot(path=str(args.output / 'materials-desktop.png'))
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
            assert api(other, '/api/workflow')['status'] == 401
            result['checks'].append('logout_revokes_private_access')
            anonymous = browser.new_context()
            response = anonymous.request.get(base + '/download/mentor-assistant-v1.10.0-local.zip')
            assert response.status == 410
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
            result['passed'] = True
            browser.close()
    finally:
        save()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()

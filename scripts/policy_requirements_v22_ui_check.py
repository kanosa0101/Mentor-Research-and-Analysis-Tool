"""Real built-policy UI/API checks; every private write is temporary."""
import hashlib
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server

OUT = ROOT / 'cache/v19/policy_requirements'
SDU = ['sdu-cs-081200-2027-exam-v22', 'sdu-cs-085404-2027-exam-v22']
THU = 'tsinghua-2027-phd-assessment-v16pilot'
ZJU = 'zju-2027-phd-assessment-v16pilot'
AUTO = 'tsinghua-auto-2027-phd-assessment-v22'


def private_signatures():
    paths = [ROOT / 'data' / name for name in ['outreach.yaml', 'student.yaml', 'student_sop.md',
             'workflow.yaml', 'workflow.json', 'discovery.yaml', 'backup.json']]
    for name in ['letters', 'backups']:
        directory = ROOT / 'data' / name
        paths.extend(sorted(p for p in directory.rglob('*') if p.is_file()))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in paths}


def goal(policy, dept='cs'):
    return dict(school_id=policy['school'], dept_id=policy['dept'] or dept, year=policy['year'],
                degree=policy['degree'], route=policy['route'], track='ordinary',
                program_code=policy['program_code'], program_name=policy['program'])


def query(policy):
    g = goal(policy)
    result = dict(school=g['school_id'], dept=g['dept_id'], year=g['year'], degree=g['degree'],
                  route=g['route'], track=g['track'])
    if g['program_name']:
        result['program'] = g['program_code'] + '|' + g['program_name']
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    public = json.loads((ROOT / 'site/admissions-data.js').read_text(encoding='utf-8-sig').split('=', 1)[1].strip().rstrip(';'))
    policies = {p['id']: p for p in public['policies']}
    before = private_signatures()
    results = dict(ui=[], saves=[], api_rejections=[], browser_errors=[], external_requests=[],
                   all_writes_temporary=True, automatic_school_submissions=0, reminders_created=0)
    assert set(SDU + [THU, ZJU, AUTO]) <= policies.keys(), 'Build the v22 target policies before running'
    assert public['sources']['sdu_cs_directory_post_v22']['json_content'] == 'structured'
    assert all(policies[pid]['level'] == 'program' for pid in SDU)
    with tempfile.TemporaryDirectory(prefix='policy-v22-') as temp:
        root = Path(temp)
        site = root / 'site'
        site.mkdir()
        for name in ['applications.html', 'admissions.html', 'workflow.js', 'material-actions.js', 'data.js',
                     'admissions-data.js', 'admissions-core.js', 'admissions.js', 'ui.css']:
            shutil.copyfile(ROOT / 'site' / name, site / name)
        server = create_server(site=site, outreach=root / 'private/outreach.yaml',
                               workflow=root / 'private/workflow.json', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'

        def api(path='', body=None, expect=200):
            request = Request(base + '/api/workflow' + path,
                              data=None if body is None else json.dumps(body).encode(),
                              headers={'Content-Type': 'application/json', 'Origin': base})
            try:
                with urlopen(request) as response:
                    code, value = response.status, json.load(response)
            except HTTPError as error:
                code, value = error.code, json.load(error)
            assert code == expect, (path, code, value)
            return value

        def save_project(page, policy, width):
            count = len(api()['projects'])
            page.click('#checklist-project')
            page.wait_for_function('window.WORKFLOW_READY')
            page.wait_for_load_state('networkidle')
            assert len(api()['projects']) == count, 'Public prefill must not autosave'
            g = goal(policy)
            for field in ['school_id', 'dept_id', 'program_code', 'program_name']:
                assert page.input_value('#project-' + field.replace('_', '-')) == g[field]
            name = f'临时v22-{policy["id"]}-{width}'
            page.fill('#project-name', name)
            page.click('#project-save')
            page.wait_for_function('!document.querySelector("#project-name").value')
            created = next(p for p in api()['projects'].values() if p['name'] == name)
            assert all(created[k] == v for k, v in g.items())
            page.goto(base + '/applications.html?section=preparation&project=' + created['id'])
            page.wait_for_function('window.WORKFLOW_READY')
            page.wait_for_load_state('networkidle')
            page.wait_for_selector('#preparation-list a')
            link = page.locator('#preparation-list a').filter(has_text='核对本项目政策与材料要求')
            assert parse_qs(urlsplit(link.get_attribute('href')).query) == {k: [str(v)] for k, v in query(policy).items()}
            return created['id']

        def show_policy(page, policy):
            page.goto(base + '/admissions.html?' + urlencode(query(policy)))
            page.wait_for_function('window.ADMISSIONS_READY')
            page.wait_for_load_state('networkidle')
            card = page.locator('#policy-' + policy['id'])
            card.wait_for()
            assert policy['reviewed_at'] in card.locator('.policy-age').first.inner_text()
            card.locator('.policy-body > summary').click()
            # Read the disclosed original quotations and dates before asserting their facts.
            for detail in card.locator('.policy-body details').all():
                if detail.get_attribute('open') is None:
                    detail.locator(':scope > summary').click()
            source = public['sources'][policy['source_id']]['url']
            assert card.locator('a').filter(has_text='核对完整政策').get_attribute('href') == source
            assert card.locator('a').filter(has_text='核对完整政策').is_visible()
            return card

        def preparation_form(page, pid, policy_id, action_id):
            rows = api('/material-tasks')['actions'][pid]
            index, row = next((i, r) for i, r in enumerate(rows)
                              if r['policy_id'] == policy_id and r['action_id'] == action_id)
            form = page.locator(f'[data-material-action="{index}"]')
            detail = form.locator('xpath=..')
            if detail.get_attribute('open') is None:
                detail.locator(':scope > summary').click()
            evidence = detail.locator(':scope > details').first
            if evidence.get_attribute('open') is None:
                evidence.locator(':scope > summary').click()
            assert ''.join(row['action']['instruction']['quote'].split()) in ''.join(detail.inner_text().split())
            source_urls = {public['sources'][sid]['url'] for sid in row['action']['instruction'].get('source_ids', [policies[policy_id]['source_id']])}
            visible_urls = {link.get_attribute('href') for link in detail.locator('a[href]').all() if link.is_visible()}
            assert source_urls <= visible_urls
            assert '摘要核对' in detail.locator('xpath=..').inner_text()
            return row, form

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.on('pageerror', lambda error: results['browser_errors'].append(str(error)))
                page.on('request', lambda request: results['external_requests'].append(request.url)
                        if urlsplit(request.url).hostname not in ['127.0.0.1', None] else None)
                for width, height in [(1440, 1000), (390, 844)]:
                    page.set_viewport_size(dict(width=width, height=height))
                    for policy_id in SDU:
                        p = policies[policy_id]
                        card = show_policy(page, p)
                        key = p['program_code'] + '|' + p['program']
                        assert page.input_value('#policy-program') == key
                        other = SDU[1] if policy_id == SDU[0] else SDU[0]
                        assert page.locator('#policy-' + other).count() == 0
                        assert '不招收同等学力' in card.inner_text()
                        assert ''.join(p['fields']['exams']['quote'].split()) in ''.join(card.inner_text().split()), repr(card.inner_text())
                        assert policies[other]['fields']['exams']['quote'] not in page.locator('#application-checklist').inner_text()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(OUT / f'{policy_id}-{width}-public.png'), full_page=True)
                        pid = save_project(page, p, width)
                        assert not api('/material-tasks')['actions'][pid]
                        page.locator('#preparation-list a').filter(has_text='核对本项目政策与材料要求').click()
                        page.wait_for_function('window.ADMISSIONS_READY')
                        assert page.input_value('#policy-program') == key
                        assert page.locator('#policy-' + other).count() == 0
                        results['ui'].append(dict(policy_id=policy_id, width=width, formal_program=True,
                                                   source_visible=True, explicit_project_save=True, scope_return=True))
                    for policy_id, action_id in [(THU, 'online-two-expert-references'),
                                                 (ZJU, 'overseas-awarded-verification'), (AUTO, None)]:
                        p = policies[policy_id]
                        card = show_policy(page, p)
                        if policy_id == AUTO:
                            assert '2026-07-28' in card.inner_text()
                            assert '已登记事项截止已过' in card.inner_text() and '该事项已截止' in card.inner_text()
                            assert '已截止' in p['title'] and '冬季' in card.inner_text()
                        assert len(p.get('material_actions', [])) > 0
                        page.screenshot(path=str(OUT / f'{policy_id}-{width}-public.png'), full_page=True)
                        pid = save_project(page, p, width)
                        rows = api('/material-tasks')['actions'][pid]
                        own = [r for r in rows if r['policy_id'] == policy_id]
                        assert len(own) == len(p['material_actions']) and all(r['can_record'] for r in own)
                        if action_id:
                            row, form = preparation_form(page, pid, policy_id, action_id)
                            assert not row['events'], 'Do not create dates/reminders for unbound actions'
                            count = len(api('/material-tasks')['records'])
                            if row['conditions']:
                                assert not form.locator('[name="confirmed_conditions"]').is_checked()
                                body = dict(project_id=pid, expected_goal=row['goal_snapshot'], policy_id=policy_id,
                                            action_id=action_id, expected_action=row['action_fingerprint'], status='prepared',
                                            material_ids=[], notes='临时拒绝验证', confirmed_conditions=False)
                                api('/material-tasks', body, expect=400)
                                assert len(api('/material-tasks')['records']) == count
                                results['api_rejections'].append(dict(policy_id=policy_id, width=width, unchecked_rejected=True))
                                form.locator('[name="confirmed_conditions"]').check()
                            else:
                                assert form.locator('[name="confirmed_conditions"]').count() == 0
                            form.locator('[name="status"]').select_option('prepared')
                            form.locator('[name="notes"]').fill('临时验收人工已准备；没有向学校提交或报名')
                            form.locator('[type="submit"]').click()
                            page.wait_for_function('document.querySelector("#preparation-feedback").textContent.includes("已保存")')
                            records = [r for r in api('/material-tasks')['records'].values() if r['project_id'] == pid]
                            assert len(records) == 1 and records[0]['status'] == 'prepared'
                            assert records[0]['confirmed_conditions'] == bool(row['conditions'])
                            results['saves'].append(dict(policy_id=policy_id, action_id=action_id, width=width,
                                                        explicit_prepared=True, conditional=bool(row['conditions'])))
                            preparation_form(page, pid, policy_id, action_id)
                        page.screenshot(path=str(OUT / f'{policy_id}-{width}-preparation.png'), full_page=True)
                        results['ui'].append(dict(policy_id=policy_id, width=width, own_actions_readable=len(own),
                                                   historical_expiry_checked=policy_id == AUTO))
                assert not results['browser_errors'] and not results['external_requests']
                assert not api()['reminders']
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
    assert private_signatures() == before, 'Real private files changed'
    results.update(passed=True, public_counts=dict(policies=len(policies), sources=len(public['sources']), material_actions=sum(len(p.get('material_actions', [])) for p in policies.values())),
                   private_signatures_unchanged=True, protected_signatures=before,
                   scope='Five real targets at1440/390; two formal SDU programs; school PhD reference/conditional saves; historical auto expiry. No school submissions or new reminders.')
    (OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    print('PASS v22 real policy requirements flows')


if __name__ == '__main__':
    main()

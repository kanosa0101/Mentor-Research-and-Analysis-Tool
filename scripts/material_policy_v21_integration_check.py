"""Built v21 policy flows; private API writes use an isolated temporary directory."""
import hashlib
import json
import shutil
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server

OUT = ROOT / 'cache/policy_v21/integration/live_flow'
CONDITIONAL = [('fudan_2027_master_exam_v15a', 'equivalent-course-record'),
               ('pku-2027-master-exam-v14', '1101-current-postgraduate-consent'),
               ('hnu-2027-master-exam-v15c', 'current-graduate-consent'),
               ('sysu-cs-2027-085410-exam-v15c', 'parttime-directed-contract')]
UI = ['fudan_2027_master_exam_v15a', 'zju_2027_master_exam_v15a',
      'nudt-2027-master-exam-v15extra', 'ucas-ict-2027-master-charter-v21',
      'ucas-ia-2027-master-charter-v21']

# Frozen v21 additions; runtime resolves full actions from built public data.
ADDED_ACTION_IDS = {
    "fudan_2027_master_exam_v15a": [
        "equivalent-course-record",
        "registration-truthful-materials",
        "point3102-past-location-proof",
        "current-interview-originals",
        "past-interview-credentials",
        "equivalent-interview-record",
        "postgraduate-interview-consent",
        "soldier-interview-proof",
        "directed-contract",
        "current-entry-certificate"
    ],
    "zju_2027_master_exam_v15a": [
        "equivalent-email-precheck",
        "soldier-email-proof",
        "postgraduate-email-consent",
        "interview-credential-review",
        "admission-personnel-political-documents",
        "directed-agreement",
        "point3312-location-proof",
        "point3312-failed-qualification",
        "point3312-identity-change",
        "point3312-second-bachelor",
        "point3312-correction"
    ],
    "nju_2027_master_exam_v15a": [
        "postgraduate-ems-consent",
        "equivalent-academic-proof",
        "interview-original-materials",
        "soldier-recheck-proof",
        "directed-contract",
        "non-directed-file"
    ],
    "tongji_2027_master_exam_v15a": [
        "postgraduate-consent",
        "point-verification-materials",
        "failed-academic-report",
        "interview-originals",
        "soldier-recheck",
        "non-directed-transfer",
        "directed-contract"
    ],
    "ecnu_2027_master_exam_v15a": [
        "registration-integrity-materials",
        "equivalent-interview-transcript",
        "current-entry-qualification"
    ],
    "shanghaitech_2027_master_exam_v15a": [
        "postgraduate-written-consent",
        "equivalent-course-proof",
        "interview-originals",
        "current-enrollment-originals",
        "delayed-enrollment-leave",
        "point3126-student-status",
        "point3126-past-location",
        "point3126-corrections"
    ],
    "sjtu-2027-master-exam-v14": [
        "equivalent-preapproval",
        "postgraduate-consent",
        "military-consent",
        "interview-certification-and-copies",
        "soldier-interview-evidence",
        "bonus-written-application",
        "parttime-directed-contract",
        "political-form-and-personnel-file"
    ],
    "seu-2027-master-exam": [
        "equivalent-study-english-paper",
        "registration-integrity-supplements",
        "soldier-proof-before-retest",
        "directed-contract",
        "entry-qualification"
    ],
    "ustc-2027-master-exam-v14": [
        "point-registration-materials",
        "current-failed-status-report",
        "past-failed-qualification-report",
        "interview-integrity-undertaking",
        "directed-agreement"
    ],
    "pku-2027-master-exam-v14": [
        "upload-point-materials-photo-payment",
        "supplement-point-rejected-materials",
        "enrollment-original-identity-degree",
        "directed-agreement-before-admission",
        "1101-failed-id-upload",
        "1101-fresh-academic-report",
        "1101-current-postgraduate-consent"
    ],
    "ucas-2027-master-exam-v14": [
        "online-point-materials",
        "questioned-academic-proof-retest",
        "fresh-degree-original-at-enrollment",
        "part-time-directed-agreement"
    ],
    "bnu_2027_master_exam_v15a": [
        "point-material-correction",
        "problematic-academic-proof-retest",
        "non-directed-transfer-personnel-file",
        "directed-contracts-before-admission"
    ],
    "hit-school-2027-exam-v15b": [
        "equivalent-transcript-paper-retest",
        "qualification-original-documents",
        "directed-employment-agreement"
    ],
    "hit-webreg-2027-exam-v15b": [
        "2301-upload-local-verification",
        "2301-supplement-materials"
    ],
    "jlu-school-2027-exam-v15b": [
        "failed-academic-email-report",
        "supplement-point-materials",
        "questioned-academic-proof",
        "non-directed-file-review",
        "directed-contract-before-admission",
        "enrollment-admission-degree-originals",
        "fresh-enrollment-certification"
    ],
    "xjtu-webreg-pdf-2027-exam-v15b": [
        "failed-academic-report-by-registration-close",
        "equivalent-application-documents",
        "retest-basic-qualification-package",
        "foreign-degree-proof-retest",
        "political-review-sealed-unit-material",
        "directed-employment-agreement"
    ],
    "nudt-2027-master-exam-v15extra": [
        "civilian-fresh-academic-proof",
        "civilian-work-consent-at-retest",
        "civilian-directed-tripartite-agreement",
        "registration-photo-payment-materials"
    ],
    "ruc_2027_master_exam_v15a": [
        "point-upload-photo-fee",
        "point-supplement-required-materials",
        "equivalent-retest-paper",
        "retest-notice-and-proof",
        "admission-sealed-political-review",
        "directed-contract-before-admission",
        "fresh-graduation-original-before-enrollment"
    ],
    "csu-2027-master-exam": [
        "integrity-and-supplement",
        "print-exam-ticket",
        "non-directed-archive"
    ],
    "hnu-2027-master-exam-v15c": [
        "online-registration-materials",
        "current-graduate-consent",
        "equivalency-proof",
        "review-supplement",
        "print-exam-ticket",
        "interview-qualification-originals",
        "directed-contract",
        "non-directed-archive"
    ],
    "xmu-2027-master-exam-v15c": [
        "integrity-and-supplement",
        "equivalency-course-and-english-proof",
        "interview-originals",
        "print-exam-ticket",
        "directed-contract",
        "failed-verification-email"
    ],
    "cqu-2027-master-exam-v15c": [
        "registration-image-materials",
        "review-supplement",
        "print-exam-ticket",
        "interview-originals",
        "questioned-education-report"
    ],
    "scu-2027-master-exam-v15c": [
        "online-registration-materials",
        "review-supplement",
        "current-graduate-consent",
        "noncurrent-sichuan-domicile-or-work",
        "conditional-special-scans",
        "print-exam-ticket",
        "equivalency-early-email",
        "equivalency-interview-originals",
        "non-directed-archive",
        "directed-contract",
        "enrollment-originals"
    ],
    "hust-2027-master-exam": [
        "registration-integrity-supplement",
        "questioned-education-report",
        "hust4202-report-number",
        "print-exam-ticket",
        "changed-directed-employment-proof",
        "stamped-political-record"
    ],
    "whu-2027-master-exam": [
        "registration-materials",
        "current-graduate-consent",
        "review-supplement",
        "failed-education-authentication",
        "print-exam-ticket"
    ],
    "sysu-2027-master-exam-v15c": [
        "equivalency-course-proof",
        "integrity-and-supplement",
        "print-exam-ticket",
        "interview-qualification-originals",
        "overseas-education-authentication",
        "stamped-political-record",
        "directed-contract",
        "non-directed-archive"
    ],
    "sysu-cs-2027-085410-exam-v15c": [
        "parttime-directed-contract"
    ]
}
SOUTH_EVENT_ACTIONS = [('hnu-2027-master-exam-v15c', 'online-registration-materials'), ('cqu-2027-master-exam-v15c', 'registration-image-materials'), ('scu-2027-master-exam-v15c', 'online-registration-materials'), ('whu-2027-master-exam', 'registration-materials')]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    public = json.loads((ROOT / 'site/admissions-data.js').read_text(encoding='utf-8-sig').split('=', 1)[1].strip().rstrip(';'))
    policies = {p['id']: p for p in public['policies']}
    assert len(ADDED_ACTION_IDS) == 27 and sum(map(len, ADDED_ACTION_IDS.values())) == 160
    assert all(pid in policies and set(ids) <= {a['id'] for a in policies[pid].get('material_actions', [])}
               for pid, ids in ADDED_ACTION_IDS.items()), 'Merge and build v21 first'
    additions = {pid: [next(a for a in policies[pid]['material_actions'] if a['id'] == action_id)
                       for action_id in ids] for pid, ids in ADDED_ACTION_IDS.items()}
    assert all(pid in policies for pid in UI), 'Build the two new UCAS institution policies first'
    protected = [ROOT / p for p in ['data/workflow.json', 'data/workflow.yaml', 'data/outreach.yaml',
                                   'data/backup.json', 'data/discovery.yaml', 'data/student.yaml', 'data/student_sop.md']]
    signatures = lambda: {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for p in protected}
    before = signatures()
    results = dict(coverage=[], conditional=[], reminders=[], ui=[], browser_errors=[], all_writes_temporary=True)

    def goal(policy):
        dept = policy['dept'] or next(u['dept'] for u in public['units'] if u['school'] == policy['school'])
        return dict(school_id=policy['school'], dept_id=dept, year=policy['year'], degree=policy['degree'],
                    route=policy['route'], track='ordinary' if policy.get('track', 'general') == 'general' else policy['track'],
                    program_code=policy.get('program_code', ''), program_name=policy.get('program', ''))

    with tempfile.TemporaryDirectory(prefix='material-policy-v21-') as tmp:
        root = Path(tmp)
        site = root / 'site'
        site.mkdir()
        for name in ['workflow.js', 'material-actions.js', 'data.js', 'admissions-data.js', 'admissions-core.js', 'admissions.js', 'ui.css']:
            shutil.copyfile(ROOT / 'site' / name, site / name)
        env = Environment(loader=FileSystemLoader(ROOT / 'site/templates'))
        for name in ['applications', 'admissions']:
            (site / (name + '.html')).write_text(env.get_template(name + '.html.j2').render(), encoding='utf-8')
        server = create_server(site=site, outreach=root / 'private/outreach.yaml', workflow=root / 'private/workflow.json', port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'

        def request(path='', body=None, method=None, expect=200):
            req = Request(base + '/api/workflow' + path, data=None if body is None else json.dumps(body).encode(),
                          method=method or ('GET' if body is None else 'POST'), headers={'Content-Type': 'application/json', 'Origin': base})
            try:
                with urlopen(req) as response:
                    code, value = response.status, json.load(response)
            except HTTPError as error:
                code, value = error.code, json.load(error)
            assert code == expect, (path, code, expect, value)
            return value

        def save(pid, row, confirmed=True, expect=200):
            return request('/material-tasks', dict(project_id=pid, expected_goal=row['goal_snapshot'],
                policy_id=row['policy_id'], action_id=row['action_id'], expected_action=row['action_fingerprint'],
                status='prepared', material_ids=[], notes='临时验收，未向学校提交', confirmed_conditions=confirmed), expect=expect)

        projects = {}
        try:
            # Every added action must be returned for its actual policy/program target.
            for policy_id, actions in additions.items():
                policy = policies[policy_id]
                project = request('/projects', dict(name='临时v21范围-' + policy_id, **goal(policy)))
                pid = projects[policy_id] = project['id']
                rows = request('/material-tasks')['actions'][pid]
                selected = [next(v for v in rows if v['policy_id'] == policy_id and v['action_id'] == a['id']) for a in actions]
                assert all(v['can_record'] for v in selected), [(v['action_id'], v['quality']) for v in selected]
                results['coverage'].append(dict(policy_id=policy_id, school=policy['school'], new_actions=len(selected), readable=True))
            # NEU already had real material actions and receives no duplicate additions in v21.
            neu = policies['neu-webreg-2027-exam-v15b']
            neu_project = request('/projects', dict(name='临时v21东北既有材料', **goal(neu)))
            assert any(v['policy_id'] == neu['id'] for v in request('/material-tasks')['actions'][neu_project['id']])
            assert len({r['school'] for r in results['coverage']} | {'neu'}) == 26

            for policy_id, action_id in CONDITIONAL:
                pid = projects[policy_id]
                row = next(v for v in request('/material-tasks')['actions'][pid] if v['policy_id'] == policy_id and v['action_id'] == action_id)
                assert row['conditions']
                count = len(request('/material-tasks')['records'])
                save(pid, row, confirmed=False, expect=400)
                assert len(request('/material-tasks')['records']) == count
                save(pid, row)
                results['conditional'].append(dict(policy_id=policy_id, action_id=action_id, unchecked_rejected=True, explicit_save=True))

            # These are four action-to-existing-event links, not four newly invented dates.
            bound = list(SOUTH_EVENT_ACTIONS)
            assert len(bound) == 4
            assert all(next(a for a in policies[pid]['material_actions'] if a['id'] == aid).get('event_indexes')
                       for pid, aid in bound)
            bound += [('jlu-school-2027-exam-v15b', 'failed-academic-email-report')]
            for policy_id, action_id in bound:
                pid = projects[policy_id]
                row = next(v for v in request('/material-tasks')['actions'][pid] if v['policy_id'] == policy_id and v['action_id'] == action_id)
                save(pid, row)
                record = next(v for v in request('/material-tasks')['records'].values() if v['project_id'] == pid and v['action_id'] == action_id)
                resolved = row['events'][0]
                event = resolved['event']
                body = dict(expected_goal=row['goal_snapshot'], expected_action=row['action_fingerprint'], event_index=resolved['event_index'])
                reminder = request('/material-tasks/' + record['id'] + '/reminders', body)
                for text in [event['at'], event['quote'], resolved['source_url']]:
                    assert text in reminder['notes']
                expected_day = event['at'] if len(event['at']) == 10 else datetime.fromisoformat(event['at']).astimezone(timezone(timedelta(hours=8))).date().isoformat()
                assert reminder['due_date'] == expected_day
                assert request()['projects'][pid]['deadlines'] == []
                results['reminders'].append(dict(policy_id=policy_id, action_id=action_id, due_date=expected_day, event=event, source_url=resolved['source_url']))

            policy_id = 'nudt-2027-master-exam-v15extra'
            pid = projects[policy_id]
            row = next(v for v in request('/material-tasks')['actions'][pid] if v['policy_id'] == policy_id and v['action_id'] == 'civilian-fresh-academic-proof')
            assert policies[policy_id]['source_id'] == 'nudt_master_latest_20261015_v21'
            save(pid, row)
            record = next(v for v in request('/material-tasks')['records'].values() if v['project_id'] == pid and v['action_id'] == row['action_id'])
            assert record['source_snapshot']['source_id'] == policies[policy_id]['source_id']
            request('/projects/' + pid, dict(school_id='fudan', dept_id='cs'), method='PATCH')
            changed = request('/material-tasks')['records'][record['id']]
            assert changed['review_required'] and not changed['applicable'] and 'goal_changed' in changed['review_reasons']
            assert all(v['latest_record_id'] != record['id'] for v in request('/material-tasks')['actions'][pid])
            results['nudt_current_source_and_changed_goal'] = True

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.on('pageerror', lambda error: results['browser_errors'].append(str(error)))
                for policy_id in UI:
                    policy = policies[policy_id]
                    g = goal(policy)
                    query = dict(school=g['school_id'], dept=g['dept_id'], year=g['year'], degree=g['degree'], route=g['route'], track=g['track'])
                    for width, height in [(1440, 1000), (390, 844)]:
                        page.set_viewport_size(dict(width=width, height=height))
                        page.goto(base + '/admissions.html?' + urlencode(query))
                        page.wait_for_selector('#checklist-project')
                        assert policy['title'] in page.locator('#policy-list').text_content()
                        page.screenshot(path=str(OUT / f'{policy_id}-{width}-public.png'), full_page=True)
                        count = len(request()['projects'])
                        page.locator('#checklist-project').click()
                        page.wait_for_function('window.WORKFLOW_READY')
                        page.wait_for_load_state('networkidle')
                        assert page.input_value('#project-school-id') == g['school_id']
                        assert page.input_value('#project-dept-id') == g['dept_id']
                        assert len(request()['projects']) == count
                        page.fill('#project-name', f'临时v21浏览器-{policy_id}-{width}')
                        page.click('#project-save')
                        page.wait_for_function('!document.querySelector("#project-name").value')
                        page.wait_for_load_state('networkidle')
                        created = next(v for v in request()['projects'].values() if v['name'] == f'临时v21浏览器-{policy_id}-{width}')
                        page.goto(base + '/applications.html?section=preparation&project=' + created['id'])
                        page.wait_for_function('window.WORKFLOW_READY')
                        page.wait_for_load_state('networkidle')
                        page.wait_for_selector('#preparation-list a')
                        rows = request('/material-tasks')['actions'][created['id']]
                        index, sample = next(((i, v) for i, v in enumerate(rows) if v['policy_id'] == policy_id), (0, rows[0]))
                        form = page.locator(f'[data-material-action="{index}"]')
                        article = form.locator('xpath=..')
                        article.locator(':scope > summary').click()
                        assert sample['action']['instruction']['quote'] in article.text_content()
                        if sample['conditions']:
                            assert not form.locator('[name="confirmed_conditions"]').is_checked()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        page.screenshot(path=str(OUT / f'{policy_id}-{width}.png'), full_page=True)
                        assert form.count() == 1 and sample['action']['instruction']['quote'] in article.text_content()
                        article.scroll_into_view_if_needed()
                        page.screenshot(path=str(OUT / f'{policy_id}-{width}-action-viewport.png'))
                        link = page.locator('#preparation-list a').filter(has_text='核对本项目政策与材料要求')
                        assert parse_qs(urlsplit(link.get_attribute('href')).query) == {k: [str(v)] for k, v in query.items()}
                        link.click()
                        page.wait_for_selector('#checklist-project')
                        assert policy['title'] in page.locator('#policy-list').text_content()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        results['ui'].append(dict(policy_id=policy_id, width=width, explicit_project_save=True, public_to_project_to_policy=True))
                browser.close()
            assert not results['browser_errors']
        finally:
            server.shutdown()
            server.server_close()
    assert signatures() == before, 'Real private files changed'
    results.update(passed=True, schools_readable=26, private_signatures_unchanged=True, protected_signatures=before,
                   scope='26-school matching API readability; 4 conditional saves; 5 reminder links; NUDT source/goal isolation; 5 real UI targets at1440/390. Not every action saved or all schools visually tested.')
    (OUT / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS v21 scoped real API/UI flows; all private writes temporary; see cache/policy_v21/integration/live_flow/results.json')


if __name__ == '__main__':
    main()

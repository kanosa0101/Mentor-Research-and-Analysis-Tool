"""Verify public-to-local contact handoff against isolated servers and private files."""
import hashlib
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crawler.public_catalog import load
from scripts import build_site, serve, serve_public


def private_hashes():
    paths = ['data/workflow.yaml', 'data/outreach.yaml', 'data/discovery.yaml', 'data/student.yaml', 'data/student_sop.md']
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() if (ROOT / name).exists() else None for name in paths}


def prepare(root):
    site = root / 'site'
    site.mkdir()
    for name in ('data.js', 'admissions-data.js', 'admissions-core.js', 'ui.css', 'desk.js', 'workflow.js',
                 'material-actions.js', 'opportunities-core.js', 'school-catalog.js', 'discovery-data.js',
                 'search.js', 'discovery-core.js', 'discovery.js', 'browser-library-core.js', 'browser-library.js'):
        shutil.copyfile(ROOT / 'site' / name, site / name)
    env = build_site.template_environment()
    for name in ('desk', 'applications', 'local'):
        (site / (name + '.html')).write_text(env.get_template(name + '.html.j2').render(), encoding='utf8')
    (site / 'discovery.html').write_text(build_site.render_discovery_page(site), encoding='utf8')
    (site / 'p').mkdir()
    mentor = next(p for p in load(ROOT, 'data.js') if p['page'] == 'bit-cs-chaichengliang')
    (site / 'p' / (mentor['page'] + '.html')).write_text('isolated known mentor', encoding='utf8')
    return site, mentor


def main():
    output = ROOT / 'cache/v20/handoff'
    output.mkdir(parents=True, exist_ok=True)
    before = private_hashes()
    results = []
    with tempfile.TemporaryDirectory(prefix='mentor-handoff-v20-') as directory:
        root = Path(directory)
        site, mentor = prepare(root)
        local = serve.create_server(site=site, outreach=root / 'private/outreach.yaml', workflow=root / 'private/workflow.yaml', port=0)
        public = serve_public.create_server(root, '127.0.0.1', 0)
        for server in (local, public):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        local_base, public_base = f'http://127.0.0.1:{local.server_port}', f'http://127.0.0.1:{public.server_port}'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                for width in (1440, 390):
                    context = browser.new_context(viewport={'width': width, 'height': 1000})
                    # Never contact a real user service on port 8000. Only substitute its port at navigation.
                    context.route('http://127.0.0.1:8000/**', lambda route: route.fulfill(status=302, headers={
                        'Location': local_base + urlsplit(route.request.url).path + '?' + urlsplit(route.request.url).query}))
                    page = context.new_page()
                    errors, writes = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: writes.append(request.url) if request.method not in ('GET', 'HEAD', 'OPTIONS') else None)
                    return_path = 'discovery.html?' + urlencode({'name': mentor['name'], 'qualifications': 'phd'})
                    goal = dict(mentor=mentor['page'], school=mentor['school'], dept=mentor['dept'], year='2027',
                                degree='master', route='recommend', track='special', program='0812|隔离专项', discovery_return=return_path)
                    # The same link shape is produced by the real mentor card; verify its mentor ID first.
                    page.goto(public_base + '/' + return_path)
                    page.wait_for_function('window.DISCOVERY_READY')
                    card = page.locator(f'[data-candidate="{mentor["page"]}"]')
                    assert card.count() == 1
                    assert parse_qs(urlsplit(card.get_by_role('link', name='准备联系', exact=True).get_attribute('href')).query)['mentor'] == [mentor['page']]
                    card.get_by_role('link', name='准备联系', exact=True).click()
                    page.wait_for_selector('#open-local')
                    assert urlsplit(page.url).path == '/local.html'
                    card_handoff = parse_qs(urlsplit(page.locator('#open-local').get_attribute('href')).query)
                    assert card_handoff['mentor'] == [mentor['page']] and card_handoff['discovery_return'] == [return_path]
                    page.goto(public_base + '/desk.html?' + urlencode(dict(goal, project='private-project-must-not-forward', material='private-file-must-not-forward')))
                    page.wait_for_selector('#open-local')
                    public_q = parse_qs(urlsplit(page.url).query)
                    assert urlsplit(page.url).path == '/local.html'
                    assert 'project' not in public_q and 'material' not in public_q
                    destination = urlsplit(page.locator('#open-local').get_attribute('href'))
                    assert destination.hostname == '127.0.0.1' and destination.port == 8000 and destination.path == '/desk.html'
                    local_q = parse_qs(destination.query)
                    for key, value in goal.items():
                        assert local_q.get(key) == [value], (key, local_q)
                    assert not {'project', 'material', 'target'} & local_q.keys()
                    page.screenshot(path=str(output / f'public-local-{width}.png'))
                    page.locator('#open-local').click()
                    page.wait_for_function('window.CONTACT_READY')
                    assert page.evaluate('incomingMentor') == mentor['page']
                    assert page.evaluate('incomingGoal.year') == 2027
                    assert page.evaluate('forwardedGoal().program') == goal['program']
                    assert page.evaluate('discoveryReturn') == return_path
                    assert mentor['name'] in page.locator('#prepare-empty').inner_text()
                    before_nav = page.evaluate('api()')
                    # Existing projects may be present from the first viewport; all belong to this temp directory.
                    manage = page.locator('#manage-link')
                    href = manage.get_attribute('href')
                    assert parse_qs(urlsplit(href).query)['discovery_return'] == [return_path]
                    page.locator('.site-header details').evaluate_all('(nodes)=>nodes.forEach(node=>node.open=true)')
                    manage.click()
                    page.wait_for_function('window.WORKFLOW_READY')
                    assert page.evaluate('contextMentor') == mentor['page']
                    assert page.evaluate('api()') == before_nav, 'navigation must not save private records'
                    back = parse_qs(urlsplit(page.locator('#back-desk').get_attribute('href')).query)
                    assert back['mentor'] == [mentor['page']] and back['discovery_return'] == [return_path]
                    assert back['program'] == [goal['program']]
                    # Seed legitimate records only through the temporary local API, then exercise the UI project switch.
                    project = page.evaluate('(id)=>api("/projects",{name:"隔离转接验收",year:2027,mentor_ids:[id]},"POST")', mentor['page'])
                    page.reload()
                    page.wait_for_function('window.WORKFLOW_READY')
                    page.locator('#filter-project').select_option(project['id'])
                    page.wait_for_function('(id)=>new URLSearchParams(location.search).get("project")===id', arg=project['id'])
                    assert parse_qs(urlsplit(page.url).query)['discovery_return'] == [return_path]
                    back = parse_qs(urlsplit(page.locator('#back-desk').get_attribute('href')).query)
                    assert back['project'] == [project['id']] and back['discovery_return'] == [return_path]
                    page.locator('#back-desk').click()
                    page.wait_for_function('window.CONTACT_READY')
                    assert page.evaluate('incomingMentor') == mentor['page']
                    assert page.evaluate('discoveryReturn') == return_path
                    assert mentor['name'] in page.locator('#context-name').inner_text()
                    page.screenshot(path=str(output / f'local-contact-{width}.png'))
                    back_link = page.locator('a[href]').filter(has_text='继续找导师').first
                    if not back_link.count():
                        back_link = page.locator('.site-header a').filter(has_text='找导师').first
                    assert urlsplit(back_link.get_attribute('href')).path == 'discovery.html'
                    assert back_link.get_attribute('href') == return_path
                    back_link.click()
                    page.wait_for_function('window.DISCOVERY_READY')
                    assert parse_qs(urlsplit(page.url).query)['name'] == [mentor['name']]
                    assert page.locator(f'[data-candidate="{mentor["page"]}"]').count() == 1
                    assert not errors, errors
                    assert all(url.startswith(local_base + '/api/workflow') for url in writes), writes
                    results.append({'width': width, 'public_scope_preserved': True, 'private_parameters_removed': True,
                                    'mentor_and_goal_recognized': True, 'project_roundtrip_and_return': True, 'private_writes': len(writes)})
                    context.close()
                context = browser.new_context()
                page = context.new_page()
                for bad in ('https://evil.example/steal', '//evil.example/path', 'javascript:alert(1)', 'discovery.html/../../evil', 'discovery.html?x=1\\evil'):
                    page.goto(public_base + '/desk.html?' + urlencode(dict(goal, discovery_return=bad, project='private', material='private')))
                    page.wait_for_selector('#open-local')
                    href = page.locator('#open-local').get_attribute('href')
                    parsed = urlsplit(href)
                    assert parsed.hostname == '127.0.0.1' and parsed.path == '/desk.html'
                    assert 'discovery_return' not in parse_qs(parsed.query)
                    assert not page.locator('a[href^="https://evil.example"],a[href^="//evil.example"],a[href^="javascript:"]').count()
                page.goto(public_base + '/applications.html?' + urlencode(dict(goal, project='private', material='private')))
                page.wait_for_selector('#open-local')
                assert urlsplit(page.locator('#open-local').get_attribute('href')).path == '/applications.html'
                page.goto(public_base + '/local.html?id=legacy-opportunity-id')
                page.wait_for_selector('#open-local')
                parsed = urlsplit(page.locator('#open-local').get_attribute('href'))
                assert parsed.path == '/opportunities.html' and parse_qs(parsed.query)['id'] == ['legacy-opportunity-id']
                context.close()
                browser.close()
            assert private_hashes() == before
            assert (root / 'private/workflow.yaml').is_file()
            result = {'passed': True, 'cases': results, 'malicious_return_cases': 5, 'legacy_activity_id_preserved': True,
                      'user_private_hashes_unchanged': True, 'local_default_port_intercepted_to_isolated_server': True,
                      'cross_origin_session_storage_transfer_claimed': False}
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            print('Handoff v20: PASS (public redirect, local contact, applications roundtrip, URL boundaries, temporary private only)')
        finally:
            for server in (public, local):
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()

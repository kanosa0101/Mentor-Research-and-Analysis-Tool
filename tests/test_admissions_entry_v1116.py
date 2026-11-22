"""The admissions directory starts inline and loads evidence only for the selected school."""
import hashlib
import json
from urllib.parse import parse_qs, urlencode, urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import expect, sync_playwright

from scripts import build_site


def public_data():
    source = (build_site.SITE / 'admissions-data.js').read_text(encoding='utf8')
    return json.loads(source.split('=', 1)[1].strip().removesuffix(';'))


def open_anonymously(html, verify, *, assets=None, initial='', intercept=None):
    paths, errors, writes = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-proxy-server'])
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def route_request(route):
            request = route.request
            path = urlsplit(request.url).path
            paths.append(path)
            if request.method != 'GET':
                writes.append(path)
                return route.abort()
            if path == '/admissions.html':
                return route.fulfill(content_type='text/html; charset=utf-8', body=html)
            if path == '/api/auth/me':
                return route.fulfill(content_type='application/json', body=json.dumps(dict(authenticated=False, user=None)))
            if assets and path.startswith('/admissions/') and path.endswith('.json'):
                content = assets[path.rsplit('/', 1)[1][:-5]]
                if intercept and intercept(route, path, content):
                    return
                return route.fulfill(content_type='application/json', body=content)
            return route.abort()

        page.route('**/*', route_request)
        try:
            page.goto('http://mentor-test.invalid/admissions.html' + initial)
            page.wait_for_function('window.ADMISSIONS_READY')
            page.evaluate('window.OnlineAccount.ready')
            assert page.locator('.site-header nav a[href^="applications.html"]').is_visible()
            assert page.locator('#policy-school').is_visible()
            verify(page, paths)
            assert errors == writes == []
        finally:
            browser.close()


def test_directory_first_view_does_not_load_full_evidence_and_school_selection_does():
    expected = public_data()
    overview, resources = build_site.admissions_entry_assets(expected)
    html = build_site.render_admissions_page()
    assert not BeautifulSoup(html, 'html.parser').select('script[src], link[rel="stylesheet"]')
    assert len(html.encode('utf-8')) < 200_000

    def verify(page, paths):
        assert page.locator('#policy-welcome').is_visible()
        assert paths.count('/admissions.html') == 1 and set(paths) == {'/admissions.html', '/api/auth/me'}
        assert page.evaluate('window.ADMISSIONS_DATA.policies') == overview['policies']
        assert page.evaluate('typeof AdmissionsRules.select') == 'function'
        assert page.evaluate('typeof MaterialPreparation.publicActions') == 'function'
        school = 'bit'
        page.locator('#policy-school').select_option(school)
        assert page.locator('#policy-school').input_value() == school
        expect(page.locator('#unit-summary')).to_be_visible()
        assert page.evaluate('window.ADMISSIONS_DATA.policies') == [p for p in expected['policies'] if p['school'] == school]
        assert page.evaluate('window.ADMISSIONS_DATA.sources') == json.loads(resources[school])['sources']
        page.locator('#policy-dept').select_option('cs')
        expect(page.locator('#unit-summary')).to_be_visible()
        assert paths.count('/admissions/bit.json') == 1

    open_anonymously(html, verify, assets=resources)


def test_new_output_directory_uses_fresh_data_escapes_script_and_preserves_live_site(tmp_path, monkeypatch):
    live = [build_site.ROOT / 'site' / name for name in ('admissions.html', 'admissions-data.js')]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in live}
    payload = dict(version=1, schools=[dict(id='stage-only', name='</ScRiPt><script>window.injected=true</SCRIPT>')],
                   units=[], groups=[], policies=[], sources={}, checks={}, entries=[])
    (tmp_path / 'admissions-data.js').write_text('window.ADMISSIONS_DATA=' + json.dumps(payload) + ';', encoding='utf8')
    monkeypatch.setattr(build_site, 'SITE', tmp_path)
    html = build_site.render_admissions_page()
    build_site.write_html(tmp_path / 'admissions.html', html)
    soup = BeautifulSoup(html, 'html.parser')
    assert len(soup.select('script')) == 2
    assert not soup.select('script[src], link[rel="stylesheet"]')
    assert (build_site.ROOT / 'site/ui.css').read_text(encoding='utf8') in html

    def verify(page, paths):
        assert page.evaluate('window.ADMISSIONS_DATA.schools') == payload['schools']
        assert page.evaluate('typeof window.injected') == 'undefined'
        assert page.locator('#policy-school option[value="stage-only"]').inner_text() == payload['schools'][0]['name']
        assert set(paths) == {'/admissions.html', '/api/auth/me'}

    open_anonymously((tmp_path / 'admissions.html').read_text(encoding='utf8'), verify)
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in live}


def test_school_assets_keep_all_fields_conditions_material_actions_and_source_references(tmp_path):
    data = public_data()
    folder = tmp_path / 'admissions'
    folder.mkdir()
    (folder / 'stale.json').write_text('{}', encoding='utf8')
    catalog = build_site.build_admissions_assets(tmp_path, data)
    assert {path.stem for path in folder.glob('*.json')} == {s['id'] for s in data['schools']}
    assert len(catalog['policies']) == len(data['policies'])
    for school, version in catalog['school_versions'].items():
        content = json.loads((folder / (school + '.json')).read_bytes())
        assert content.pop('revision') == version
        assert hashlib.sha256(build_site.admissions_json(content).encode()).hexdigest() == version
        assert content['policies'] == [p for p in data['policies'] if p['school'] == school]
        assert content['entries'] == [e for e in data['entries'] if e['school'] == school]
        refs = {key for p in content['policies'] for key in p['review_hashes']} | {e['source_id'] for e in content['entries']}
        assert content['sources'] == {ref: data['sources'][ref] for ref in refs}
        assert content['checks'] == {ref: data['checks'][ref] for ref in refs if ref in data['checks']}


def test_deep_link_loads_one_school_and_reveals_the_requested_policy():
    data = public_data()
    _, resources = build_site.admissions_entry_assets(data)
    html = build_site.render_admissions_page()
    policy = next(p for p in data['policies'] if p['id'] == 'sjtu-auto-2027-master-special')
    intent = {key: str(policy[key]) for key in ('school', 'dept', 'year', 'degree', 'route', 'track')}
    intent.update(program=policy['program_code']+'|'+policy['program'], topics='视觉')
    target = '?'+urlencode(intent)+'#policy-'+policy['id']

    def verify(page, paths):
        assert set(paths) == {'/admissions.html', '/admissions/sjtu.json', '/api/auth/me'}
        card = page.locator(f'[data-policy="{policy["id"]}"]')
        expect(page.locator('#policy-program')).to_have_value(intent['program'])
        expect(card.locator('.policy-body')).to_have_attribute('open', '')
        expect(card.get_by_role('link', name='核对完整政策 ↗')).to_have_attribute('href', data['sources'][policy['source_id']]['url'])
        assert parse_qs(urlsplit(page.url).query) == {key: [value] for key, value in intent.items()}
        for link in ('#checklist-project', '#checklist-mentors'):
            assert parse_qs(urlsplit(page.locator(link).get_attribute('href')).query) == {key: [value] for key, value in intent.items()}
        # Compare what the public evidence and material steps render, across the
        # real catalog, with both the old global bundle and the school payloads.
        assert page.evaluate('''({full,packets}) => full.policies.every(policy => {
          const packet=JSON.parse(packets[policy.school]), scoped=packet.policies.find(p=>p.id===policy.id);
          const evidence=[...Object.values(policy.fields), ...policy.events||[], policy.applies_if,
            ...(policy.material_actions||[]).flatMap(action=>[action.instruction,action.applies_if])].filter(Boolean);
          const links=(p,sources)=>JSON.stringify(evidence.map(item=>AdmissionsRules.sourceReferences(p,item,sources)));
          return links(policy,full.sources)===links(scoped,packet.sources)&&
            MaterialPreparation.publicActions(policy,full)===MaterialPreparation.publicActions(scoped,packet);
        })''', {'full': data, 'packets': resources})

    open_anonymously(html, verify, assets=resources, initial=target)


def test_slow_previous_school_response_does_not_replace_the_current_school():
    _, resources = build_site.admissions_entry_assets(public_data())
    held = []

    def delay(route, path, content):
        if path == '/admissions/bit.json':
            held.append((route, content))
            return True
        return False

    def verify(page, paths):
        page.locator('#policy-school').select_option('bit')
        expect(page.locator('#policy-data-message')).to_contain_text('正在读取')
        page.locator('#policy-school').select_option('tsinghua')
        expect(page.locator('#unit-name')).to_have_text('清华大学')
        bit_route, content = held.pop()
        bit_route.fulfill(content_type='application/json', body=content)
        page.evaluate('schoolRequests.get("bit")')
        assert paths.count('/admissions/bit.json') == paths.count('/admissions/tsinghua.json') == 1
        assert page.evaluate('ADMISSIONS_DATA.policies.every(p=>p.school==="tsinghua")')
        assert parse_qs(urlsplit(page.url).query) == {'school': ['tsinghua']}
        expect(page.locator('#policy-data-status')).to_be_hidden()
        page.locator('#policy-school').select_option('bit')
        expect(page.locator('#unit-name')).to_have_text('北京理工大学')
        assert paths.count('/admissions/bit.json') == 1

    open_anonymously(build_site.render_admissions_page(), verify, assets=resources, intercept=delay)


def test_timeout_clears_old_school_policy_and_retry_reuses_the_selected_scope():
    _, resources = build_site.admissions_entry_assets(public_data())
    requests = []

    def delay(route, path, content):
        if path == '/admissions/tsinghua.json':
            requests.append(path)
            return len(requests) == 1
        return False

    def verify(page, paths):
        expect(page.locator('[data-policy]').first).to_be_visible()
        page.evaluate('''() => {const original=window.setTimeout;window.setTimeout=(f,delay,...args)=>original(f,delay===8000?100:delay,...args);}''')
        page.locator('#policy-school').select_option('tsinghua')
        expect(page.locator('#policy-data-message')).to_contain_text('超时')
        expect(page.locator('[data-policy]')).to_have_count(0)
        expect(page.locator('#policy-results')).to_be_hidden()
        page.locator('#policy-data-retry').click()
        expect(page.locator('#unit-name')).to_have_text('清华大学')
        assert page.locator('#policy-year').input_value() == '2027'
        assert parse_qs(urlsplit(page.url).query)['school'] == ['tsinghua']
        assert len(requests) == 2
        expect(page.locator('#policy-data-status')).to_be_hidden()

    open_anonymously(build_site.render_admissions_page(), verify, assets=resources,
                     initial='?school=bit&year=2027', intercept=delay)


def test_revision_mismatch_requires_refresh_without_showing_unmatched_evidence():
    _, resources = build_site.admissions_entry_assets(public_data())
    visits = []

    def mismatch(route, path, content):
        if path != '/admissions/bit.json':
            return False
        visits.append(path)
        if len(visits) == 1:
            packet = json.loads(content)
            packet['revision'] = 'new-version'
            route.fulfill(json=packet)
            return True
        return False

    def verify(page, paths):
        page.locator('#policy-school').select_option('bit')
        expect(page.locator('#policy-data-message')).to_contain_text('资料已更新')
        expect(page.locator('[data-policy]')).to_have_count(0)
        page.get_by_role('button', name='刷新页面').click()
        page.wait_for_function('window.ADMISSIONS_READY')
        expect(page.locator('[data-policy]').first).to_be_visible()
        assert parse_qs(urlsplit(page.url).query)['school'] == ['bit']
        assert len(visits) == 2

    open_anonymously(build_site.render_admissions_page(), verify, assets=resources, intercept=mismatch)


def test_raw_template_retains_preview_dependency_order():
    html = build_site.template_environment().get_template('admissions.html.j2').render()
    scripts = [node['src'].split('?')[0] for node in BeautifulSoup(html, 'html.parser').select('script[src]')]
    assert scripts == ['account-session.js', 'cloud-library.js', 'admissions-data.js',
                       'admissions-core.js', 'material-actions.js', 'admissions.js']

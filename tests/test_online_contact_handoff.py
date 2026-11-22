"""Exercise the online account, application and contact handoffs in Chromium."""
import json
import shutil
import ssl
from datetime import datetime, timedelta, timezone
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from playwright.sync_api import expect, sync_playwright
import pytest

from scripts import build_site, serve_public


MENTOR = {
    'page': 'bit-cs-fixture', 'name': '验收导师', 'school': 'bit', 'school_name': '北京理工大学',
    'dept': 'cs', 'dept_name': '计算机学院', 'email': 'mentor@example.invalid', 'provenance': {},
}
DISCOVERY = 'discovery.html?school=bit&dept=cs&name=fixture'
GOAL = dict(school='bit', dept='cs', year=2027, degree='master', route='recommend', track='ordinary')
PASSWORD = 'fixture-password-only'


@pytest.fixture
def online_site(tmp_path):
    site = tmp_path / 'site'
    (site / 'p').mkdir(parents=True)
    env = build_site.template_environment()
    for name in ('account', 'applications', 'desk', 'compare'):
        template = env.get_template(name + '.html.j2')
        (site / (name + '.html')).write_text(template.render(), encoding='utf-8')
    detail = env.get_template('detail.html.j2').render(p=MENTOR)
    (site / 'p' / (MENTOR['page'] + '.html')).write_text(detail, encoding='utf-8')
    (site / 'discovery.html').write_text('<h1>Fixture discovery</h1>', encoding='utf-8')
    for name in ('ui.css', 'desk.js', 'account.js', 'account-session.js', 'cloud-library.js',
                 'browser-library-core.js', 'browser-library.js'):
        shutil.copyfile(build_site.SITE / name, site / name)
    mentors = 'window.MENTOR_DATA = ' + json.dumps([MENTOR]) + ';\n'
    admissions = 'window.ADMISSIONS_DATA = ' + json.dumps({
        'units': [{'school': 'bit', 'dept': 'cs', 'school_name': MENTOR['school_name'], 'dept_name': MENTOR['dept_name']}],
        'policies': [], 'sources': {}, 'checks': {},
    }) + ';\n'
    (site / 'contact-data.js').write_text(mentors, encoding='utf-8')
    (site / 'data.js').write_text(mentors, encoding='utf-8')
    (site / 'compare-data.js').write_text('window.MENTOR_COMPARE = {};', encoding='utf-8')
    (site / 'application-data.js').write_text(mentors + admissions, encoding='utf-8')
    build_site.build_application_entry(site)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
                   .not_valid_after(now + timedelta(hours=1)).sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / 'certificate.pem', tmp_path / 'key.pem'
    cert_file.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    server = serve_public.create_server(tmp_path, '127.0.0.1', 0)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_file, key_file)
    server.socket = tls.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f'https://127.0.0.1:{server.server_port}', str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()


def query(url):
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}


def register(page):
    page.locator('[data-account-mode=register]').click()
    page.locator('#account-username').fill('fixture_contact')
    page.locator('#account-password').fill(PASSWORD)
    page.locator('#account-confirm').fill(PASSWORD)
    page.locator('#account-submit').click()


@pytest.mark.parametrize('width', [390, 1440])
def test_mentor_project_material_and_communication_keep_contact_context(online_site, width):
    base, port = online_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=['--no-proxy-server', '--explicitly-allowed-ports=' + port])
        page = browser.new_page(ignore_https_errors=True, viewport={'width': width, 'height': 900})
        page.set_default_timeout(8000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        intent = dict(GOAL, discovery_return=DISCOVERY)
        page.goto(f'{base}/p/{MENTOR["page"]}.html?' + urlencode(intent))
        page.get_by_role('link', name='准备联系 验收导师').click()
        page.wait_for_url('**/account.html?**')
        next_query = query(query(page.url)['next'])
        assert next_query['discovery_return'] == DISCOVERY and next_query['mentor'] == MENTOR['page']
        assert {key: next_query[key] for key in GOAL} == {key: str(value) for key, value in GOAL.items()}
        register(page)
        page.wait_for_url('**/desk.html?**')
        page.wait_for_function('window.CONTACT_READY')
        page.locator('#prepare-empty a').click()
        page.wait_for_function('window.WORKFLOW_READY && !document.getElementById("workspace").disabled')
        expect(page.locator('#project-school-id')).to_have_value('bit')
        expect(page.locator('#project-dept-id')).to_have_value('cs')
        expect(page.locator('#project-year')).to_have_value('2027')
        expect(page.locator('#project-degree')).to_have_value('master')
        expect(page.locator('#project-route')).to_have_value('recommend')
        expect(page.locator('#project-mentor-selected')).to_contain_text('验收导师')
        page.locator('#project-name').fill('隔离验收申请')
        page.locator('#project-save').click()
        expect(page.locator('#project-feedback')).to_contain_text('已保存')
        project = page.locator('#filter-project').input_value()
        assert project

        page.locator('#project-next [data-section=material]').click()
        assert page.locator('#material-projects').evaluate('(node)=>[...node.selectedOptions].map(o=>o.value)') == [project]
        payload = b'isolated fixture file'
        page.locator('#material-file').set_input_files({'name': 'fixture.txt', 'mimeType': 'text/plain', 'buffer': payload})
        page.locator('#material-save').click()
        expect(page.locator('#material-feedback')).to_contain_text('已保存到账号')
        download = page.get_by_role('link', name='下载材料')
        assert page.request.get(base + download.get_attribute('href')).body() == payload

        page.locator('nav [data-section=communication]').click()
        expect(page.locator('#communication-project')).to_have_value(project)
        expect(page.locator('#communication-mentor-selected')).to_contain_text('验收导师')
        page.locator('#communication-subject').fill('验收沟通记录')
        page.locator('#communication-save').click()
        expect(page.locator('#communication-feedback')).to_contain_text('已保存')
        page.locator('#back-desk').click()
        page.wait_for_function('window.CONTACT_READY && !document.getElementById("desk-workspace").disabled')
        expect(page.locator('#context-name')).to_have_text('验收导师')
        expect(page.locator('#context-project')).to_contain_text('隔离验收申请')
        page.get_by_role('button', name='历史', exact=True).click()
        expect(page.locator('#contact-history')).to_contain_text('验收沟通记录')
        profile = page.locator('#context-profile')
        assert query(profile.get_attribute('href'))['project'] == project

        # Clicking a project action on the same project must not reset the return panel.
        page.locator('#manage-link').click()
        page.wait_for_function('window.WORKFLOW_READY && !document.getElementById("workspace").disabled')
        page.locator('#project-list [data-project-section=material]:visible').click()
        assert query(page.locator('#back-desk').get_attribute('href')).get('panel') == 'history'
        page.locator('#back-desk').click()
        page.wait_for_function('window.CONTACT_READY && !document.getElementById("desk-workspace").disabled')
        expect(page.locator('#contact-history')).to_be_visible()

        page.get_by_role('button', name='写邮件', exact=True).click()
        for size, subject in enumerate(('验收草稿甲', '验收草稿乙'), start=2):
            page.locator('#draft-new').click()
            page.locator('#draft-subject').fill(subject)
            page.locator('#draft-basis').fill('验收研究内容')
            page.locator('#draft-body').fill('验收邮件正文')
            page.locator('#draft-save').click()
            expect(page.locator('#draft-choice option')).to_have_count(size)
            expect(page.locator('#draft-status')).to_contain_text('已保存')
        older = page.locator('#draft-choice option').nth(2).get_attribute('value')
        page.locator('#draft-choice').select_option(older)
        page.locator('#draft-manage').click()
        page.wait_for_function('window.WORKFLOW_READY && !document.getElementById("workspace").disabled')
        page.locator('#back-desk').click()
        page.wait_for_function('window.CONTACT_READY && !document.getElementById("desk-workspace").disabled')
        expect(page.locator('#draft-choice')).to_have_value(older)
        expect(page.locator('#draft-materials')).to_contain_text('fixture.txt')

        # The manage link beside the add-contact form follows the project selected in that form.
        other = page.evaluate('api("/projects", {name:"待加入的隔离项目"}, "POST")')['id']
        page.reload()
        page.wait_for_function('window.CONTACT_READY && !document.getElementById("desk-workspace").disabled')
        page.locator('.tabs [data-view=targets]').click()
        page.locator('#target-project').select_option(other)
        assert query(page.locator('#target-manage').get_attribute('href'))['project'] == other
        page.locator('#target-manage').click()
        page.wait_for_function('window.WORKFLOW_READY && !document.getElementById("workspace").disabled')
        expect(page.locator('#filter-project')).to_have_value(other)
        expect(page.locator('#project-list')).to_contain_text('待加入的隔离项目')

        # A saved project + mentor remains authoritative when the discovery intent changes.
        changed = dict(intent, year=2028, project=project)
        page.goto(f'{base}/p/{MENTOR["page"]}.html?' + urlencode(changed))
        link = page.get_by_role('link', name='准备联系 验收导师')
        assert query(link.get_attribute('href')).get('project') == project
        application_link = page.get_by_role('link', name='我的申请')
        application_query = query(application_link.get_attribute('href'))
        assert (application_query['mentor'], application_query['project'], application_query['discovery_return']) == (
            MENTOR['page'], project, DISCOVERY,
        )
        assert 'project' not in query(page.get_by_role('link', name='学校与院系招生要求').get_attribute('href'))
        page.locator('#detail-compare').click()
        page.locator('#detail-selection').click()
        page.locator('.compare-contact').click()
        page.wait_for_function('window.CONTACT_READY && !document.getElementById("desk-workspace").disabled')
        expect(page.locator('#context-project')).to_contain_text('隔离验收申请')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        assert query(page.url)['project'] == project
        return_link = page.get_by_role('navigation', name='主导航').get_by_role('link', name='找导师')
        assert return_link.get_attribute('href') == DISCOVERY
        return_link.click()
        assert query(page.url) == query(DISCOVERY)
        assert errors == []
        browser.close()

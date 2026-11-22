from datetime import datetime, timezone
from hashlib import sha256

import pytest
import yaml

from crawler import mentor_fields, mentor_recovery


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
NAME = '张甲'
DETAIL = 'https://cs.example.edu.cn/profiles/one.htm'
HOME = 'https://cs.example.edu.cn/home/other.htm'
LINKED = 'https://cs.example.edu.cn/profiles/contact.htm'
EMAIL = 'researcher@example.edu.cn'
FUDAN_HTTP = 'http://ai.fudan.edu.cn/example/list.htm?person=42'
FUDAN_HTTPS = 'https://ai.fudan.edu.cn/example/list.htm?person=42'
FUDAN_EMAIL = 'researcher@fudan.edu.cn'


def write_yaml(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(record, allow_unicode=True), encoding='utf-8')


def unit(root, school, hook_name, profile, hook, *, managed=False):
    config = root / 'sites' / school / 'cs.yaml'
    base_url = 'https://cs.fudan.edu.cn' if school == 'fudan' else 'https://cs.example.edu.cn'
    write_yaml(config, {'school': school, 'dept': 'cs', 'base_url': base_url,
                        'hook': hook_name, 'contact_hook_only': managed})
    config.with_name(hook_name + '.py').write_text(hook, encoding='utf-8')
    path = root / 'data/professors' / school / 'cs/primary.yaml'
    write_yaml(path, {'school': school, 'dept': 'cs', 'slug': 'primary', 'name': NAME,
                      'title': '副教授', **profile})
    return path


@pytest.mark.parametrize('identity_conflict', [True, False])
def test_field_writer_uses_generic_contacts_only_after_ordinary_parse_failure(tmp_path, identity_conflict):
    error = ('mentor_recovery.IdentityConflict("详情明确身份与原档不符")'
             if identity_conflict else 'ValueError("普通模板暂缺字段")')
    hook = ('from crawler import mentor_recovery\n'
            'def parse_detail(cfg, html, url):\n'
            f'    raise {error}\n')
    path = unit(tmp_path, 'example', 'test_hook', {'detail_url': DETAIL}, hook)
    primary = (f'<article><h1>{NAME}</h1><p>邮箱：{EMAIL}</p>'
               f'<p><a href="{HOME}">个人主页</a></p>'
               f'<p><a href="{LINKED}">联系方式</a></p></article>').encode()
    target = f'<article><h1>{NAME}</h1><p>导师个人主页</p></article>'.encode()
    requested = []

    def fetch(source):
        url = source['url']
        requested.append(url)
        return {DETAIL: primary, HOME: target, LINKED: target}[url]

    report = mentor_fields.run(tmp_path, units=('example/cs',), limit=2, workers=1, fetcher=fetch, now=NOW)
    assert report['attempted'] == 1
    saved = yaml.safe_load(path.read_bytes())
    item = report['results'][0]
    if identity_conflict:
        assert saved.get('email') is None
        assert saved.get('homepage') is None
        assert requested == [DETAIL]
        assert not item['field_evidence']
        assert item['status'] == 'error'
        assert '身份与原档不符' in item['reason']
        record = mentor_fields.read(tmp_path)['records']['example/cs/primary']
        assert not record.get('contact_search', {}).get('queue')
    else:
        assert saved['email'] == EMAIL
        assert saved['homepage'] == HOME
        assert item['field_evidence']['email']['sha256'] == sha256(primary).hexdigest()
        assert item['field_evidence']['homepage']['target_evidence']['sha256'] == sha256(target).hexdigest()


def test_identity_conflict_preserves_separately_attested_contact(tmp_path):
    hook = (
        'from crawler.mentor_recovery import IdentityConflict\n'
        'def parse_contact(cfg, original):\n'
        f'    _, text = cfg["_read_source"]({LINKED!r})\n'
        f'    assert {NAME!r} in text and {EMAIL!r} in text\n'
        f'    return {{"email": {EMAIL!r}, "_verified_roster_name": original["name"],\n'
        f'            "_field_sources": {{"email": {LINKED!r}}}}}\n'
        'def parse_detail(cfg, html, url):\n'
        '    raise IdentityConflict("主详情对应另一登记记录")\n'
    )
    path = unit(tmp_path, 'example', 'test_hook', {'detail_url': DETAIL}, hook)
    verified = f'<article><h1>{NAME}</h1><p>邮箱：{EMAIL}</p></article>'.encode()
    wrong = (f'<article><h1>{NAME}</h1><p>邮箱：another@example.edu.cn</p>'
             f'<p><a href="{HOME}">个人主页</a></p></article>').encode()
    requested = []

    def fetch(source):
        url = source['url']
        requested.append(url)
        return {LINKED: verified, DETAIL: wrong}[url]

    report = mentor_fields.run(tmp_path, units=('example/cs',), limit=1, workers=1, fetcher=fetch, now=NOW)
    saved = yaml.safe_load(path.read_bytes())
    assert saved['email'] == EMAIL
    assert saved['provenance']['email']['source'] == LINKED
    assert saved.get('homepage') is None
    assert requested == [LINKED, DETAIL]
    item = report['results'][0]
    assert item['field_evidence']['email']['sha256'] == sha256(verified).hexdigest()
    assert '主详情对应另一登记记录' in item['reason']


@pytest.mark.parametrize(('case', 'target', 'hook_name', 'claimed_name', 'capture', 'accepted'), [
    ('matched', FUDAN_HTTPS, 'fudan_cs', NAME, True, True),
    ('alternate_path', FUDAN_HTTPS.replace('/example/', '/other/'), 'fudan_cs', NAME, True, False),
    ('other_host', FUDAN_HTTPS.replace('ai.fudan', 'cs.fudan'), 'fudan_cs', NAME, True, False),
    ('other_query', FUDAN_HTTPS.replace('42', '43'), 'fudan_cs', NAME, True, False),
    ('other_hook', FUDAN_HTTPS, 'generic_cs', NAME, True, False),
    ('wrong_name', FUDAN_HTTPS, 'fudan_cs', '张乙', True, False),
    ('not_captured', FUDAN_HTTPS, 'fudan_cs', NAME, False, False),
    ('manual', FUDAN_HTTPS, 'fudan_cs', NAME, True, False),
    ('other_owner', FUDAN_HTTPS, 'fudan_cs', NAME, True, False),
])
def test_field_writer_attests_fudan_registered_https_equivalent(
        tmp_path, case, target, hook_name, claimed_name, capture, accepted):
    hook = (
        'def parse_contact(cfg, original):\n'
        f'    if {capture}:\n'
        f'        cfg["_read_source"]({target!r})\n'
        f'    return {{"email": {FUDAN_EMAIL!r}, "_verified_roster_name": {claimed_name!r},\n'
        f'            "_field_sources": {{"email": {target!r}}}}}\n'
        'def parse_detail(cfg, html, url):\n'
        '    return {"name": cfg["_expected_name"]}\n'
    )
    profile = {'detail_url': FUDAN_HTTP}
    manual = {'origin': 'manual', 'source': FUDAN_HTTP, 'fetched_at': '2026-09-01', 'confidence': 'verified'}
    if case == 'manual':
        profile['provenance'] = {'email': manual}
    if case == 'other_owner':
        other = tmp_path / 'data/professors/other/cs/second.yaml'
        write_yaml(other, {'school': 'other', 'dept': 'cs', 'slug': 'second', 'name': '另外一人',
                           'detail_url': 'https://other.edu.cn/profile.htm', 'email': FUDAN_EMAIL})
    path = unit(tmp_path, 'fudan', hook_name, profile, hook, managed=True)
    raw = f'<main><h1>{NAME}</h1><p>邮箱：{FUDAN_EMAIL}</p></main>'.encode()
    requested = []

    def fetch(source):
        url = source['url']
        requested.append(url)
        assert url in {FUDAN_HTTPS, target}
        assert mentor_recovery.allowed(url, source['official_scope'])
        return raw

    report = mentor_fields.run(tmp_path, units=('fudan/cs',), limit=2, workers=1, fetcher=fetch, now=NOW)
    assert report['attempted'] == 1
    assert FUDAN_HTTP not in requested
    saved = yaml.safe_load(path.read_bytes())
    if accepted:
        proof = report['results'][0]['field_evidence']['email']
        assert saved['email'] == FUDAN_EMAIL
        assert saved['provenance']['email']['source'] == FUDAN_HTTPS
        assert proof['url'] == FUDAN_HTTPS and proof['sha256'] == sha256(raw).hexdigest()
    else:
        assert saved.get('email') is None
        assert 'email' not in report['results'][0]['field_evidence']
    if case == 'manual':
        assert saved['provenance']['email'] == manual
    if case == 'other_owner':
        assert yaml.safe_load(other.read_bytes())['email'] == FUDAN_EMAIL


@pytest.mark.parametrize('school,registered', [('other', FUDAN_HTTP),
                                              ('fudan', FUDAN_HTTP.replace('ai.fudan', 'other.fudan'))])
def test_managed_http_alias_is_limited_to_the_configured_fudan_hosts(school, registered):
    target = mentor_recovery.canonical(registered)
    person = {'name': NAME, 'detail_url': registered}
    parsed = {'email': FUDAN_EMAIL, '_verified_roster_name': NAME, '_field_sources': {'email': target}}
    captures = {target: {'url': target, 'sha256': 'a' * 64, 'fetched_at': NOW.isoformat()}}
    assert mentor_fields.secondary_hook_proof(person, parsed, captures, {
        'school': school, 'hook': 'fudan_cs', 'contact_hook_only': True,
    }) is None

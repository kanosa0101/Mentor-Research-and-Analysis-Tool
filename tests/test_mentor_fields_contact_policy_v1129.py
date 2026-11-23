from datetime import datetime, timezone
from hashlib import sha256

import pytest
import yaml

from crawler import mentor_fields, mentor_quality, mentor_recovery
from crawler.opportunity_monitor import atomic_json


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
NAME = '张甲'
DETAIL = 'https://cs.example.edu.cn/teachers/one.htm'
HOME = 'https://cs.example.edu.cn/home/one.htm'
ROSTER = 'https://cs.example.edu.cn/teachers/'
EMAIL = 'researcher@example.edu.cn'
UNIT = 'example/cs'
RECORD = UNIT + '/one'


def content(link):
    return (f'<article><h1>{NAME}</h1><p>邮箱：{EMAIL}</p>'
            f'<p>{link}</p></article>').encode()


def stage(root, *, homepage_policy, contact_policy=True, via_hook=False, direct=False, manual=False):
    folder = root / 'sites/example'
    folder.mkdir(parents=True)
    cfg = {'school': 'example', 'dept': 'cs', 'base_url': 'https://cs.example.edu.cn',
           'hook': 'fixture', 'contact_hook_only': contact_policy,
           'list': {'urls': [ROSTER]}}
    if homepage_policy:
        cfg['homepage_hook_only'] = True
    (folder / 'cs.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')
    hook = ('def parse_detail(cfg, html, url):\n'
            f'    return {{"name": {NAME!r}, "research_direction_raw": "搜索算法"'
            + (f', "homepage": {HOME!r}' if direct else '') + '}\n')
    if via_hook:
        hook += ('def parse_contact(cfg, original):\n'
                 f'    _, source = cfg["_read_source"]({DETAIL!r})\n'
                 f'    if "个人主页" not in source or {NAME!r} not in source:\n'
                 '        return {}\n'
                 f'    return {{"homepage": {HOME!r}, "_verified_roster_name": {NAME!r},\n'
                 f'            "_field_sources": {{"homepage": {DETAIL!r}}}}}\n')
    (folder / 'fixture.py').write_text(hook, encoding='utf-8')
    path = root / 'data/professors/example/cs/one.yaml'
    path.parent.mkdir(parents=True)
    person = {'slug': 'one', 'school': 'example', 'dept': 'cs', 'name': NAME,
              'detail_url': DETAIL, 'title': '教授', 'supervisor': '博导'}
    if manual:
        person['provenance'] = {'homepage': {'origin': 'manual', 'source': DETAIL,
                                              'fetched_at': '2026-11-20', 'confidence': 'verified'}}
    path.write_text(yaml.safe_dump(person, allow_unicode=True), encoding='utf-8')
    return path, cfg, person


def run(root, raw, *, target_name=NAME):
    requested = []
    child = f'<article><h1>{target_name}</h1><p>研究简介</p></article>'.encode()

    def source(request):
        url = request['url']
        requested.append(url)
        if url not in (DETAIL, HOME):
            raise ValueError('控制样本无此官方资料')
        return {DETAIL: raw, HOME: child}[url]

    result = mentor_fields.run(root, units=(UNIT,), limit=1, workers=1, request_budget=8,
                               domain_budget=8, fetcher=source, now=NOW)
    assert result['attempted'] == 1
    return requested, result['results'][0], child


@pytest.mark.parametrize('homepage_policy', [False, True])
def test_generic_homepage_remains_available_only_without_opt_in(tmp_path, homepage_policy):
    path, _, _ = stage(tmp_path, homepage_policy=homepage_policy)
    raw = content(f'<a href="{HOME}">实验室主页</a>')
    requests, report, target = run(tmp_path, raw)
    actual = yaml.safe_load(path.read_bytes())
    assert actual['research_direction_raw'] == '搜索算法'
    if homepage_policy:
        assert 'homepage' not in actual and 'homepage' not in report['field_evidence']
        assert requests == [DETAIL]
    else:
        assert actual['homepage'] == HOME
        assert requests == [DETAIL, HOME]
        proof = report['field_evidence']['homepage']
        assert proof['sha256'] == sha256(raw).hexdigest()
        assert proof['target_evidence']['sha256'] == sha256(target).hexdigest()


def test_managed_homepage_does_not_accept_direct_parser_value(tmp_path):
    path, _, _ = stage(tmp_path, homepage_policy=True, direct=True, contact_policy=False)
    # Generic email discovery retains its existing independent scope.
    requests, report, _ = run(tmp_path, content('这里没有已核主页声明'))
    actual = yaml.safe_load(path.read_bytes())
    assert actual['email'] == EMAIL
    assert 'homepage' not in actual and 'homepage' not in report['field_evidence']
    assert requests == [DETAIL]


@pytest.mark.parametrize('target_name,manual,accepted', [(NAME, False, True),
                                                        ('张乙', False, False),
                                                        (NAME, True, False)])
def test_managed_homepage_validates_named_target_only_from_contact_hook(tmp_path, target_name, manual, accepted):
    path, _, before = stage(tmp_path, homepage_policy=True, via_hook=True, manual=manual)
    raw = content(f'个人主页：<a href="{HOME}">{HOME}</a>')
    requests, report, target = run(tmp_path, raw, target_name=target_name)
    assert ROSTER not in requests
    actual = yaml.safe_load(path.read_bytes())
    if accepted:
        assert HOME in requests and actual['homepage'] == HOME
        proof = report['field_evidence']['homepage']
        assert proof['url'] == DETAIL and proof['sha256'] == sha256(raw).hexdigest()
        assert proof['target_evidence']['url'] == HOME
        assert proof['target_evidence']['sha256'] == sha256(target).hexdigest()
    else:
        assert 'homepage' not in actual and 'homepage' not in report['field_evidence']
        assert (HOME in requests) == (not manual)
    if manual:
        assert actual['provenance']['homepage'] == before['provenance']['homepage']


@pytest.mark.parametrize('approved,ordinary_email_complete', [(False, False), (True, False), (False, True)])
def test_managed_homepage_only_resumes_queue_from_contact_hook(tmp_path, approved, ordinary_email_complete):
    path, cfg, person = stage(tmp_path, homepage_policy=True, via_hook=approved,
                              contact_policy=not ordinary_email_complete)
    if ordinary_email_complete:
        person['email'] = EMAIL
        path.write_text(yaml.safe_dump(person, allow_unicode=True), encoding='utf-8')
    link = f'个人主页：<a href="{HOME}">{HOME}</a>' if approved else f'<a href="{HOME}">实验室主页</a>'
    raw = content(link)
    stamp = NOW.isoformat(timespec='seconds')
    evidence = mentor_quality.Sources(tmp_path, None, stamp).capture(DETAIL, raw, stamp)
    state = mentor_fields.seed(tmp_path, NOW)
    state['records'][RECORD]['contact_search'] = {
        'signature': mentor_recovery.signature(tmp_path, cfg), 'next_at': stamp,
        'visited': [DETAIL], 'directory': True,
        'queue': [{'kind': 'homepage_check', 'url': HOME, 'value': HOME, 'parent': evidence,
                   'depth': 1, 'identity_basis': ('configured_official_contact_source' if approved
                                                  else 'registered_official_detail')}],
    }
    atomic_json(tmp_path / mentor_fields.PATH, state)
    requests, report, _ = run(tmp_path, raw)
    actual = yaml.safe_load(path.read_bytes())
    assert actual.get('homepage') == (HOME if approved else None)
    assert actual.get('email') == (EMAIL if ordinary_email_complete else None)
    assert ('homepage' in report['field_evidence']) == approved
    assert (HOME in requests) == approved and ROSTER not in requests
    search = mentor_fields.read(tmp_path)['records'][RECORD].get('contact_search', {})
    assert not search.get('queue') and not search.get('directory')


@pytest.mark.parametrize('difference', ['none', 'school', 'department', 'hook', 'host', 'path', 'query', 'capture_url'])
def test_ustc_https_mail_proof_is_limited_to_exact_registration(difference):
    registered = 'http://cs.ustc.edu.cn/2021/1115/c23239a532870/page.htm'
    cfg = {'school': 'ustc', 'dept': 'cs', 'hook': 'ustc_cs', 'contact_hook_only': True}
    if difference == 'host':
        registered = registered.replace('cs.ustc', 'faculty.ustc')
    target = mentor_recovery.canonical(registered)
    if difference == 'school':
        cfg['school'] = 'example'
    if difference == 'department':
        cfg['dept'] = 'math'
    if difference == 'hook':
        cfg['hook'] = 'wp'
    if difference == 'path':
        target = target.replace('532870', '532871')
    if difference == 'query':
        target += '?identifier=other'
    raw_url = target.replace('532870', '532871') if difference == 'capture_url' else target
    raw_hash = sha256(b'official document').hexdigest()
    captures = {target: {'url': raw_url, 'sha256': raw_hash, 'fetched_at': NOW.isoformat()}}
    person = {'detail_url': registered, 'name': NAME}
    offered = {'_verified_roster_name': NAME, 'email': 'teacher@ustc.edu.cn',
               '_field_sources': {'email': target}}
    proof = mentor_fields.secondary_hook_proof(person, offered, captures, cfg)
    if difference == 'none':
        assert proof['url'] == target and proof['sha256'] == raw_hash and proof['value'] == offered['email']
    else:
        assert proof is None


@pytest.mark.parametrize('old_value', ['搜索算法', '搜索算法。张甲，博士。2009年毕业于示例大学。'])
def test_primary_direction_proof_only_marks_the_current_value_as_verified(tmp_path, old_value):
    path, _, person = stage(tmp_path, homepage_policy=True)
    person['research_direction_raw'] = old_value
    person['provenance'] = {'research_direction_raw': {'origin': 'crawled', 'source': DETAIL,
                                                      'fetched_at': '2026-11-20', 'confidence': 'auto'}}
    path.write_text(yaml.safe_dump(person, allow_unicode=True), encoding='utf-8')
    # It can look complete to the generic field classifier even when this
    # site's parser has verified a different, bounded direction.
    assert mentor_fields.present(person, 'research_direction_raw')
    state = mentor_fields.seed(tmp_path, NOW)
    state['records'][RECORD]['fields']['research_direction_raw'] = {
        'status': 'resolved', 'reason_code': 'record_now_complete', 'first_seen': NOW.isoformat(),
    }
    atomic_json(tmp_path / mentor_fields.PATH, state)
    raw = content('研究方向：搜索算法')
    run(tmp_path, raw)
    assert yaml.safe_load(path.read_bytes())['research_direction_raw'] == old_value
    proof = mentor_fields.read(tmp_path)['records'][RECORD]['fields']['research_direction_raw']
    if old_value == '搜索算法':
        assert proof['reason_code'] == 'field_verified' and proof['source_sha256'] == sha256(raw).hexdigest()
    else:
        assert proof['reason_code'] == 'record_now_complete' and 'source_sha256' not in proof

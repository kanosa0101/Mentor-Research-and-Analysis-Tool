import json
from datetime import timedelta

import pytest

from crawler import legacy_refresh, mentor_quality as quality, mentor_recovery as recovery
from tests.test_mentor_quality_v1114 import NOW, body, put, root


def configure(root):
    path = root / 'sites/test/cs.yaml'
    cfg = quality.load_yaml(path)
    cfg.update(base_url='https://test.edu.cn', profile_lookup_urls=['https://test.edu.cn/people'])
    put(path, cfg)
    path = root / 'data/issues/test-cs.yaml'
    issues = quality.load_yaml(path)
    issues[0]['message'] = 'HTTP 404 for https://test.edu.cn/old'
    put(path, issues)
    return cfg


@pytest.mark.parametrize('message,code', [
    ('HTTP 404 for https://test.edu.cn/503.htm', 'http_not_found'),
    ('HTTP 503 for https://test.edu.cn/404.htm', 'server_error'),
    ('未解析 https://test.edu.cn/info/404/1234.htm', 'template_empty'),
    ('HTTP 429', 'rate_limited'), ('certificate verify failed', 'tls_error')])
def test_transport_classification_ignores_article_numbers(message, code):
    assert recovery.classify(message)['reason_code'] == code


@pytest.mark.parametrize('url', ['https://other.edu.cn/a', 'http://test.edu.cn/a',
    'https://test.edu.cn:8443/a', 'https://user@test.edu.cn/a', 'https://127.0.0.1/a'])
def test_replacement_boundary(url):
    assert not recovery.allowed(url, 'https://test.edu.cn')


def test_404_discovers_without_requesting_dead_url(root):
    configure(root)
    requested = []
    def fetch(source):
        requested.append(source['url'])
        if source['url'] == 'https://test.edu.cn/new':
            return body()
        assert not source['url'].endswith('/old')
        return '<a href="/new">张老师教授</a>'
    result = quality.run(root, fetcher=fetch, now=NOW)
    assert result['resolved'] == 1
    assert result['results'][0]['replacement']['identity_basis'] == 'name_and_email'
    assert result['results'][0]['source_urls']['profile'] == 'https://test.edu.cn/new'
    assert requested.count('https://test.edu.cn/people') == 1


@pytest.mark.parametrize('field', ['detail_url', 'profile_url'])
def test_manual_urls_block_automatic_migration(root, field):
    configure(root)
    path = root / 'data/professors/test/cs/teacher.yaml'
    before = quality.load_yaml(path)
    before[field] = 'https://test.edu.cn/old'
    before['provenance'][field] = dict(origin='manual', source=before[field], fetched_at='2026-10-01')
    put(path, before)
    result = quality.run(root, fetcher=lambda s: body() if s['url'].endswith('/new') else '<a href="/new">张老师</a>', now=NOW)
    assert result['error'] == 1 and result['results'][0]['reason_code'] == 'identity_conflict'
    assert 'https://test.edu.cn/new' in result['results'][0]['reason']
    assert quality.load_yaml(path) == before


def test_cached_parent_link_must_still_exist(root):
    cfg = configure(root)
    sources = quality.Sources(root, lambda s:'<a href="/new">张老师</a>', NOW.isoformat())
    recovery.directory_index(root, cfg, sources)
    requested = []
    def fetch(source):
        requested.append(source['url'])
        assert not source['url'].endswith('/new')
        return '<p>教师目录已更新</p>'
    result = quality.run(root, fetcher=fetch, now=NOW+timedelta(hours=1))
    assert result['error'] == 1
    assert '不再链接' in result['results'][0]['reason']


def test_manual_url_cannot_be_rewritten_by_https_fallback(root):
    cfg = configure(root)
    person = quality.load_yaml(root/'data/professors/test/cs/teacher.yaml')
    person['detail_url'] = 'http://test.edu.cn/old'
    person['provenance']['detail_url'] = dict(origin='manual', source=person['detail_url'], fetched_at='2026-10-01')
    sources = quality.Sources(root,lambda s:body() if s['url'].endswith('/old') else '<p>无</p>',NOW.isoformat())
    with pytest.raises(ValueError,match='人工维护'):
        quality.profile(root,person,cfg,sources,failure_reason='未解析到有效姓名')


def test_roster_row_is_exact_and_conflicts_are_rejected():
    cfg = dict(profile_directory_format='faculty_table', profile_table_columns=dict(name=0, subjects=1, email=2))
    html = '<table><tr><td>张老师</td><td>计算机</td><td>a@test.edu.cn</td></tr><tr><td>李老师</td><td>自动化</td><td>b@test.edu.cn</td></tr></table>'
    row, _ = recovery.directory_fields(cfg, html, '张老师')
    assert row['email'] == 'a@test.edu.cn' and row['subjects'] == '计算机'
    duplicate = html.replace('李老师', '张老师')
    assert recovery.directory_fields(cfg, duplicate, '张老师') == (None, None)


def test_legacy_refresh_honors_recovery_cooldown_but_parser_change_reopens(root):
    cfg = configure(root)
    path = root/'cache/legacy_refresh/state.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(records={'professor/test/cs/teacher.yaml':dict(status='error', source_url='https://test.edu.cn/old')})), encoding='utf-8')
    quality.run(root, fetcher=lambda s:'<p>无导师链接</p>', now=NOW)
    assert legacy_refresh.run(root, kind='professors', fetcher=lambda s:pytest.fail('known dead URL still cooling down'), now=NOW+timedelta(days=1))['attempted'] == 0
    cfg['parser_revision'] = 2
    put(root/'sites/test/cs.yaml', cfg)
    assert legacy_refresh.run(root, kind='professors', fetcher=lambda s:body().encode('utf-8'), now=NOW+timedelta(days=1))['ok'] == 1


def test_legacy_cooldown_also_works_before_first_legacy_attempt(root):
    configure(root)
    quality.run(root,fetcher=lambda s:'<p>无导师链接</p>',now=NOW)
    assert legacy_refresh.run(root,kind='professors',fetcher=lambda s:pytest.fail('known recovery issue'),now=NOW+timedelta(days=1))['attempted'] == 0


def test_replacement_fetch_rejects_private_dns(monkeypatch):
    import socket
    import requests
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k:[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1',443))])
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **k:pytest.fail('private host was fetched'))
    with pytest.raises(ValueError, match='非公网'):
        quality.fetch_source(dict(url='https://test.edu.cn/a', official_scope='https://test.edu.cn'))


def test_non_body_http_response_keeps_status_without_guessing_cause(monkeypatch):
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def request(self,*args,**kwargs):return self
        status_code=202
        content=b''
        def raise_for_status(self):pass
    monkeypatch.setattr(quality.requests,'Session',Session)
    with pytest.raises(ValueError,match='HTTP 202') as error:
        quality.fetch_source({'url':'https://test.edu.cn/profile'})
    classified = recovery.classify(str(error.value))
    assert classified['reason_code']=='http_unexpected_status'
    assert classified['next_action']=='discover_official_source'


def test_same_name_alone_never_establishes_identity():
    original = dict(name='张老师',detail_url='https://test.edu.cn/old',email='a@test.edu.cn')
    assert recovery.identity(original, dict(name='张老师',email='b@test.edu.cn'),'https://test.edu.cn/new') is None
    assert recovery.identity(original, dict(name='张老师'),'https://other.edu.cn/new') is None


def test_bounded_directory_frontier_progresses_beyond_sixteen_pages(root):
    cfg = configure(root)
    cfg['profile_lookup_urls'] = ['https://test.edu.cn/'+str(i)+'.htm' for i in range(20)]
    seen = []
    def fetch(source):
        seen.append(source['url'])
        return '<a href="/new">张老师</a>' if source['url'].endswith('/19.htm') else '<p>教师目录</p>'
    first = recovery.directory_index(root,cfg,quality.Sources(root,fetch,NOW.isoformat()))
    assert first['pages_checked'] == 16 and first['frontier']
    second = recovery.directory_index(root,cfg,quality.Sources(root,fetch,(NOW+timedelta(days=1)).isoformat()))
    assert any(row['url'].endswith('/new') for row in second['links'])
    assert seen.count('https://test.edu.cn/0.htm') == 1

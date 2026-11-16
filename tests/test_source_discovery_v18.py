import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import yaml

from crawler import source_discovery as discovery

NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
PARENT = 'https://cs.example.edu.cn/admissions.html'
CHILD = 'https://grad.example.edu.cn/camps.html'
RAW = '<html><meta charset="utf-8"><a href="https://grad.example.edu.cn/camps.html">研究生招生</a><a href="https://other.edu.cn/camp">冬令营</a><a href="/login">招生登录</a></html>'.encode()
COLUMN = '<html><meta charset="utf-8"><a href="/winter.html">2027年冬令营招生报名通知</a><a href="/summer.html">2026年夏令营申请公告</a></html>'.encode()


def fixture(root):
    (root / 'sites').mkdir()
    configs = [dict(url=PARENT, school='example', dept='cs', name='计算机学院')]
    (root / 'sites/opportunities.yaml').write_text(yaml.safe_dump(dict(targets=configs)), encoding='utf-8')
    calls = []
    def fetch(url, parent):
        calls.append(url)
        return RAW if url == PARENT else COLUMN
    return configs, calls, fetch


def test_discovery_is_bounded_same_institution_proposal_only_and_due_aware(tmp_path):
    configs, calls, fetch = fixture(tmp_path)
    original = (tmp_path / 'sites/opportunities.yaml').read_bytes()
    result = discovery.run(tmp_path, fetcher=fetch, now=NOW, max_seeds=1, max_candidates=1)
    assert calls == [PARENT, CHILD]
    candidate = result['candidates'][0]
    assert candidate['status'] == 'candidate' and candidate['activity_count'] == 2
    assert candidate['parent_url'] == PARENT and candidate['dept'] == ''
    assert result['summary']['new_candidates'] == 1
    assert (tmp_path / 'sites/opportunities.yaml').read_bytes() == original
    assert not (tmp_path / 'data/opportunities.json').exists()
    discovery.run(tmp_path, fetcher=fetch, now=NOW + timedelta(hours=1))
    assert len(calls) == 2


def test_explicit_approval_rechecks_and_backs_up_config_without_publishing(tmp_path):
    _, _, fetch = fixture(tmp_path)
    original = (tmp_path / 'sites/opportunities.yaml').read_bytes()
    candidate = discovery.run(tmp_path, fetcher=fetch, now=NOW)['candidates'][0]
    approved = discovery.decide(tmp_path, candidate['id'], 'approve', expected_sha256=candidate['source_sha256'], fetcher=fetch, now=NOW)
    assert approved['status'] == 'approved'
    configs = yaml.safe_load((tmp_path / 'sites/opportunities.yaml').read_text(encoding='utf-8'))['targets']
    assert len(configs) == 2 and configs[-1]['url'] == CHILD and configs[-1]['dept'] == ''
    backup = next((tmp_path / 'cache/source-discovery-backups').glob('*.yaml'))
    assert backup.read_bytes() == original
    discovery.decide(tmp_path, candidate['id'], 'approve', expected_sha256=approved['source_sha256'], fetcher=fetch, now=NOW)
    assert len(yaml.safe_load((tmp_path / 'sites/opportunities.yaml').read_text(encoding='utf-8'))['targets']) == 2
    assert discovery.read(tmp_path)['summary']['pending'] == 0
    with pytest.raises(ValueError, match='已接入'):
        discovery.decide(tmp_path, candidate['id'], 'reject', now=NOW)
    assert not (tmp_path / 'data/opportunities.json').exists()


def test_stale_version_changed_content_removed_parent_and_rejection(tmp_path):
    configs, _, fetch = fixture(tmp_path)
    candidate = discovery.run(tmp_path, fetcher=fetch, now=NOW)['candidates'][0]
    with pytest.raises(ValueError, match='版本'):
        discovery.decide(tmp_path, candidate['id'], 'approve', expected_sha256='0' * 64, fetcher=fetch)
    with pytest.raises(ValueError, match='内容'):
        discovery.decide(tmp_path, candidate['id'], 'approve', expected_sha256=candidate['source_sha256'],
                         fetcher=lambda url, _: RAW if url == PARENT else COLUMN.replace(b'winter.html', b'changed.html'))
    with pytest.raises(ValueError, match='父来源当前'):
        discovery.decide(tmp_path, candidate['id'], 'approve', expected_sha256=candidate['source_sha256'],
                         fetcher=lambda url, _: b'<html></html>' if url == PARENT else COLUMN)
    (tmp_path / 'sites/opportunities.yaml').write_text('targets: []', encoding='utf-8')
    with pytest.raises(ValueError, match='父来源'):
        discovery.decide(tmp_path, candidate['id'], 'approve', expected_sha256=candidate['source_sha256'], fetcher=fetch)
    rejected = discovery.decide(tmp_path, candidate['id'], 'reject', now=NOW)
    assert rejected['status'] == 'rejected'
    assert discovery.read(tmp_path)['summary']['pending'] == 0
    discovery.run(tmp_path, configs=configs, fetcher=fetch, refresh=True, now=NOW + timedelta(hours=7))
    assert discovery.read(tmp_path)['candidates'][0]['status'] == 'rejected'


def test_candidate_budget_does_not_starve_later_links_or_mark_unchecked_seeds(tmp_path):
    configs, calls, _ = fixture(tmp_path)
    configs.append(dict(url='https://z.example.edu.cn/list', school='example', dept='', name='研究生院'))
    raw = '<html><meta charset="utf-8"><a href="/a">招生专栏</a><a href="/b">研究生招生</a></html>'.encode()
    def fetch(url, _):
        calls.append(url)
        return raw if url == PARENT else COLUMN if url.endswith('/b') else b'<html>empty</html>'
    first = discovery.run(tmp_path, configs=configs, fetcher=fetch, now=NOW, max_candidates=1)
    assert first['summary']['seeds_attempted'] == 1 and configs[1]['url'] not in first['seeds']
    # Keep the unrelated second seed out of this bounded continuation test.
    second = discovery.run(tmp_path, configs=configs[:1], fetcher=fetch, now=NOW + timedelta(minutes=1), max_candidates=1)
    assert second['summary']['pending'] == 1
    assert calls.count('https://cs.example.edu.cn/a') == 1
    assert calls.count('https://cs.example.edu.cn/b') == 1


@pytest.mark.parametrize('url', ['http://127.0.0.1/private', 'https://other.edu.cn/camp',
    'https://cs.example.edu.cn:8443/private', 'https://x:secret@cs.example.edu.cn/a',
    'https://cs.example.edu.cn/form.docx', 'javascript:alert(1)'])
def test_untrusted_non_html_and_nonstandard_urls_rejected(url):
    with pytest.raises(ValueError):
        discovery.canonical(url, PARENT)


def test_cas_institutes_are_not_same_trust_boundary_and_shells_are_not_columns():
    with pytest.raises(ValueError):
        discovery.canonical('https://ict.cas.cn/admissions', 'https://iscas.cas.cn/')
    with pytest.raises(ValueError, match='活动公告'):
        discovery.inspect(b'<html><a href="/admissions">Admissions</a></html>', CHILD)
    with pytest.raises(ValueError, match='验证'):
        discovery.inspect('<title>安全验证</title>'.encode(), CHILD)


def test_network_rejects_private_dns_before_request(monkeypatch):
    session = MagicMock(); session.__enter__.return_value = session
    monkeypatch.setattr(discovery.requests, 'Session', lambda: session)
    monkeypatch.setattr(discovery.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('127.0.0.1', 443))])
    with pytest.raises(ValueError, match='非公网'):
        discovery.fetch_html(CHILD, PARENT)
    session.get.assert_not_called()


def test_research_link_is_preserved_but_search_navigation_is_excluded():
    raw = '<html><meta charset="utf-8"><a href="/research.html">科研实践</a><a href="/search.html">招生查询</a><a href="/find?search=summer">招生筛选</a><a href="/login">招生平台</a></html>'.encode()
    assert discovery.links(raw, PARENT) == [dict(url='https://cs.example.edu.cn/research.html', title='科研实践')]


def test_cross_institution_redirect_is_rejected_before_following(monkeypatch):
    session = MagicMock(); session.__enter__.return_value = session
    response = MagicMock(); response.__enter__.return_value = response
    response.status_code = 302; response.headers = {'Location': 'https://attacker.edu.cn/'}
    session.get.return_value = response
    monkeypatch.setattr(discovery.requests, 'Session', lambda: session)
    monkeypatch.setattr(discovery.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('8.8.8.8', 443))])
    with pytest.raises(ValueError, match='跨机构'):
        discovery.fetch_html(CHILD, PARENT)
    assert session.get.call_count == 1


def test_bks_camp_column_is_not_undergraduate_admissions():
    parent = 'https://ihep.cas.cn/edu/'
    raw = '<meta charset="utf-8"><a href="bks/xly/">大学生冬令营</a><a href="bkzs/">本科招生</a>'.encode()
    assert discovery.links(raw, parent) == [dict(url=parent + 'bks/xly/', title='大学生冬令营')]


def test_multiple_seeds_share_candidate_budget_and_progress_over_rounds(tmp_path):
    configs = [dict(url=f'https://cs.example.edu.cn/seed{i}/', school='example', dept='cs') for i in range(4)]
    calls = []
    def fetch(url, _):
        calls.append(url)
        if url in {c['url'] for c in configs}:
            return '<meta charset="utf-8"><a href="a">研究生招生</a><a href="b">通知公告</a>'.encode()
        return COLUMN
    first = discovery.run(tmp_path, configs=configs, fetcher=fetch, now=NOW, max_seeds=2, max_candidates=2)
    assert first['summary']['seeds_attempted'] == first['summary']['candidates_checked'] == 2
    assert first['summary']['due_seeds_deferred'] == 2
    second = discovery.run(tmp_path, configs=configs, fetcher=fetch, now=NOW + timedelta(minutes=1), max_seeds=2, max_candidates=2)
    assert len(second['seeds']) == 4 and len(second['candidates']) == 4
    third = discovery.run(tmp_path, configs=configs, fetcher=fetch, now=NOW + timedelta(minutes=2), max_seeds=2, max_candidates=2)
    assert len(third['candidates']) == 6
    assert all(calls.count(c['url'] + 'a') == 1 for c in configs)


def test_official_https_redirect_cannot_downgrade_transport(monkeypatch):
    session = MagicMock(); session.__enter__.return_value = session
    response = MagicMock(); response.__enter__.return_value = response
    response.status_code = 302; response.headers = {'Location': CHILD.replace('https:', 'http:')}
    session.get.return_value = response
    monkeypatch.setattr(discovery.requests, 'Session', lambda: session)
    monkeypatch.setattr(discovery.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('8.8.8.8', 443))])
    with pytest.raises(ValueError, match='降级'):
        discovery.fetch_html(CHILD, PARENT)
    assert session.get.call_count == 1


def test_camp_and_admissions_columns_precede_generic_notices(tmp_path):
    raw = '<meta charset="utf-8"><a href="a">通知公告</a><a href="b">研究生招生</a><a href="z">冬令营</a>'.encode()
    calls = []
    def fetch(url, _):
        calls.append(url)
        return raw if url == PARENT else COLUMN
    discovery.run(tmp_path, configs=[dict(url=PARENT, school='example', dept='cs')],
                  fetcher=fetch, now=NOW, max_seeds=1, max_candidates=1)
    assert calls == [PARENT, 'https://cs.example.edu.cn/z']


def test_redirect_hops_consume_external_request_budget(monkeypatch):
    session = MagicMock(); session.__enter__.return_value = session
    response = MagicMock(); response.__enter__.return_value = response
    response.status_code = 302; response.headers = {'Location': CHILD + '?moved=1'}
    session.get.return_value = response
    monkeypatch.setattr(discovery.requests, 'Session', lambda: session)
    monkeypatch.setattr(discovery.socket, 'getaddrinfo', lambda *a, **k: [(None, None, None, None, ('8.8.8.8', 443))])
    used = []
    def budget():
        if used:
            raise ValueError('budget exhausted')
        used.append(True)
    with pytest.raises(ValueError, match='budget exhausted'):
        discovery.fetch_html(CHILD, PARENT, before_request=budget)
    assert session.get.call_count == 1

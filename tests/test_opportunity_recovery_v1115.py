import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit, urlunsplit

import pytest
import yaml

from crawler import opportunity_recovery as recovery
from crawler import opportunity_review as review

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)
PARENT = 'https://cs.example.edu.cn/admissions/'
OLD = PARENT + 'old.html'
NEW = PARENT + 'new.html'
TITLE = '2027年计算机学院大学生冬令营报名通知'
RAW = ('<html><meta charset="utf-8"><title>' + TITLE + '</title><article><h1>' + TITLE + '</h1>'
       '<p>申请对象为2028届本科生，报名截止时间为2026年12月31日。</p>'
       '<p>申请材料为成绩单、个人简历、身份证复印件；联系邮箱camp@example.edu.cn。</p></article></html>').encode()


def fixture(root, old=RAW, item=None):
    (root / 'sites').mkdir()
    (root / 'cache/opportunity_evidence').mkdir(parents=True)
    configs = [dict(school='example', dept='cs', name='计算机学院', url=PARENT)]
    (root / 'sites/opportunities.yaml').write_text(yaml.safe_dump(dict(targets=configs)), encoding='utf-8')
    digest = hashlib.sha256(old).hexdigest()
    (root / 'cache/opportunity_evidence' / (digest + '.html')).write_bytes(old)
    draft = dict(id='stable-id', listing_url=PARENT, source_url=OLD,
                 item=item or dict(id='activity-stable-id', title=TITLE, school_id='example', dept_id='cs', unit='计算机学院', source_url=OLD),
                 fetch=dict(status='error', sha256=digest, error='HTTP 404'), quotes=[])
    queue_path = root / 'cache/opportunity_review.json'
    queue_path.write_text(json.dumps(dict(version=1, drafts=[draft])), encoding='utf-8')
    calls = []
    parent_raw = ('<html><meta charset="utf-8"><a href="new.html">' + TITLE + '</a></html>').encode()

    def fetch(url, _):
        calls.append(url)
        assert url != OLD, 'Recovery must never repeat the dead original URL'
        return parent_raw if url == PARENT else RAW
    return draft, queue_path, calls, fetch


def test_identical_official_article_reconnects_untouched_draft_without_publication(tmp_path):
    original, path, calls, fetch = fixture(tmp_path)
    result = recovery.run(tmp_path, fetcher=fetch, now=NOW)
    assert result['summary']['adopted'] == 1
    assert calls == [PARENT, NEW, PARENT, NEW]
    draft = review.read_queue(path)['drafts'][0]
    assert draft['id'] == original['id'] and draft['item']['id'] == original['item']['id']
    assert draft['source_url'] == draft['item']['source_url'] == NEW
    assert draft['fetch']['status'] == 'ok' and draft['suggestions']['graduation_year'] == 2028
    chain = draft['source_replacements'][0]
    assert chain['original_url'] == OLD and chain['new_url'] == NEW
    assert chain['old_sha'] == chain['new_sha'] == hashlib.sha256(RAW).hexdigest()
    assert chain['title'] == TITLE and chain['adopted_at'] == NOW.isoformat()
    assert set(draft['item']) == recovery.IDENTITY
    assert not (tmp_path / 'data/opportunities.json').exists()
    recovery.run(tmp_path, fetcher=fetch, now=NOW + timedelta(days=1))
    assert len(calls) == 4


@pytest.mark.parametrize('case', ['no_old_body', 'changed_deadline', 'published', 'quotes', 'manual', 'attachment', 'image'])
def test_manual_or_incomplete_evidence_never_changes_original(tmp_path, case):
    original, path, calls, fetch = fixture(tmp_path)
    raw = RAW
    if case == 'no_old_body':
        (tmp_path / 'cache/opportunity_evidence' / (original['fetch']['sha256'] + '.html')).unlink()
    elif case == 'changed_deadline':
        raw = RAW.replace(b'2026', b'2025')
    elif case == 'published':
        original['review'] = dict(reviewer='maintainer')
    elif case == 'quotes':
        original['quotes'] = ['verified quote']
    elif case == 'manual':
        original['item']['deadline'] = '2026-12-31'
    elif case == 'attachment':
        raw = RAW.replace(b'</article>', b'<a href="form.docx">form</a></article>')
    elif case == 'image':
        raw = RAW.replace(b'</article>', b'<img src="condition.png"></article>')
    path.write_text(json.dumps(dict(version=1, drafts=[original])), encoding='utf-8')
    before = path.read_bytes()
    result = recovery.run(tmp_path, fetcher=lambda url, parent: fetch(url, parent) if url == PARENT else raw, now=NOW)
    assert result['records']['stable-id']['status'] == 'manual_required'
    assert path.read_bytes() == before
    assert result['summary']['adopted'] == 0
    assert result['records']['stable-id']['candidates'][0]['original_url'] == OLD


def test_same_title_without_same_body_and_duplicate_urls_are_not_adopted(tmp_path):
    original, path, calls, fetch = fixture(tmp_path)
    other = copy.deepcopy(original); other.update(id='other', source_url=NEW, fetch=dict(status='ok'))
    path.write_text(json.dumps(dict(version=1, drafts=[original, other])), encoding='utf-8')
    before = path.read_bytes()
    result = recovery.run(tmp_path, fetcher=fetch, now=NOW)
    assert result['summary']['adopted'] == 0 and path.read_bytes() == before
    assert '已有独立草稿' in result['records']['stable-id']['errors'][0]['error']


@pytest.mark.parametrize('target', ['https://attacker.edu.cn/new.html', 'http://cs.example.edu.cn/new.html'])
def test_untrusted_or_insecure_links_never_fetched(tmp_path, target):
    original, path, calls, fetch = fixture(tmp_path)
    result = recovery.run(tmp_path, fetcher=lambda url, _: ('<meta charset="utf-8"><a href="' + target + '">' + TITLE + '</a>').encode(), now=NOW)
    assert result['summary']['requests'] == 1 and result['summary']['adopted'] == 0


def test_changed_parent_or_queue_aborts_atomic_adoption(tmp_path):
    original, path, calls, fetch = fixture(tmp_path)
    before = path.read_bytes()
    def changed_parent(url, parent):
        if len(calls) == 2:
            calls.append(url)
            return b'<html>removed</html>'
        return fetch(url, parent)
    result = recovery.run(tmp_path, fetcher=changed_parent, now=NOW)
    assert '父栏目链接' in result['records']['stable-id']['errors'][0]['error']
    assert path.read_bytes() == before


def test_concurrent_human_edit_is_preserved(tmp_path):
    original, path, calls, fetch = fixture(tmp_path)
    def edited(url, parent):
        if len(calls) == 3:
            original['notes'] = '人工处理中'
            path.write_text(json.dumps(dict(version=1, drafts=[original])), encoding='utf-8')
        return fetch(url, parent)
    result = recovery.run(tmp_path, fetcher=edited, now=NOW)
    assert result['summary']['adopted'] == 0
    saved = review.read_queue(path)['drafts'][0]
    assert saved['notes'] == '人工处理中' and saved['source_url'] == OLD
    assert '草稿在核验期间变化' in result['records']['stable-id']['errors'][0]['error']


def test_resolved_failures_leave_audit_but_not_active_backlog(tmp_path):
    original, path, calls, fetch = fixture(tmp_path)
    original['quotes'] = ['manual']
    path.write_text(json.dumps(dict(version=1, drafts=[original])), encoding='utf-8')
    assert recovery.run(tmp_path, fetcher=fetch, now=NOW)['summary']['manual_required'] == 1
    original['fetch']['status'] = 'ok'
    path.write_text(json.dumps(dict(version=1, drafts=[original])), encoding='utf-8')
    result = recovery.run(tmp_path, fetcher=fetch, now=NOW + timedelta(days=1))
    assert result['summary']['failed_drafts'] == result['summary']['manual_required'] == 0
    assert result['records']['stable-id']['active'] is False


def redirected_pages(monkeypatch, pages, redirects):
    """Exercise actual redirect validation/counting without a network service."""
    calls = []
    session = MagicMock()
    session.__enter__.return_value = session
    def get(url, **kwargs):
        calls.append(url)
        assert kwargs['allow_redirects'] is False
        parsed = urlsplit(url)
        base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
        hop = int(parse_qs(parsed.query).get('hop', ['0'])[0])
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 302 if hop < redirects else 200
        response.headers = {'Location': base + '?hop=' + str(hop + 1), 'Content-Type': 'text/html'}
        response.iter_content.return_value = [pages[base]]
        return response
    session.get.side_effect = get
    monkeypatch.setattr(recovery.discovery.requests, 'Session', lambda: session)
    monkeypatch.setattr(recovery.discovery.socket, 'getaddrinfo', lambda *args, **kwargs:
                        [(2, 1, 6, '', ('93.184.216.34', 443))])
    return calls


@pytest.mark.parametrize('redirects', [1, 3])
def test_default_budget_completes_official_redirects(tmp_path, monkeypatch, redirects):
    _, path, _, _ = fixture(tmp_path)
    parent = ('<meta charset="utf-8"><a href="' + NEW + '">' + TITLE + '</a>').encode()
    calls = redirected_pages(monkeypatch, {PARENT: parent, NEW: RAW}, redirects)
    result = recovery.run(tmp_path, now=NOW)
    assert result['summary']['request_budget'] == 16
    assert result['summary']['requests'] == len(calls) == 4 * (redirects + 1)
    assert result['summary']['adopted'] == 1 and result['summary']['budget_wait'] == 0
    assert review.read_queue(path)['drafts'][0]['source_url'] == NEW
    assert OLD not in calls


def test_prior_parent_budget_does_not_skip_unfinished_candidate(tmp_path, monkeypatch):
    _, path, _, _ = fixture(tmp_path)
    second = 'https://cs.example.edu.cn/news/'
    configs = [dict(school='example', dept='cs', url=url) for url in (PARENT, second)]
    (tmp_path / 'sites/opportunities.yaml').write_text(yaml.safe_dump(dict(targets=configs)), encoding='utf-8')
    parent = ('<meta charset="utf-8"><a href="' + NEW + '">' + TITLE + '</a>').encode()
    calls = redirected_pages(monkeypatch, {PARENT: b'<html></html>', second: parent, NEW: RAW}, 3)
    first = recovery.run(tmp_path, now=NOW)
    assert first['summary']['requests'] == len(calls) == 16
    assert first['summary']['budget_wait'] == 1 and first['summary']['unresolved'] == 0
    assert first['records']['stable-id']['status'] == 'budget_wait'
    assert first['records']['stable-id']['parent_cursor'] == 1
    assert review.read_queue(path)['drafts'][0]['source_url'] == OLD
    second_run = recovery.run(tmp_path, now=NOW + timedelta(days=1))
    assert calls[16] == second and PARENT not in calls[16:]
    assert second_run['summary']['requests'] == 16 and len(calls) == 32
    assert second_run['summary']['adopted'] == 1 and second_run['summary']['budget_wait'] == 0


def test_request_budget_preserves_unfinished_parent(tmp_path):
    original, path, calls, fetch = fixture(tmp_path)
    configs = [dict(school='example', dept='cs', url=PARENT), dict(school='example', dept='cs', url='https://cs.example.edu.cn/news/')]
    (tmp_path / 'sites/opportunities.yaml').write_text(yaml.safe_dump(dict(targets=configs)), encoding='utf-8')
    result = recovery.run(tmp_path, request_budget=1, fetcher=fetch, now=NOW)
    assert result['summary']['requests'] == 1 and result['summary']['adopted'] == 0
    assert result['summary']['budget_wait'] == 1 and result['records']['stable-id']['parent_cursor'] == 0
    next_calls = []
    recovery.run(tmp_path, request_budget=1, fetcher=lambda url, _: next_calls.append(url) or b'<html></html>', now=NOW + timedelta(days=1))
    assert next_calls == [PARENT]


def test_budget_exhausted_after_completed_parent_keeps_next_parent(tmp_path):
    fixture(tmp_path)
    second = 'https://cs.example.edu.cn/news/'
    configs = [dict(school='example', dept='cs', url=url) for url in (PARENT, second)]
    (tmp_path / 'sites/opportunities.yaml').write_text(yaml.safe_dump(dict(targets=configs)), encoding='utf-8')
    result = recovery.run(tmp_path, request_budget=1, fetcher=lambda *args: b'<html></html>', now=NOW)
    assert result['records']['stable-id']['status'] == 'budget_wait'
    assert result['records']['stable-id']['parent_cursor'] == 1


def test_navigation_only_error_is_classified_without_network(tmp_path):
    original, path, calls, fetch = fixture(tmp_path)
    original['item']['title'] = '夏令营'
    path.write_text(json.dumps(dict(version=1, drafts=[original])), encoding='utf-8')
    result = recovery.run(tmp_path, fetcher=fetch, now=NOW)
    assert result['summary']['not_announcement'] == 1 and calls == []


@pytest.mark.parametrize('title', ['夏令营', '冬令营', '夏令营报名', '科技创新实践课程', '科研实践'])
def test_navigation_headings_do_not_enter_announcement_monitor(title):
    from crawler.opportunity_monitor import activity_title
    assert not activity_title(title)

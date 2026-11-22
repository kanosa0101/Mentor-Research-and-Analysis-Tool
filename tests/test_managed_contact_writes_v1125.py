import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest
import yaml

from crawler import legacy_refresh, mentor_fields, mentor_quality, mentor_recovery, source_discovery, store
from scripts import crawl


URL = 'https://example.edu.cn/person'
HTML = '<h1>张甲</h1><p>邮箱：wrong@example.edu.cn</p>'
NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
HOOK = '''
def iter_roster(cfg):
    return [dict(name='张甲', url='https://example.edu.cn/person', email='wrong@example.edu.cn')], {'fetched_at': '2026-11-23'}

def parse_detail(cfg, html, url):
    return {'name': '张甲', 'title': '教授', 'email': 'wrong@example.edu.cn', '_rejected_email': 'right@example.edu.cn'}
'''
CONTACT = HOOK + '''
def parse_contact(cfg, person):
    url = person['detail_url']
    if cfg['scenario'] != 'uncaptured':
        cfg['_read_source'](url)
    result = {'_verified_roster_name': '另一个人' if cfg['scenario']=='wrong_name' else person['name'],
              '_field_sources': {'email': url}}
    if cfg['scenario'] == 'withdraw':
        result.update(_rejected_email='right@example.edu.cn', _contact_locator={'email': {
            'article_url': url, 'rejected_mailto': 'mailto:right@example.edu.cn',
            'visible_addresses': ['alternative@example.edu.cn', 'other@example.edu.cn']}})
    else:
        result['email'] = 'verified@example.edu.cn'
    return result
'''


def fixture(tmp_path, enabled, initial_email=True, hook=HOOK):
    cfg = dict(school='example', dept='cs', hook='contact_fixture', base_url='https://example.edu.cn',
               list={'urls': [URL]})
    if enabled:
        cfg['contact_hook_only'] = True
    site = tmp_path / 'sites/example'
    site.mkdir(parents=True)
    (site / 'cs.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')
    (site / 'contact_fixture.py').write_text(hook, encoding='utf-8')
    record = dict(name='张甲', slug='zhangjia', school='example', dept='cs', detail_url=URL)
    if initial_email:
        record.update(email='right@example.edu.cn', provenance={'email': {
            'origin': 'crawled', 'source': URL, 'fetched_at': '2026-11-22', 'confidence': 'auto'}})
    path = tmp_path / 'data/professors/example/cs/zhangjia.yaml'
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(record, allow_unicode=True), encoding='utf-8')
    return cfg, path, record


@pytest.mark.parametrize('entry', ['legacy', 'quality', 'field', 'crawl', 'roster'])
@pytest.mark.parametrize('enabled', [True, False])
def test_enabled_unit_only_writes_email_through_captured_contact_hook(tmp_path, monkeypatch, entry, enabled):
    initial = entry != 'roster'
    cfg, path, original = fixture(tmp_path, enabled, initial_email=initial)
    if entry == 'legacy':
        assert legacy_refresh.run(tmp_path, kind='professors', units=('example/cs',),
                                  fetcher=lambda source: HTML.encode(), now=NOW)['ok'] == 1
    elif entry == 'quality':
        issue = tmp_path / 'data/issues/example-cs.yaml'
        issue.parent.mkdir()
        issue.write_text(yaml.safe_dump([dict(kind='fetch_or_parse_error', ref='zhangjia', message='review',
                                             first_seen='2026-11-23', resolved=False)]), encoding='utf-8')
        assert mentor_quality.run(tmp_path, units=('example/cs',), fetcher=lambda source: HTML.encode(), now=NOW)['resolved'] == 1
    elif entry == 'field':
        # The ordinary vacancy path must ignore contact claims when there is no contact hook.
        orig = dict(original)
        orig.pop('email')
        orig.pop('provenance')
        path.write_text(yaml.safe_dump(orig, allow_unicode=True), encoding='utf-8')
        assert mentor_fields.run(tmp_path, units=('example/cs',), limit=1,
                                 fetcher=lambda source: HTML.encode(), now=NOW)['attempted'] == 1
    else:
        monkeypatch.setattr(store, 'DATA', tmp_path / 'data')
        monkeypatch.setattr(crawl.fetch, 'fetch_text', lambda *args, **kwargs: (HTML, {'fetched_at': '2026-11-23'}, True))
        hook = legacy_refresh.load_hook(tmp_path, cfg)
        if entry == 'crawl':
            assert crawl.phase_enrich(cfg, hook, False)['enriched'] == 1
        else:
            assert crawl.phase_roster(cfg, hook, False)['roster_total'] == 1
    after = yaml.safe_load(path.read_bytes())
    expected = (original.get('email') if entry != 'field' else None) if enabled else 'wrong@example.edu.cn'
    assert after.get('email') == expected
    if enabled and expected:
        assert after['provenance']['email'] == original['provenance']['email']
    if entry != 'roster':
        assert after['title'] == '教授'


@pytest.mark.parametrize('scenario', ['fill', 'correct', 'withdraw', 'occupied', 'wrong_name', 'uncaptured', 'manual', 'other_source'])
def test_managed_email_queue_uses_verified_capture_and_compare_and_swap(tmp_path, scenario):
    cfg, path, original = fixture(tmp_path, True, initial_email=scenario != 'fill', hook=CONTACT)
    cfg['scenario'] = scenario
    (tmp_path / 'sites/example/cs.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')
    if scenario == 'other_source':
        original['provenance']['email']['source'] = 'https://example.edu.cn/elsewhere'
    elif scenario == 'manual':
        original['provenance']['email']['origin'] = 'manual'
    elif scenario == 'occupied':
        second = tmp_path / 'data/professors/example/cs/second.yaml'
        second.write_text(yaml.safe_dump(dict(original, name='张乙', slug='second', email='verified@example.edu.cn'),
                                         allow_unicode=True), encoding='utf-8')
    path.write_text(yaml.safe_dump(original, allow_unicode=True), encoding='utf-8')

    def fetcher(source):
        assert source['url'] == URL
        return HTML.encode()

    now = NOW + timedelta(days=15)
    report = mentor_fields.run(tmp_path, units=('example/cs',), limit=4, fetcher=fetcher, now=now)
    row = yaml.safe_load(path.read_bytes())
    if scenario in ('fill', 'correct'):
        assert row['email'] == 'verified@example.edu.cn' and row['provenance']['email']['source'] == URL
    elif scenario == 'withdraw':
        assert 'email' not in row and 'email' not in row['provenance']
        status = mentor_fields.read(tmp_path)['records']['example/cs/zhangjia']['fields']['email']
        assert status['withdrawal']['sha256'] == sha256(HTML.encode()).hexdigest()
        assert status['withdrawal']['value'] == 'right@example.edu.cn'
        mentor_fields.seed(tmp_path, now + timedelta(days=1))
        status = mentor_fields.read(tmp_path)['records']['example/cs/zhangjia']['fields']['email']
        assert status['withdrawal']['previous_provenance']['source'] == URL
    else:
        assert row.get('email') == original['email'] and row['provenance']['email'] == original['provenance']['email']
    assert report['attempted'] > 0


@pytest.mark.parametrize('entry', ['legacy', 'crawl', 'field'])
def test_managed_unit_preserves_concurrent_profile_edit(tmp_path, monkeypatch, entry):
    cfg, path, original = fixture(tmp_path, True, hook=CONTACT)
    cfg['scenario'] = 'correct'
    (tmp_path / 'sites/example/cs.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')
    changed = dict(original, email='manual@example.edu.cn')
    changed['provenance']['email']['origin'] = 'manual'
    editor_bytes = yaml.safe_dump(changed, allow_unicode=True).encode()

    def fetcher(*args, **kwargs):
        path.write_bytes(editor_bytes)
        return HTML.encode() if entry != 'crawl' else (HTML, {'fetched_at': '2026-11-23'}, True)

    if entry == 'legacy':
        assert legacy_refresh.run(tmp_path, kind='professors', units=('example/cs',),
                                  fetcher=fetcher, now=NOW)['error'] == 1
    elif entry == 'crawl':
        monkeypatch.setattr(store, 'DATA', tmp_path / 'data')
        monkeypatch.setattr(crawl.fetch, 'fetch_text', fetcher)
        with pytest.raises(ValueError, match='记录已变化'):
            crawl.phase_enrich(cfg, legacy_refresh.load_hook(tmp_path, cfg), False)
    else:
        assert mentor_fields.run(tmp_path, units=('example/cs',), limit=1, fetcher=fetcher,
                                 now=NOW+timedelta(days=15))['attempted'] == 1
    assert path.read_bytes() == editor_bytes


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jPJoAAAAASUVORK5CYII=')
JLU_PNG = 'https://ccst.jlu.edu.cn/__local/3/6E/33/EE4F70B031E3A9FACD74492F740_AF2C4D44_D5.png?e=.png'


def test_contact_png_transport_has_exact_unit_path_and_captures_without_decoding(tmp_path):
    cfg = {'hook': 'jlu_cs', 'contact_hook_only': True}
    scope = 'https://ccst.jlu.edu.cn/info/1367/19096.htm'
    assert mentor_recovery.contact_allowed(JLU_PNG, scope, cfg)
    assert not mentor_recovery.contact_allowed(JLU_PNG, scope, {})
    assert not mentor_recovery.contact_allowed(JLU_PNG.replace('ccst.', 'www.'), scope, cfg)
    assert not mentor_recovery.contact_allowed(JLU_PNG + '&size=3', scope, cfg)
    sources = mentor_quality.Sources(tmp_path, lambda source: PNG, NOW.isoformat())
    assert sources.read(JLU_PNG, official_scope=scope, contact_cfg=cfg) == (PNG, '')
    assert sources.captured(sources.used[0]) == (PNG, '')
    corrupt = mentor_quality.Sources(tmp_path, lambda source: b'<html>challenge</html>', NOW.isoformat())
    with pytest.raises(ValueError, match='原始PNG'):
        corrupt.read(JLU_PNG, official_scope=scope, contact_cfg=cfg)


@pytest.mark.parametrize('case', ['valid', 'redirect', 'wrong_mime', 'large_dimensions', 'traversal_path'])
def test_contact_png_fetch_uses_one_bounded_official_request(monkeypatch, case):
    calls = []
    budget = []
    mock_response = type('Response', (), {})()
    mock_response.status_code = 302 if case == 'redirect' else 200
    mock_response.headers = {'Content-Type': 'text/html' if case == 'wrong_mime' else 'image/png',
                             'Location': JLU_PNG.replace('ccst.', 'www.')}
    mock_response.raise_for_status = lambda: None
    raw = PNG[:16] + (1025).to_bytes(4, 'big') + PNG[20:] if case == 'large_dimensions' else PNG
    mock_response.iter_content = lambda size: iter([raw])

    from contextlib import nullcontext

    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs['allow_redirects'] is False
            return nullcontext(mock_response)

    monkeypatch.setattr(source_discovery.requests, 'Session', Session)
    monkeypatch.setattr(source_discovery.socket, 'getaddrinfo', lambda *args, **kwargs: [(0, 0, 0, '', ('1.1.1.1', 443))])
    url = JLU_PNG.replace('/__local/', '/x/../__local/') if case == 'traversal_path' else JLU_PNG
    opts = dict(allow_contact_png=True, before_request=lambda: budget.append(1))
    if case == 'valid':
        assert source_discovery.fetch_html(url, 'https://ccst.jlu.edu.cn/', **opts) == PNG
    else:
        with pytest.raises(ValueError):
            source_discovery.fetch_html(url, 'https://ccst.jlu.edu.cn/', **opts)
    expected = 0 if case == 'traversal_path' else 1
    assert len(budget) == len(calls) == expected

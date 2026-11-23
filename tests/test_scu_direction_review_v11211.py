from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
from threading import Event
from types import SimpleNamespace

import pytest
import yaml

from crawler import legacy_refresh, mentor_direction_review as direction, mentor_fields, mentor_quality, quality_status, store
from crawler.model import Issue
from crawler.opportunity_monitor import OutputLockBusy, output_lock
from scripts import crawl
from sites.scu import scu_cs


ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path('data/professors/scu/cs/lihui.yaml')
ISSUES = Path('data/issues/scu-cs.yaml')
STATE = Path('cache/legacy_refresh/state.json')
KEY = 'professor/scu/cs/lihui.yaml'
URL = 'https://faculty.scu.edu.cn/lihui/zh_CN/index.htm'
T0 = datetime(2026, 11, 23, 1, tzinfo=timezone.utc)
OLD = '并行计算、分布式系统'
NEW = ('推荐系统', '数据挖掘')


def document(terms=NEW, *, name='李辉', path='lihui', extra=''):
    links = ''.join(f'<a href="/{path}/zh_CN/yjfx/12/content/{i}.htm">{term}</a>'
                    for i, term in enumerate(terms, 1))
    return (f'<title>四川大学主页平台管理系统 {name}--中文主页--首页</title>'
            f'<h2>{name}</h2><a href="/{path}/zh_CN/index.htm">首页</a>'
            f'<div class="teacher_tit">研究方向</div><div class="research_det">{links}</div>{extra}').encode()


@pytest.fixture
def live(tmp_path):
    cfg = Path('sites/scu/cs.yaml')
    hook = Path('sites/scu/scu_cs.py')
    (tmp_path / cfg).parent.mkdir(parents=True)
    for path in (cfg, hook):
        shutil.copyfile(ROOT / path, tmp_path / path)
    (tmp_path / PROFILE).parent.mkdir(parents=True)
    person = dict(school='scu', dept='cs', slug='lihui', name='李辉', detail_url=URL,
                  status='enriched', research_direction_raw=OLD,
                  provenance={direction.FIELD: dict(origin='crawled', source=URL,
                                                    confidence='auto', fetched_at='2026-11-22')})
    legacy_refresh.write_yaml(tmp_path / PROFILE, person)
    return tmp_path


def refresh(root, body, now, **metadata):
    calls = []

    def fetch(source):
        calls.append(source['url'])
        if isinstance(body, Exception):
            raise body
        if metadata.get('verified', True):
            source['_response_metadata'].update(dict(requested_url=URL, final_url=URL, status=200, redirected=False,
                                                      observed_utc=now.isoformat()) | metadata)
        return body

    result = legacy_refresh.run(root, units=(direction.UNIT,), kind='professors', limit=1, retry=True,
                                fetcher=fetch, now=now)
    assert calls == [URL]
    return result


def seed(root, now):
    def no_fetch(source):
        pytest.fail('Direction reviews must not fetch or spend the repair budget')

    return mentor_quality.run(root, units=(direction.UNIT,), limit=40, fetcher=no_fetch, now=now)


def issue(root):
    rows = yaml.safe_load((root / ISSUES).read_bytes())
    assert len(rows) == 1 and rows[0]['kind'] == direction.KIND
    Issue.model_validate(rows[0])
    return rows[0]


def save_issue(root, **updates):
    with output_lock(root / ISSUES):
        legacy_refresh.write_yaml(root / ISSUES, [dict(issue(root), **updates)])


def test_difference_only_is_observed_without_writing_profile(live):
    previous = (live / PROFILE).read_bytes()
    raw = document()
    report = refresh(live, raw, T0)
    assert (report['ok'], report['error'], report['results'][0]['checked_fields']) == (1, 0, [])
    assert (live / PROFILE).read_bytes() == previous
    queue = seed(live, T0)
    assert (queue['created'], queue['active'], queue['attempted']) == (1, 1, 0)
    record = issue(live)['automatic_check']
    observation = record['observation']
    assert record['pending_since'] == T0.isoformat() and record['next_action'] == 'manual_review'
    assert observation['registered'][direction.FIELD] == OLD and observation['proposal']['value'] == '、'.join(NEW)
    source = observation['source']
    assert source['sha256'] == hashlib.sha256(raw).hexdigest()
    assert (live / source['path']).read_bytes() == raw
    alert = next(row for row in quality_status.refresh(live, T0)['active'] if row['category'] == 'mentor')
    overdue = next(row for row in quality_status.refresh(live, T0 + timedelta(days=1))['active'] if row['category'] == 'mentor')
    assert alert['next_action'] == 'manual_review' and alert['priority'] == 2
    assert overdue['priority'] == 1 and overdue['fingerprint'] == alert['fingerprint']
    fields = mentor_fields.read(live)['records'][direction.UNIT + '/lihui']['fields']
    assert direction.FIELD not in fields


def test_same_candidate_dedup_human_close_new_value_and_restoration(live):
    def step(days, body):
        now = T0 + timedelta(days=days)
        refresh(live, body, now)
        seed(live, now)
        return issue(live)

    first = step(0, document())
    duplicate = step(1, document(extra='<!-- unrelated byte change -->'))
    assert first['review_history'] == duplicate['review_history'] == []
    assert first['automatic_check']['fingerprint'] == duplicate['automatic_check']['fingerprint']
    assert first['automatic_check']['pending_since'] == duplicate['automatic_check']['pending_since']
    assert first['automatic_check']['evidence'][0]['sha256'] != duplicate['automatic_check']['evidence'][0]['sha256']
    save_issue(live, reviewed=True, resolved=True, review_note='人工决定保留已登记值')
    still_closed = step(2, document(extra='<!-- another byte change -->'))
    assert still_closed['reviewed'] is True and still_closed['review_note'] == '人工决定保留已登记值'
    changed = step(3, document(('图学习',)))
    assert not changed['resolved'] and changed['automatic_check']['pending_since'] == (T0 + timedelta(days=3)).isoformat()
    assert changed['review_history'][0]['review_note'] == still_closed['review_note']
    changed_active = step(4, document(('图学习', '强化学习')))
    assert changed_active['automatic_check']['pending_since'] == changed['automatic_check']['pending_since']
    assert changed_active['review_history'][-1]['state'] == 'candidate_changed'
    old_cache = (live / STATE).read_bytes()
    restored = step(5, document(tuple(OLD.split('、'))))
    assert restored['resolved'] and restored['automatic_check']['resolution'] == 'source_restored'
    assert step(6, document(tuple(OLD.split('、')), extra='<!-- rechecked -->'))['resolved']
    (live / STATE).write_bytes(old_cache)
    seed(live, T0 + timedelta(days=7))
    assert issue(live)['resolved']
    assert not step(8, document(('图学习', '强化学习')))['resolved']


@pytest.mark.parametrize('human_closed', [True, False])
def test_same_candidate_after_source_restoration_keeps_human_decision(live, human_closed):
    def step(days, terms):
        now = T0 + timedelta(days=days)
        refresh(live, document(terms), now)
        seed(live, now)
        return issue(live)

    initial = step(0, NEW)
    if human_closed:
        save_issue(live, reviewed=True, resolved=True, review_note='人工决定保留登记方向')
    restored = step(1, tuple(OLD.split('、')))
    assert restored['resolved']
    repeated = step(2, NEW)
    assert repeated['automatic_check']['fingerprint'] == initial['automatic_check']['fingerprint']
    if human_closed:
        assert repeated['resolved'] and repeated['reviewed'] is True
        assert repeated['review_note'] == '人工决定保留登记方向'
        assert repeated['review_history'] == []
        changed = step(3, ('图学习',))
        assert not changed['resolved']
        assert changed['review_history'][-1]['review_note'] == repeated['review_note']
    else:
        assert restored['automatic_check']['resolution'] == 'source_restored'
        assert not repeated['resolved']
        assert repeated['review_history'][-1]['state'] == 'reopened'


def test_consistent_ordinals_are_display_only_and_raw_evidence_is_kept(live):
    first = refresh(live, document(), T0)['results'][0]['research_direction_observation']
    assert seed(live, T0)['created'] == 1
    active = issue(live)
    assert first['proposal']['entries'][0]['text'] == NEW[0]
    save_issue(live, reviewed=True, resolved=True, review_note='人工保留登记方向')
    second_time = T0 + timedelta(days=1)
    shown = tuple(f'[{i}]{text}' for i,text in enumerate(NEW, 1))
    second = refresh(live, document(shown), second_time)['results'][0]['research_direction_observation']
    assert second['proposal']['entries'][0]['text'] == shown[0]
    assert second['proposal']['value'] == '、'.join(shown)
    seed(live, second_time)
    kept = issue(live)
    assert kept['resolved'] and kept['review_note'] == '人工保留登记方向'
    assert kept['automatic_check']['fingerprint'] == active['automatic_check']['fingerprint']
    third_time = T0 + timedelta(days=2)
    refresh(live, document(('[3]'+NEW[0],shown[1])), third_time)
    seed(live, third_time)
    assert not issue(live)['resolved']


@pytest.mark.parametrize(('old','shown'), [
    (OLD, tuple(f'[{i}]{text}' for i,text in enumerate(OLD.split('、'), 1))),
    ('[1]并行计算、[2] 分布式系统', tuple(OLD.split('、'))),
])
def test_same_reference_with_different_ordinal_display_does_not_open_issue(live, old, shown):
    original = yaml.safe_load((live / PROFILE).read_bytes())
    legacy_refresh.write_yaml(live / PROFILE, dict(original, research_direction_raw=old))
    report = refresh(live, document(shown), T0)
    assert report['results'][0]['research_direction_observation']['proposal']['same']
    assert seed(live, T0)['created'] == 0


@pytest.mark.parametrize(('part','hidden'), [
    ('identity', 'hidden'),
    ('identity', 'aria-hidden="TRUE"'),
    ('research', 'style="display: None !important"'),
    ('research', 'style="height: 2px; VISIBILITY: hidden;"'),
])
def test_hidden_identity_or_research_never_opens_or_resolves(live, part, hidden):
    original = yaml.safe_load((live / PROFILE).read_bytes())
    original['title'] = '教授'
    original['provenance']['title'] = dict(original['provenance'][direction.FIELD])
    legacy_refresh.write_yaml(live / PROFILE, original)
    unchanged_title = '<div class="bs"><p>职务：教授</p></div>'

    def hidden_page(terms):
        html = document(terms, extra=unchanged_title).decode()
        if part == 'identity':
            return html.replace('<h2>李辉</h2>',f'<div {hidden}><h2>李辉</h2></div>').encode()
        start = html.index('<div class="teacher_tit">')
        end = html.index(unchanged_title)
        return (html[:start] + f'<div {hidden}>' + html[start:end] + '</div>' + html[end:]).encode()

    refresh(live, hidden_page(NEW), T0)
    assert seed(live, T0)['created'] == 0
    active_time = T0 + timedelta(days=1)
    refresh(live, document(extra=unchanged_title), active_time)
    seed(live, active_time)
    active = issue(live)
    restored_time = T0 + timedelta(days=2)
    refresh(live, hidden_page(tuple(OLD.split('、'))), restored_time)
    seed(live, restored_time)
    assert issue(live) == active


@pytest.mark.parametrize('variant', ['manual', 'manual_value', 'verified', 'other_source', 'wrong_teacher', 'empty', 'placeholder', 'cross_heading',
                                     'redirected', 'no_metadata', 'failed', 'missing_body', 'bad_body', 'forged_value'])
def test_only_original_same_person_verified_source_can_create_issue(live, variant):
    raw, metadata = document(), {}
    if variant in {'manual', 'manual_value', 'verified', 'other_source'}:
        person = yaml.safe_load((live / PROFILE).read_bytes())
        proof = person['provenance'][direction.FIELD]
        if variant in {'manual', 'manual_value'}:
            proof['origin'] = 'manual'
            if variant == 'manual':
                person[direction.FIELD] = None
        elif variant == 'verified':
            proof['confidence'] = 'verified'
        else:
            proof['source'] = 'https://faculty.scu.edu.cn/lihui/other.htm'
        legacy_refresh.write_yaml(live / PROFILE, person)
    elif variant == 'wrong_teacher':
        raw = document(path='lihuixiao')
    elif variant == 'empty':
        raw = document(())
    elif variant == 'placeholder':
        raw = document(('[1]推荐系统', '[2]暂无内容'))
    elif variant == 'cross_heading':
        raw = document().replace(b'</div><div class="research_det">', '</div><h2>个人简介</h2><div class="research_det">'.encode())
    elif variant == 'redirected':
        metadata = {'redirected': True, 'final_url': URL.replace('lihui', 'lihuixiao')}
    elif variant == 'no_metadata':
        metadata = {'verified': False}
    elif variant == 'failed':
        raw = TimeoutError('controlled failed capture')
    refresh(live, raw, T0, **metadata)
    cached = json.loads((live / STATE).read_bytes())['records'][KEY]
    if variant in {'missing_body', 'bad_body', 'forged_value'}:
        source = cached['research_direction_observation']['source']
        if variant == 'missing_body':
            (live / source['path']).unlink()
        elif variant == 'bad_body':
            (live / source['path']).write_bytes(document(('游戏开发',)))
        else:
            cached['research_direction_observation']['proposal']['value'] = '伪造方向'
        (live / STATE).write_text(json.dumps({'version': 1, 'records': {KEY: cached}}), encoding='utf-8')
    now = T0 + timedelta(seconds=1)
    # A genuine parse or transport error keeps its ordinary issue type and budget.
    mentor_quality.run(live, units=(direction.UNIT,), limit=0, now=now)
    if (live / ISSUES).is_file():
        rows = yaml.safe_load((live / ISSUES).read_bytes())
        assert all(row['kind'] != direction.KIND for row in rows)
        if variant == 'failed':
            assert [row['kind'] for row in rows] == ['fetch_or_parse_error']


@pytest.mark.parametrize('previous', [None, '[1]、推荐系统、[2]、数据挖掘'])
def test_empty_still_fills_and_numbered_same_value_is_same(live, previous):
    person = yaml.safe_load((live / PROFILE).read_bytes())
    person[direction.FIELD] = previous
    legacy_refresh.write_yaml(live / PROFILE, person)
    raw = document(('[1]推荐系统', '[2]数据挖掘'))
    assert refresh(live, raw, T0)['ok'] == 1 and seed(live, T0)['created'] == 0
    current = yaml.safe_load((live / PROFILE).read_bytes())
    assert current[direction.FIELD] == (previous or '[1]推荐系统、[2]数据挖掘')


def test_profile_write_race_and_manually_changed_registration(live, monkeypatch):
    refresh(live, document(), T0)
    before = (live / PROFILE).read_bytes()
    verify = direction._record_verified

    def changed(*args, **kwargs):
        result = verify(*args, **kwargs)
        (live / PROFILE).write_bytes(before + b'\n')
        return result

    with monkeypatch.context() as patch:
        patch.setattr(direction, '_record_verified', changed)
        assert seed(live, T0)['active'] == 0
    assert seed(live, T0)['created'] == 1
    person = yaml.safe_load(before)
    person[direction.FIELD] = '人工复核的登记方向'
    with output_lock(live / PROFILE):
        legacy_refresh.write_yaml(live / PROFILE, person)
    assert seed(live, T0 + timedelta(minutes=1))['active'] == 0
    assert issue(live)['automatic_check']['resolution'] == 'registration_changed'


def test_path_absence_is_distinguished_from_bad_profile_read(live):
    refresh(live, document(), T0)
    assert seed(live, T0)['created'] == 1
    (live / PROFILE).write_text('[malformed YAML', encoding='utf-8')
    assert seed(live, T0)['active'] == 1
    (live / PROFILE).unlink()
    assert seed(live, T0 + timedelta(minutes=1))['active'] == 0
    assert issue(live)['automatic_check']['status'] == 'retired'


def test_concurrent_quality_seed_does_not_duplicate_issue(live, monkeypatch):
    refresh(live, document(), T0)
    entered, proceed = Event(), Event()
    original = direction._record_verified

    def block(*args):
        entered.set()
        assert proceed.wait(5)
        return original(*args)

    monkeypatch.setattr(direction, '_record_verified', block)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(seed, live, T0)
        try:
            assert entered.wait(5)
            with pytest.raises(OutputLockBusy):
                seed(live, T0)
        finally:
            proceed.set()
        assert first.result()['created'] == 1
    assert seed(live, T0)['created'] == 0 and not issue(live)['review_history']


def test_quality_does_not_use_old_capture_while_legacy_is_updating(live):
    refresh(live, document(), T0)
    with output_lock(live / STATE):
        assert seed(live, T0)['created'] == 0
    assert seed(live, T0)['created'] == 1


def test_cli_stale_issue_snapshot_keeps_current_research_review_only(live, monkeypatch):
    refresh(live, document(), T0)
    seed(live, T0)
    initial = issue(live)
    old_error = dict(kind='fetch_or_parse_error', ref='lihui', message='读取失败', first_seen='2026-11-22', resolved=False)
    legacy_refresh.write_yaml(live / ISSUES, [initial, old_error])
    monkeypatch.setattr(store, 'DATA', live / 'data')
    cfg = yaml.safe_load((live / 'sites/scu/cs.yaml').read_bytes())

    def fetch(_method, url, **kwargs):
        assert url == URL
        with output_lock(live / ISSUES):
            legacy_refresh.write_yaml(live / ISSUES, [dict(initial, reviewed=True, resolved=True,
                                                         review_note='抓取期间的人工决定'), old_error])
        return document().decode(), {'fetched_at': '2026-11-23'}, False

    monkeypatch.setattr(crawl.fetch, 'fetch_text', fetch)
    assert crawl.phase_enrich(cfg, scu_cs, True)['enriched'] == 1
    rows = {row['kind']: row for row in yaml.safe_load((live / ISSUES).read_bytes())}
    assert rows[direction.KIND]['review_note'] == '抓取期间的人工决定'
    assert rows[direction.KIND]['reviewed'] is rows[direction.KIND]['resolved'] is True
    assert rows['fetch_or_parse_error']['resolved'] is True
    person = yaml.safe_load((live / PROFILE).read_bytes())
    assert person[direction.FIELD] == OLD and '_research_direction_observation' not in person


def test_native_response_metadata_is_obtained_without_a_second_request(monkeypatch):
    requests = []
    raw = document()
    response = SimpleNamespace(url=URL, status_code=200, history=[], content=raw, raise_for_status=lambda: None)

    def request(_session, method, url, **kwargs):
        requests.append((method, url))
        return response

    monkeypatch.setattr(legacy_refresh.requests.Session, 'request', request)
    request_data = {'url': URL, '_response_metadata': {}}
    assert legacy_refresh.fetch_source(request_data) == raw
    assert requests == [('GET', URL)] and request_data['_response_metadata']['final_url'] == URL

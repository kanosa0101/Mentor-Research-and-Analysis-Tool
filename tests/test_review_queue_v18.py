import copy
import hashlib
from datetime import datetime, timedelta, timezone

from crawler import opportunity_review as review, review_queue

NOW = datetime(2026, 11, 15, 8, tzinfo=timezone.utc)


def draft(root, text='2027年冬令营面向本科生报名，请按公告准备申请材料。'):
    raw = ('<html><meta charset="utf-8"><article><p>' + text + '</p></article></html>').encode()
    queue = root / 'cache/opportunity_review.json'
    url = 'https://cs.example.edu.cn/camp.html'
    monitoring = {'candidates': [dict(url=url, source='https://cs.example.edu.cn/list.html', school='example', dept='cs',
        unit='计算机学院', title='2027年冬令营', first_seen=(NOW - timedelta(hours=30)).isoformat(), last_seen=NOW.isoformat())]}
    value = review.sync(monitoring, queue, [{'url': monitoring['candidates'][0]['source']}], fetcher=lambda _: raw, now=NOW, refresh=True)
    return value['drafts'][0]


def test_urgent_deadline_requires_current_hashed_official_evidence(tmp_path):
    d = draft(tmp_path, '冬令营面向本科生，申请报名截止2026年11月17日，请准备材料。')
    row = review_queue.evaluate(d, NOW, tmp_path)
    assert row['priority'] == 0 and row['deadline_verified'] and row['sla_hours'] == 2
    d['item']['deadline'] = '2026-11-16'
    row = review_queue.evaluate(d, NOW, tmp_path)
    assert row['priority'] == 2 and not row['deadline_verified']
    d['item']['deadline'] = ''
    (tmp_path / 'cache/opportunity_evidence' / (d['fetch']['sha256'] + '.html')).write_bytes(b'changed')
    assert not review_queue.evaluate(d, NOW, tmp_path)['deadline_verified']


def test_activity_year_is_not_graduation_year_but_explicit_cohort_is_prioritized(tmp_path):
    d = draft(tmp_path, '2028年冬令营欢迎本科生申请，具体材料要求请查看本公告。')
    d['suggestions']['graduation_year'] = 2028
    assert review_queue.evaluate(d, NOW, tmp_path)['priority'] == 2
    explicit = draft(tmp_path, '2027年冬令营面向2028届本科毕业生，具体申请材料要求请查看本公告。')
    assert review_queue.evaluate(explicit, NOW, tmp_path)['priority'] == 1


def test_historical_and_expired_items_do_not_compete_with_current_work(tmp_path):
    d = draft(tmp_path, '面向2028届本科毕业生，冬令营报名截止2026年11月12日，请准备申请材料。')
    assert review_queue.evaluate(d, NOW, tmp_path)['priority'] == 3
    d['triage'] = {'classification': 'historical', 'source_sha256': d['fetch']['sha256']}
    assert review_queue.evaluate(d, NOW, tmp_path)['priority'] == 4
    d['fetch']['sha256'] = 'a' * 64
    assert review_queue.evaluate(d, NOW, tmp_path)['priority'] != 4


def test_overdue_events_persist_dedupe_resolve_and_reopen(tmp_path):
    d = draft(tmp_path)
    queue = dict(version=1, drafts=[d])
    before = copy.deepcopy(queue)
    first = review_queue.refresh_alerts(tmp_path, queue, NOW)
    assert first['summary']['overdue'] == 1
    assert [e['kind'] for e in first['events']] == ['overdue']
    again = review_queue.refresh_alerts(tmp_path, queue, NOW + timedelta(hours=1))
    assert again['events'] == first['events']
    assert queue == before
    d['triage'] = dict(classification='historical', source_sha256=d['fetch']['sha256'])
    resolved = review_queue.refresh_alerts(tmp_path, queue, NOW + timedelta(hours=2))
    assert not resolved['active'] and resolved['events'][-1]['kind'] == 'resolved'
    d.pop('triage'); d['fetch']['content_sha256'] = 'b' * 64
    d['fetch']['checked_at'] = (NOW + timedelta(hours=3)).isoformat()
    reopened = review_queue.refresh_alerts(tmp_path, queue, NOW + timedelta(hours=3))
    assert reopened['events'][-1]['kind'] == 'reopened'
    assert reopened['active'][0]['opened_at'] == d['fetch']['checked_at']
    assert not reopened['active'][0]['overdue']
    # UI read-only evaluation uses the persistent reopen time, not first-ever discovery.
    assert review_queue.evaluate(d, NOW + timedelta(hours=4), tmp_path)['opened_at'] == d['fetch']['checked_at']
    repeated = review_queue.refresh_alerts(tmp_path, queue, NOW + timedelta(hours=28))
    assert repeated['events'][-1]['kind'] == 'overdue'
    assert len({e['id'] for e in repeated['events']}) == len(repeated['events'])


def test_source_errors_and_expired_verification_are_actionable(tmp_path):
    d = draft(tmp_path)
    d['fetch']['status'] = 'error'
    assert review_queue.evaluate(d, NOW, tmp_path)['priority'] == 1
    d['fetch']['status'] = 'ok'; d['item']['verified_at'] = '2026-10-01'
    d['review'] = dict(source_sha256=d['fetch']['sha256'], content_sha256=d['fetch']['content_sha256'],
                      item_sha256=review.item_hash(d['item']), quotes=d['quotes'], field_evidence={})
    row = review_queue.evaluate(d, NOW, tmp_path)
    assert row['state'] == 'verification_due' and row['priority'] == 1
    assert row['overdue']


def test_missing_from_queue_resolves_alert_without_mutating_draft(tmp_path):
    d = draft(tmp_path)
    review_queue.refresh_alerts(tmp_path, dict(drafts=[d]), NOW)
    result = review_queue.refresh_alerts(tmp_path, dict(drafts=[]), NOW + timedelta(hours=1))
    assert result['events'][-1]['kind'] == 'resolved'
    assert not result['active']

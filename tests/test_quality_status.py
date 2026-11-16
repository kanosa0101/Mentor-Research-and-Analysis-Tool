import json
from datetime import datetime, timedelta, timezone

from crawler.quality_status import refresh


NOW = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)


def save(root, path, value):
    path = root / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def test_retry_keeps_sla_and_delivery_fingerprint_and_resolution_removes_alert(tmp_path):
    record = dict(title='政策', status='retry', pending_since=(NOW-timedelta(hours=25)).isoformat(),
                  next_attempt=(NOW+timedelta(hours=2)).isoformat(), last_attempt=NOW.isoformat(),
                  reasons=[{'kind':'source_error','message':'官方来源暂不可读'}])
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {'p':record}})
    first = refresh(tmp_path, NOW)
    assert first['summary'] == {'active':1,'overdue':1,'policies':1,'new_policies':0,'mentors':0,'mentor_field_gaps':0,'missing_fields':0}
    record['last_attempt'] = (NOW+timedelta(hours=2)).isoformat()
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {'p':record}})
    second = refresh(tmp_path, NOW+timedelta(hours=2))
    assert first['active'][0]['fingerprint'] == second['active'][0]['fingerprint']
    assert first['active'][0]['due_at'] == second['active'][0]['due_at']
    record['status'] = 'confirmed'
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {'p':record}})
    assert refresh(tmp_path, NOW)['active'] == []
    record.update(status='retry',pending_since=(NOW+timedelta(days=1)).isoformat())
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {'p':record}})
    reopened = refresh(tmp_path, NOW+timedelta(days=1))['active'][0]
    assert reopened['fingerprint'] != first['active'][0]['fingerprint']
    assert not reopened['overdue']


def test_mentor_backlog_and_missing_or_corrupt_state_are_not_silently_healthy(tmp_path):
    assert refresh(tmp_path, NOW)['available'] == {'policy':False,'mentor':False,'policy_intake':False,'mentor_fields':False}
    save(tmp_path,'cache/mentor_quality/state.json',{'records':{
        'unit/error/person':dict(status='pending',title='导师详情',reason='正文空白',
            pending_since=(NOW-timedelta(hours=3)).isoformat(),next_check_at=NOW.isoformat()),
        'unit/closed/person':dict(status='resolved',next_check_at=(NOW+timedelta(days=7)).isoformat())}})
    value = refresh(tmp_path,NOW)
    assert value['summary']['mentors'] == 1 and value['summary']['overdue'] == 0
    assert value['active'][0]['reasons'] == ['正文空白']
    save(tmp_path,'cache/policy_revalidation/state.json',{'policies':[]})
    assert refresh(tmp_path,NOW)['failures'] == {'policy':'ValueError','policy_intake':'MissingState','mentor_fields':'MissingState'}


def test_missing_states_are_unknown_but_initialized_empty_states_are_healthy(tmp_path):
    value = refresh(tmp_path, NOW)
    assert value['failures'] == {'policy': 'MissingState', 'mentor': 'MissingState', 'policy_intake':'MissingState','mentor_fields':'MissingState'}
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {}})
    save(tmp_path, 'cache/mentor_quality/state.json', {'records': {}})
    save(tmp_path, 'cache/policy_intake/state.json', {'records': {}})
    save(tmp_path, 'cache/mentor_quality/field-gaps.json', {'records': {}})
    value = refresh(tmp_path, NOW)
    assert all(value['available'].values()) and not value['failures'] and not value['incomplete']
    assert value['active'] == []


def test_missed_confirmed_and_resolved_rechecks_have_two_hour_scheduler_grace(tmp_path):
    scheduled = (NOW - timedelta(hours=1)).isoformat()
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {
        'p': dict(status='confirmed', next_attempt=scheduled)}})
    save(tmp_path, 'cache/mentor_quality/state.json', {'records': {
        'm': dict(status='resolved', next_check_at=scheduled)}})
    assert refresh(tmp_path, NOW)['active'] == []
    value = refresh(tmp_path, NOW + timedelta(hours=2))
    assert value['summary']['overdue'] == 2 and not value['incomplete']
    assert all(r['status'] == 'maintenance_overdue' and r['opened_at'] is None for r in value['active'])
    assert all(r['due_at'] == (NOW + timedelta(hours=1)).isoformat() for r in value['active'])
    repeated = refresh(tmp_path, NOW + timedelta(hours=3))
    assert [r['fingerprint'] for r in repeated['active']] == [r['fingerprint'] for r in value['active']]


def test_missing_pending_clock_or_recheck_schedule_is_unknown_not_fabricated_overdue(tmp_path):
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {
        'no-clock': dict(status='retry', last_attempt=(NOW-timedelta(days=7)).isoformat()),
        'bad-clock': dict(status='review_required', pending_since='yesterday'),
        'future-clock': dict(status='retry', pending_since=(NOW+timedelta(days=7)).isoformat()),
        'no-schedule': dict(status='confirmed')}})
    save(tmp_path, 'cache/mentor_quality/state.json', {'records': {}})
    save(tmp_path, 'cache/policy_intake/state.json', {'records': {}})
    value = refresh(tmp_path, NOW)
    assert len(value['incomplete']) == 4 and value['summary']['overdue'] == 0
    assert all(r['status'] == 'unknown' and r['opened_at'] is None and r['due_at'] is None for r in value['active'])


def test_reason_groups_include_unattempted_backlog_without_claiming_evidence(tmp_path):
    save(tmp_path, 'cache/policy_revalidation/state.json', {'policies': {}})
    save(tmp_path, 'cache/mentor_quality/state.json', {'records': {
        'm': dict(status='pending', reason_code='http_not_found', category_label='旧页面不存在',
                  next_action='discover_official_source', action_label='发现替代官方来源',
                  pending_since=(NOW-timedelta(hours=26)).isoformat(),
                  source_urls={'profile': 'https://example.edu.cn/old.htm'})}})
    first = refresh(tmp_path, NOW)
    assert first['breakdown'] == {'reasons': {'http_not_found': 1},
                                 'actions': {'discover_official_source': 1}, 'never_attempted': 1}
    row = first['active'][0]
    assert row['overdue'] and row['last_attempt_at'] is None and row['replacement'] is None
    assert row['action_label'] == '发现替代官方来源'
    assert refresh(tmp_path, NOW+timedelta(hours=2))['active'][0]['fingerprint'] == row['fingerprint']

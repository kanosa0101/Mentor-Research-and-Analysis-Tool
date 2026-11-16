import copy
from datetime import timedelta

import pytest
import requests
import yaml

from crawler import automatic_review as automatic, opportunity_recovery as recovery, opportunity_review as review
from crawler import review_preflight as preflight, review_queue
from test_review_preflight_v1116 import CONFIGS, CURRENT, NOW, PAST, fixture
from test_review_preflight_v1116 import html


@pytest.mark.parametrize('legacy', [False, True])
def test_historical_incomplete_evidence_is_archived_without_ai_or_url_repair(tmp_path, legacy):
    raw = PAST.replace(b'</article>', b'<img src="requirements.png"></article>')
    path, draft = fixture(tmp_path, raw)
    assert review.fetch_evidence(draft, path, lambda _: raw, now=NOW, complete=True) is None
    assert draft['fetch']['status'] == 'evidence_error'
    if legacy:
        draft['fetch']['status'] = 'error'
    review.atomic_json(path, {'version': 1, 'drafts': [draft]})
    before = copy.deepcopy(draft)
    result = automatic.run(tmp_path, path, CONFIGS, now=NOW,
        fetcher=lambda _: pytest.fail('fresh historical source fetched'),
        checker=lambda *a: pytest.fail('historical AI'), assistant=lambda *a: pytest.fail('historical assistance'))
    stored = review.read_queue(path)['drafts'][0]
    assert review.triage(stored)['classification'] == 'historical'
    assert stored['item'] == before['item'] and stored['first_seen'] == before['first_seen']
    assert result['counts'] == {'skipped': 1}
    (tmp_path/'sites').mkdir()
    (tmp_path/'sites/opportunities.yaml').write_text(yaml.safe_dump({'targets': CONFIGS}), encoding='utf-8')
    report = recovery.run(tmp_path, now=NOW,
        fetcher=lambda *a: pytest.fail('evidence error entered URL repair'))
    assert report['summary']['attempted'] == 0


def test_fresh_historical_body_is_triaged_even_when_attachment_collection_fails(tmp_path):
    path, draft = fixture(tmp_path)
    raw = PAST.replace(b'</article>', b'<img src="requirements.png"></article>')
    result = automatic.process(tmp_path, path, draft, CONFIGS, now=NOW, publish=False,
        fetcher=lambda _: raw, checker=lambda *a: pytest.fail('historical AI'))
    stored = review.read_queue(path)['drafts'][0]
    assert result['state'] == 'skipped'
    assert stored['fetch']['status'] == 'evidence_error'
    assert review.triage(stored)['classification'] == 'historical'


def test_current_images_stay_in_evidence_queue_with_actual_cohort_priority(tmp_path):
    path, draft = fixture(tmp_path, CURRENT, '2027年计算机冬令营报名通知')
    raw = CURRENT.replace(b'</article>', b'<img src="requirements.png"></article>')
    result = automatic.process(tmp_path, path, draft, CONFIGS, now=NOW, publish=False,
        fetcher=lambda _: raw, checker=lambda *a: pytest.fail('incomplete evidence reached AI'))
    stored = review.read_queue(path)['drafts'][0]
    assert result['state'] == 'manual_required' and result['error_phase'] == 'source_evidence'
    assert review.status(stored) == 'needs_evidence_review'
    assert preflight.effective(stored)['priority_hint'] == 'target_cohort'
    assert review_queue.evaluate(stored, NOW, tmp_path)['current_cycle_priority']
    assert not (tmp_path/'data/opportunities.json').exists()


def test_attachment_timeout_retries_evidence_without_invalidating_html(tmp_path, monkeypatch):
    path, draft = fixture(tmp_path, CURRENT, '2027年计算机冬令营报名通知')
    from crawler import automatic_evidence
    def failed(*args, **kwargs):
        raise requests.ReadTimeout('fixture attachment timeout')
    monkeypatch.setattr(automatic_evidence, 'collect', failed)
    result = automatic.process(tmp_path, path, draft, CONFIGS, now=NOW, publish=False,
        fetcher=lambda _: CURRENT, checker=lambda *a: pytest.fail('incomplete evidence reached AI'))
    stored = review.read_queue(path)['drafts'][0]
    assert result['state'] == 'retry' and result['retryable']
    assert result['error_phase'] == 'source_evidence'
    assert review.evidence_error(stored['fetch']) and not review.source_error(stored['fetch'])
    assert stored['fetch']['html_fetched_at'] == NOW.isoformat(timespec='seconds')


def test_transport_failure_with_old_bytes_cannot_archive(tmp_path):
    path, draft = fixture(tmp_path)
    def failed(_):
        raise requests.ReadTimeout('fixture')
    review.fetch_evidence(draft, path, failed, now=NOW, complete=True)
    assert review.source_error(draft['fetch'])
    assert preflight.classify(tmp_path, draft, CONFIGS, now=NOW)['classification'] == 'unknown'


def test_old_image_only_notice_is_lower_priority_without_claiming_historical_verification(tmp_path):
    title = '2024年优秀大学生夏令营报名通知'
    raw = html(title, '<p>发布时间：2024年06月17日</p><img src="all-requirements.png">')
    path, draft = fixture(tmp_path, raw, title)
    review.fetch_evidence(draft, path, lambda _: raw, now=NOW, complete=True)
    draft['preflight'] = preflight.classify(tmp_path, draft, CONFIGS, now=NOW)
    assert draft['preflight']['classification'] == 'unknown'
    assert draft['preflight']['priority_hint'] == 'past_activity_evidence'
    row = review_queue.evaluate(draft, NOW, tmp_path)
    assert row['priority'] == 3 and not row['current_cycle_priority']


def test_evidence_state_correction_keeps_sla_generation_and_waiting_clock(tmp_path):
    path, draft = fixture(tmp_path, CURRENT)
    draft['first_seen'] = (NOW-timedelta(days=3)).isoformat()
    draft['fetch'].update(status='error')
    queue = {'version': 1, 'drafts': [draft]}
    original = review_queue.refresh_alerts(tmp_path, queue, NOW)
    draft['fetch']['error_kind'] = 'evidence'
    corrected = review_queue.refresh_alerts(tmp_path, queue, NOW+timedelta(hours=1))
    assert corrected['active'][0]['state'] == 'needs_evidence_review'
    assert corrected['active'][0]['opened_at'] == original['active'][0]['opened_at']
    assert corrected['records'][draft['id']]['generation'] == original['records'][draft['id']]['generation']
    assert corrected['events'] == original['events']

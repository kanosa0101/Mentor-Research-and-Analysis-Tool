import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import run_review_pipeline as pipeline


@pytest.fixture
def phases(monkeypatch):
    mocks = {}
    for name, module, function, value in (
        ('discovery', pipeline.source_discovery, 'run', {'summary': {}}),
        ('recovery', pipeline.opportunity_recovery, 'run', {'summary': {}}),
        ('automatic', pipeline.automatic_review, 'run', {'counts': {}}),
        ('alerts', pipeline.review_queue, 'refresh_alerts', {'active': [], 'summary': {}}),
        ('quality', pipeline.quality_status, 'refresh', {'available': {'policy': True, 'mentor': True}, 'active': [], 'summary': {}}),
        ('notifications', pipeline.maintenance_push, 'dispatch', {'sent': 0}),
        ('metrics', pipeline, 'summarize', {'status': 'ok'}),
        ('build', pipeline, 'rebuild', {'published': True}),
    ):
        mocks[name] = Mock(return_value=value)
        monkeypatch.setattr(module, function, mocks[name])
    return mocks


def catalog(root, text='{"opportunities": []}'):
    path = root / 'data/opportunities.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding='utf8')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_independent_failures_still_refresh_alerts_and_redact_credentials(tmp_path, phases):
    secret = 'fixture-key-must-never-appear-in-pipeline-state'
    phases['discovery'].side_effect = RuntimeError('Authorization: Bearer ' + secret)
    phases['automatic'].side_effect = ValueError('request headers contain ' + secret)
    result = pipeline.run(tmp_path, publish=True, discover=True)
    assert result['status'] == 'partial'
    assert result['failures'] == {'discovery': 'RuntimeError', 'automatic': 'ValueError'}
    phases['alerts'].assert_called_once_with(tmp_path)
    phases['notifications'].assert_called_once_with(tmp_path, result['alerts'])
    phases['metrics'].assert_called_once_with(tmp_path)
    assert secret not in (tmp_path / 'cache/review-pipeline.json').read_text(encoding='utf8')


def test_assess_mode_never_sends_or_rebuilds_even_when_catalog_changed(tmp_path, phases):
    catalog(tmp_path)
    result = pipeline.run(tmp_path, publish=False)
    phases['automatic'].assert_called_once_with(tmp_path, limit=2, publish=False)
    phases['notifications'].assert_not_called()
    phases['build'].assert_not_called()
    phases['discovery'].assert_not_called()
    assert result['mode'] == 'assess' and result['built_catalog_sha256'] is None


def test_discovery_admits_only_in_publish_mode_and_quality_alerts_join_maintainer_delivery(tmp_path, phases, monkeypatch):
    catalog(tmp_path)
    quality = {'id':'policy:example', 'category':'policy', 'overdue':True}
    monkeypatch.setattr(pipeline.quality_status, 'refresh', Mock(return_value={
        'active':[quality], 'summary':{'overdue':1}}))
    result = pipeline.run(tmp_path, publish=True, discover=True)
    assert phases['discovery'].call_args.kwargs['auto_admit'] is True
    assert quality in phases['notifications'].call_args.args[1]['active']
    assert result['status'] == 'attention'
    phases['notifications'].reset_mock()
    pipeline.run(tmp_path, publish=False, discover=True)
    assert phases['discovery'].call_args.kwargs['auto_admit'] is False
    phases['notifications'].assert_not_called()


def test_failed_build_retries_next_run_and_only_success_advances_digest(tmp_path, phases):
    digest = catalog(tmp_path)
    phases['build'].side_effect = [RuntimeError('build failed'), {'published': True}, {'published': True}]
    first = pipeline.run(tmp_path, publish=True)
    assert first['status'] == 'partial' and first['built_catalog_sha256'] is None
    assert first['failures']['public_pages'] == 'RuntimeError'
    second = pipeline.run(tmp_path, publish=True)
    assert second['status'] == 'ok' and second['built_catalog_sha256'] == digest
    pipeline.run(tmp_path, publish=True)
    assert phases['build'].call_count == 2
    changed = catalog(tmp_path, '{"opportunities": [], "updated": true}')
    fourth = pipeline.run(tmp_path, publish=True)
    assert phases['build'].call_count == 3 and fourth['built_catalog_sha256'] == changed
    assert json.loads((tmp_path / 'cache/review-pipeline.json').read_text(encoding='utf8'))['built_catalog_sha256'] == changed


def test_alert_failure_skips_sending_but_allows_publication_and_metrics(tmp_path, phases):
    digest = catalog(tmp_path)
    phases['alerts'].side_effect = OSError('alerts cannot be written')
    result = pipeline.run(tmp_path, publish=True)
    assert result['status'] == 'partial' and result['built_catalog_sha256'] == digest
    phases['notifications'].assert_not_called()
    phases['metrics'].assert_called_once_with(tmp_path)


def test_catalog_read_failure_is_isolated_and_releases_run_lock(tmp_path, phases, monkeypatch):
    catalog(tmp_path)
    original = Path.read_bytes
    def fail_catalog(path):
        if path == tmp_path / 'data/opportunities.json':
            raise PermissionError('secret fixture config detail')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', fail_catalog)
    failed = pipeline.run(tmp_path, publish=True)
    assert failed['status'] == 'partial' and failed['failures']['public_pages'] == 'PermissionError'
    assert 'secret fixture' not in json.dumps(failed)
    phases['metrics'].assert_called_once_with(tmp_path)
    monkeypatch.setattr(Path, 'read_bytes', original)
    assert pipeline.run(tmp_path, publish=True)['status'] == 'ok'


def test_rebuild_subprocess_failures_hide_raw_output_and_release_lock(tmp_path, monkeypatch):
    (tmp_path / 'cache').mkdir()
    process = Mock(return_value=Mock(returncode=1, stdout='fixture-key-secret', stderr='fixture-key-secret'))
    monkeypatch.setattr(pipeline.subprocess, 'run', process)
    snapshot = Mock()
    from crawler import public_snapshot
    monkeypatch.setattr(public_snapshot, 'build', snapshot)
    with pytest.raises(ValueError, match='重建失败') as error:
        pipeline.rebuild(tmp_path)
    assert 'fixture-key-secret' not in str(error.value)
    snapshot.assert_not_called()
    process.return_value.returncode = 0
    assert pipeline.rebuild(tmp_path) == {'published': True}
    snapshot.assert_not_called()


@pytest.mark.parametrize('quality', [
    {'available': {'policy': False, 'mentor': True}},
    {'incomplete': [{'id': 'policy:p', 'reason': '缺少时钟'}]},
    {'summary': {'overdue': 1}},
])
def test_unavailable_or_incomplete_quality_never_reports_healthy(tmp_path, phases, quality):
    phases['quality'].return_value = dict(active=[], **quality)
    assert pipeline.run(tmp_path)['status'] == 'attention'


def test_source_recovery_requires_publish_mode_and_isolates_failure(tmp_path, phases):
    pipeline.run(tmp_path, discover=True)
    phases['recovery'].assert_not_called()
    phases['recovery'].side_effect = ValueError('fixture private diagnostic')
    result = pipeline.run(tmp_path, discover=True, publish=True)
    phases['recovery'].assert_called_once_with(tmp_path, limit=1, request_budget=16)
    assert result['status'] == 'partial' and result['failures']['source_recovery'] == 'ValueError'
    assert 'fixture private diagnostic' not in json.dumps(result)
    assert phases['automatic'].call_count == 2 and phases['metrics'].call_count == 2


def test_source_recovery_budget_wait_needs_attention(tmp_path, phases):
    phases['recovery'].return_value = {'summary': {'budget_wait': 1}}
    result = pipeline.run(tmp_path, discover=True, publish=True)
    assert result['status'] == 'attention' and not result['failures']

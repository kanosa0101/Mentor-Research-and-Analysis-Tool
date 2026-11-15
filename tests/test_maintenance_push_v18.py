import base64
import json
from unittest.mock import patch

import pytest

from crawler import maintenance_push as alerts, push_util


def subscription(endpoint='https://fcm.googleapis.com/fcm/send/maintainer-fixture'):
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    return dict(endpoint=endpoint, keys=dict(auth=encode(b'a' * 16), p256dh=encode(b'\x04' + b'b' * 64)))


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / 'var/push'
    directory.mkdir(parents=True)
    (directory / 'config.json').write_text(json.dumps(dict(public_key='fixture-public-key')), encoding='utf8')
    (directory / 'vapid.pem').write_text('fixture; never used for real delivery', encoding='utf8')
    with patch.object(push_util, 'send', side_effect=AssertionError('Real push is forbidden in tests')):
        yield tmp_path


def queue(fingerprint='version1', overdue=True):
    return dict(active=[dict(id='draft1', fingerprint=fingerprint, due_at='2026-11-15T02:00:00+00:00',
                             priority=0, overdue=overdue)])


def test_subscriptions_are_isolated_owned_and_never_expose_private_keys(root):
    body = alerts.subscribe(root, dict(subscription=subscription()))
    assert not (root / 'var/push/alerts.sqlite').exists()
    assert 'token' not in alerts.paths(root)[0].read_text(encoding='utf8').replace('token_hash', '')
    assert body['token'] not in alerts.paths(root)[0].read_text(encoding='utf8')
    with pytest.raises(ValueError, match='凭据'):
        alerts.subscribe(root, dict(subscription=subscription()))
    with pytest.raises(ValueError, match='凭据'):
        alerts.unsubscribe(root, dict(id=body['id'], token='wrong'))
    assert alerts.subscribe(root, dict(subscription=subscription(), token=body['token'])) == body
    assert set(alerts.settings(root)) == {'enabled', 'public_key', 'last_delivery', 'audience', 'requires_explicit_subscription'}
    alerts.unsubscribe(root, body)
    assert alerts.read(alerts.paths(root)[0]) == {}


def test_no_subscription_or_unexpired_task_never_sends(root):
    sender = lambda *_: pytest.fail('Unsubscribed or unexpired alerts must not send')
    assert alerts.dispatch(root, queue(), sender)['sent'] == 0
    alerts.subscribe(root, dict(subscription=subscription()))
    assert alerts.dispatch(root, queue(overdue=False), sender)['sent'] == 0


def test_overdue_delivery_is_deduplicated_and_reopened_version_notifies(root):
    alerts.subscribe(root, dict(subscription=subscription()))
    calls = []
    def sender(sub, payload):
        calls.append(payload)
        return 201
    assert alerts.dispatch(root, queue(), sender)['sent'] == 1
    assert alerts.dispatch(root, queue(), sender)['sent'] == 0
    assert alerts.dispatch(root, queue('version2'), sender)['sent'] == 1
    assert all(c['url'] == '/review.html?draft=draft1' for c in calls)


def test_delivery_failure_is_bounded_and_remains_visible(root):
    alerts.subscribe(root, dict(subscription=subscription()))
    calls = []
    def sender(*_):
        calls.append(1)
        return 503
    for _ in range(5):
        assert alerts.dispatch(root, queue(), sender)['failed'] == 1
    result = alerts.dispatch(root, queue(), sender)
    assert len(calls) == 5 and result['retry_exhausted'] == 1
    assert alerts.settings(root)['last_delivery']['retry_exhausted'] == 1


def test_expired_subscription_removed_and_inflight_unsubscribe_not_recreated(root):
    credential = alerts.subscribe(root, dict(subscription=subscription()))
    assert alerts.dispatch(root, queue(), lambda *_: 410)['expired'] == 1
    assert alerts.unsubscribe(root, credential) == {'removed': True}
    assert not alerts.read(alerts.paths(root)[0])
    credential = alerts.subscribe(root, dict(subscription=subscription()))
    def sender(*_):
        alerts.unsubscribe(root, credential)
        return 201
    alerts.dispatch(root, queue(), sender)
    assert not alerts.read(alerts.paths(root)[0])


def test_ssrf_rejected_and_test_delivery_is_explicit(root):
    with pytest.raises(ValueError):
        alerts.subscribe(root, dict(subscription=subscription('http://127.0.0.1/private')))
    credential = alerts.subscribe(root, dict(subscription=subscription()))
    assert alerts.test_notification(root, credential, lambda *_: 201)['accepted']
    with pytest.raises(ValueError):
        alerts.test_notification(root, credential, lambda *_: 500)

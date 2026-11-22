import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from crawler import ai_evidence, ai_review, ai_transport, automatic_review


def test_incomplete_field_protocol_is_retryable_without_accepting_partial_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_review.ai_evidence, 'config', lambda _: {'model': 'fixture'})
    counted = []
    monkeypatch.setattr(ai_review.ai_evidence, 'reserve_request', lambda *args: counted.append(1))
    monkeypatch.setattr(ai_transport, 'completion', lambda *args, **kwargs:
        (json.dumps({'decision': 'consistent', 'issues': [], 'checks': []}), {}))
    with pytest.raises(ai_transport.AIServiceError) as caught:
        ai_review.check(tmp_path, 'https://cs.example.edu.cn/camp.html', '本科生申请。',
                        {'eligibility': {'value': '本科生申请。', 'quote': '本科生申请。'}})
    assert caught.value.code == 'invalid_schema' and caught.value.retryable
    assert counted == [1]


def test_field_cache_hash_binds_values_and_quotes_with_stable_order():
    fields = {'eligibility': {'value': '本科生', 'quote': '本科生申请'}, 'materials': {'value': ['成绩单'], 'quote': '成绩单'}}
    assert ai_review.fields_hash(fields) == ai_review.fields_hash(dict(reversed(list(fields.items()))))
    assert ai_review.fields_hash(fields) != ai_review.fields_hash(dict(fields, eligibility={'value': '研究生', 'quote': '本科生申请'}))


def test_safe_transport_diagnostics_reach_automatic_error_record():
    error = ai_transport.AIServiceError('total_timeout', '超时', retryable=True, phase='response_body')
    error.transport = {'elapsed_seconds': 91, 'first_answer_seconds': None, 'complete': False}
    result = automatic_review.service_failure(error)
    assert result['transport'] == error.transport
    assert result['error_code'] == 'total_timeout' and result['retryable']


@pytest.fixture
def provider(monkeypatch, tmp_path):
    clock = [datetime(2026, 11, 22, 22, tzinfo=timezone.utc)]
    settings = dict(base_url='https://example.com/v1', model='fixture', api_key='fixture-only', daily_limit=3)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].astimezone(tz)

    monkeypatch.setattr(ai_evidence, 'datetime', Clock)
    monkeypatch.setattr(ai_evidence, 'config', lambda _: settings)

    def deny(*_args, **_kwargs):
        raise ai_transport.AIServiceError('http_402', 'HTTP 402', retryable=False)

    def exhaust():
        monkeypatch.setattr(ai_transport, 'completion', deny)
        with pytest.raises(ai_transport.AIServiceError) as error:
            ai_evidence.completion(tmp_path, 10, settings, [])
        assert error.value.code == 'http_402'
        assert 'fixture-only' not in (tmp_path/'cache/ai-evidence-usage.json').read_text(encoding='utf-8')
        return datetime.fromisoformat(error.value.next_attempt_at)

    return clock, settings, exhaust


def test_provider_cooldown_survives_midnight_and_only_one_real_task_probes(provider, tmp_path, monkeypatch):
    clock, settings, exhaust = provider
    expiry = exhaust()
    ledger_path = tmp_path/'cache/ai-evidence-usage.json'
    first = ledger_path.read_bytes()
    assert expiry == clock[0] + timedelta(hours=6)
    clock[0] += timedelta(hours=3)
    with pytest.raises(ai_transport.AIServiceError) as error:
        ai_evidence.completion(tmp_path, 20, settings, [])
    assert error.value.code == 'provider_cooldown' and ledger_path.read_bytes() == first

    clock[0] = expiry
    admitted, finish = Event(), Event()

    def succeed(*_args, **_kwargs):
        admitted.set()
        assert finish.wait(5)
        return 'complete', {}

    monkeypatch.setattr(ai_transport, 'completion', succeed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(ai_evidence.completion, tmp_path, 20, settings, [])
        try:
            assert admitted.wait(5)
            with pytest.raises(ai_transport.AIServiceError) as denied:
                ai_evidence.completion(tmp_path, 30, settings, [])
            assert denied.value.code == 'provider_cooldown'
            snapshot = json.loads(ledger_path.read_bytes())
            assert (snapshot['date'], snapshot['requests'], snapshot['input_chars']) == ('2026-11-23', 1, 20)
        finally:
            finish.set()
        assert running.result(timeout=5) == ('complete', {})
    assert not ai_evidence.provider_retry_at(tmp_path)
    assert ai_evidence.completion(tmp_path, 30, settings, []) == ('complete', {})


def test_provider_rejection_backoff_is_bounded_and_reconfiguration_keeps_quota(provider, tmp_path, monkeypatch):
    clock, settings, exhaust = provider
    for index, hours in enumerate((6, 12, 24, 24), 1):
        expiry = exhaust()
        assert expiry == clock[0] + timedelta(hours=hours)
        if index < 4:
            clock[0] = expiry
    replacement = dict(settings, api_key='replacement', daily_limit=1)
    with pytest.raises(ValueError, match='每日调用上限'):
        ai_evidence.completion(tmp_path, 20, replacement, [])
    clock[0] = clock[0].replace(hour=0) + timedelta(days=1)
    monkeypatch.setattr(ai_transport, 'completion', lambda *a, **kw: ('ok', {}))
    assert ai_evidence.completion(tmp_path, 20, replacement, []) == ('ok', {})
    ledger = json.loads((tmp_path/'cache/ai-evidence-usage.json').read_bytes())
    assert (ledger['requests'], ledger['input_chars']) == (1, 20)


def test_interrupted_recovery_probe_expires_without_clearing_the_provider_state(provider, tmp_path, monkeypatch):
    clock, settings, exhaust = provider
    clock[0] = exhaust()
    lease, _ = ai_evidence.reserve_request(tmp_path, 20, settings)
    assert lease  # Process stops before transport finishes.
    with pytest.raises(ai_transport.AIServiceError) as error:
        ai_evidence.completion(tmp_path, 30, settings, [])
    assert error.value.code == 'provider_cooldown'
    assert datetime.fromisoformat(error.value.next_attempt_at) == clock[0] + ai_evidence.PROBE_LEASE
    clock[0] += ai_evidence.PROBE_LEASE
    monkeypatch.setattr(ai_transport, 'completion', lambda *a, **kw: ('ok', {}))
    assert ai_evidence.completion(tmp_path, 30, settings, []) == ('ok', {})


def test_unconfirmed_probe_backs_off_without_counting_another_payment_failure(provider, tmp_path, monkeypatch):
    clock, settings, exhaust = provider
    clock[0] = exhaust()

    def timeout(*_args, **_kwargs):
        raise ai_transport.AIServiceError('read_timeout', 'timeout', retryable=True, phase='response_body')

    monkeypatch.setattr(ai_transport, 'completion', timeout)
    with pytest.raises(ai_transport.AIServiceError) as failed:
        ai_evidence.completion(tmp_path, 20, settings, [])
    assert failed.value.code == 'read_timeout'
    with pytest.raises(ai_transport.AIServiceError) as wait:
        ai_evidence.completion(tmp_path, 30, settings, [])
    assert wait.value.code == 'provider_cooldown'
    assert datetime.fromisoformat(wait.value.next_attempt_at) == clock[0] + ai_evidence.PROBE_FAILURE_WAIT
    clock[0] += ai_evidence.PROBE_FAILURE_WAIT
    assert exhaust() == clock[0] + timedelta(hours=12)


def test_late_payment_error_from_before_a_successful_probe_cannot_reopen_it(provider, tmp_path, monkeypatch):
    clock, settings, exhaust = provider
    admitted, finish = Event(), Event()

    def stale(*_args, **_kwargs):
        admitted.set()
        assert finish.wait(5)
        raise ai_transport.AIServiceError('http_402', 'late 402', retryable=False)

    monkeypatch.setattr(ai_transport, 'completion', stale)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(ai_evidence.completion, tmp_path, 10, settings, [])
        try:
            assert admitted.wait(5)
            clock[0] = exhaust()
            monkeypatch.setattr(ai_transport, 'completion', lambda *a, **kw: ('ok', {}))
            assert ai_evidence.completion(tmp_path, 20, settings, []) == ('ok', {})
        finally:
            finish.set()
        with pytest.raises(ai_transport.AIServiceError) as error:
            running.result(timeout=5)
        assert error.value.code == 'http_402'
    assert not ai_evidence.provider_retry_at(tmp_path)
    assert ai_evidence.completion(tmp_path, 30, settings, []) == ('ok', {})

import json

import pytest

from crawler import ai_review, ai_transport, automatic_review


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

import json
from unittest.mock import Mock

import pytest
import requests

from crawler import ai_transport as transport


SETTINGS = dict(base_url='https://api.ai.50x.energy/v1', api_key='fixture-secret',
                model='deepseek-ai/DeepSeek-V4.1-Flash-1017')


def frame(value):
    return ('data: ' + json.dumps(value, ensure_ascii=False) + '\n\n').encode()


def response(chunks, content_type='text/event-stream'):
    client = Mock()
    result = client.post.return_value
    result.status_code = 200
    result.headers = {'Content-Type': content_type}
    result.iter_content.return_value = chunks
    return client, result


def delta(content=None, finish=None, **extra):
    return frame({'choices': [{'index': 0, 'delta': dict(content=content, **extra), 'finish_reason': finish}]})


def test_fragmented_utf8_sse_requires_done_and_discards_reasoning():
    payload = b': keep-alive\n\n' + delta(reasoning_content='private reasoning') + delta('{"note":"中文') + delta('"}', 'stop') + b'data: [DONE]\n\n'
    client, result = response([bytes([n]) for n in payload])
    text, timing = transport.completion(SETTINGS, [{'role':'user','content':'public'}], session=client)
    assert json.loads(text) == {'note':'中文'}
    assert timing['complete'] and timing['mode'] == 'stream'
    assert 'private reasoning' not in json.dumps(timing)
    sent = client.post.call_args.kwargs
    assert sent['json']['reasoning_effort'] == 'none'
    assert sent['json']['stream'] and sent['stream'] and not sent['allow_redirects']
    assert sent['timeout'] == (10,30)
    assert client.trust_env is False
    assert 'fixture-secret' not in json.dumps(sent['json'])
    result.close.assert_called_once()
    client.close.assert_not_called()


@pytest.mark.parametrize('chunks', [
    [delta('{}','stop')],
    [delta('{}'), b'data: [DONE]\n\n'],
    [delta('{}','length'), b'data: [DONE]\n\n'],
    [delta(reasoning_content='{}'), delta(finish='stop'), b'data: [DONE]\n\n'],
    [b'data: not-json\n\n'],
])
def test_partial_empty_and_malformed_outputs_never_pass(chunks):
    client, result = response(chunks)
    with pytest.raises(transport.AIServiceError) as error:
        transport.completion(SETTINGS, [], session=client)
    assert error.value.code in ('incomplete_output','invalid_response')
    assert error.value.retryable is True
    result.close.assert_called_once()


@pytest.mark.parametrize('status,retryable', [(301,False),(400,False),(401,False),(403,False),(408,True),(429,True),(500,True),(503,True)])
def test_http_classification_never_copies_provider_body(status,retryable):
    client, result = response([b'fixture-secret-provider-body'])
    result.status_code = status
    with pytest.raises(transport.AIServiceError) as error:
        transport.completion(SETTINGS, [], session=client)
    assert error.value.code == 'http_' + str(status)
    assert error.value.retryable is retryable
    assert 'secret' not in str(error.value)
    assert error.value.phase == 'response_headers'
    result.iter_content.assert_not_called()


@pytest.mark.parametrize('exception,code,retryable', [
    (requests.ConnectTimeout('secret'),'connect_timeout',True),
    (requests.ReadTimeout('secret'),'read_timeout',True),
    (requests.ConnectionError('secret'),'network_error',True),
    (requests.exceptions.SSLError('secret'),'tls_error',False),
])
def test_request_errors_are_typed_without_credentials(exception,code,retryable):
    client = Mock();client.post.side_effect = exception
    with pytest.raises(transport.AIServiceError) as error:
        transport.completion(SETTINGS, [], session=client)
    assert (error.value.code,error.value.retryable) == (code,retryable)
    assert 'secret' not in str(error.value)


def test_continuous_heartbeats_cannot_reset_total_budget(monkeypatch):
    client, result = response(iter([b': heart',b'beat\n',b': next']))
    moments = iter([0,1,20,20,89,91,91])
    monkeypatch.setattr(transport.time,'monotonic',lambda:next(moments))
    with pytest.raises(transport.AIServiceError) as error:
        transport.completion(SETTINGS, [], session=client)
    assert error.value.code == 'total_timeout' and error.value.retryable
    assert error.value.transport['elapsed_seconds'] == 91
    assert error.value.transport['first_answer_seconds'] is None
    assert error.value.transport['complete'] is False
    result.close.assert_called_once()


def test_response_size_bound_applies_before_json_parse(monkeypatch):
    client, result = response([b'a'*30], 'application/json')
    monkeypatch.setattr(transport,'MAX_BYTES',20)
    with pytest.raises(transport.AIServiceError) as error:
        transport.completion(SETTINGS, [], session=client)
    assert error.value.code == 'response_too_large' and not error.value.retryable


def test_json_fallback_keeps_existing_envelope_guards():
    body={'choices':[{'finish_reason':'stop','message':{'content':'{}','reasoning_content':'private'}}]}
    client, result = response([json.dumps(body).encode()], 'application/json')
    text,timing=transport.completion(dict(SETTINGS,model='another-model'),[],session=client)
    assert text=='{}' and timing['mode']=='json'
    assert 'reasoning_effort' not in client.post.call_args.kwargs['json']


def test_same_model_on_another_provider_does_not_get_untested_parameters():
    client, _ = response([delta('{}','stop'),b'data: [DONE]\n\n'])
    transport.completion(dict(SETTINGS,base_url='https://other.example/v1'),[],session=client)
    assert 'reasoning_effort' not in client.post.call_args.kwargs['json']


def test_owned_session_is_closed_on_failure(monkeypatch):
    client=Mock();client.post.side_effect=requests.ReadTimeout('secret')
    monkeypatch.setattr(transport.requests,'Session',lambda:client)
    with pytest.raises(transport.AIServiceError):transport.completion(SETTINGS,[])
    client.close.assert_called_once()

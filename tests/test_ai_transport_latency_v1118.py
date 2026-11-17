import json
from unittest.mock import Mock

import pytest
import requests

from crawler import ai_transport as transport


SETTINGS = dict(base_url='https://api.ai.50x.energy/v1', api_key='fixture-secret',
    model='deepseek-ai/DeepSeek-V4.1-Flash-1017')


def test_delayed_headers_after_old_idle_limit_can_complete(monkeypatch):
    clock = [0]
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    client, reply = Mock(), Mock()
    reply.status_code, reply.headers = 200, {'Content-Type': 'application/json'}
    def post(*args, **kwargs):
        assert kwargs['timeout'] == (10, 45)
        clock[0] = 31
        return reply
    def content(**kwargs):
        clock[0] = 34
        yield json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}).encode()
    client.post.side_effect, reply.iter_content.side_effect = post, content
    text, timing = transport.completion(SETTINGS, [], session=client)
    assert text == '{}' and timing['complete'] is True
    assert timing['header_seconds'] == 31 and timing['elapsed_seconds'] == 34
    reply.close.assert_called_once()


def test_idle_header_timeout_stays_typed_and_does_not_retry(monkeypatch):
    clock = [0]
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    client = Mock()
    def post(*args, **kwargs):
        clock[0] = kwargs['timeout'][1]
        raise requests.ReadTimeout('provider private text')
    client.post.side_effect = post
    with pytest.raises(transport.AIServiceError) as caught:
        transport.completion(SETTINGS, [], session=client)
    assert caught.value.code == 'read_timeout' and caught.value.phase == 'response_headers'
    assert caught.value.transport['elapsed_seconds'] == 45
    assert 'private' not in str(caught.value)
    client.post.assert_called_once()


@pytest.mark.parametrize('late_chunk', [b': heartbeat\n\n', b'data: [DONE]\n\n'])
def test_last_idle_interval_is_reserved_within_existing_total_limit(monkeypatch, late_chunk):
    clock = [0]
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    client, reply = Mock(), Mock()
    reply.status_code, reply.headers = 200, {'Content-Type': 'text/event-stream'}
    client.post.return_value = reply
    def content(**kwargs):
        clock[0] = 74.9
        yield b': heartbeat\n\n'
        clock[0] += transport.READ_TIMEOUT
        yield late_chunk
    reply.iter_content.side_effect = content
    with pytest.raises(transport.AIServiceError) as caught:
        transport.completion(SETTINGS, [], session=client)
    assert caught.value.code == 'total_timeout'
    assert transport.TOTAL_TIMEOUT == 120
    assert caught.value.transport['elapsed_seconds'] == 119.9
    assert caught.value.transport['complete'] is False
    reply.close.assert_called_once()

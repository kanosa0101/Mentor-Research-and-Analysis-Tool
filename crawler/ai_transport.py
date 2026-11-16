"""Bounded completion transport for the configured public-evidence model."""
import json
import sys
import time
from urllib.parse import urlsplit

import requests

READ_TIMEOUT = 30
TOTAL_TIMEOUT = 120
MAX_BYTES = 1_000_000


class AIServiceError(ValueError):
    def __init__(self, code, message, *, retryable, phase=None):
        super().__init__(message)
        self.code, self.retryable, self.phase = code, retryable, phase


def fail(code, message, *, retryable=True, phase=None):
    raise AIServiceError(code, message, retryable=retryable, phase=phase)


def completion(settings, messages, *, session=None):
    """No internal retries: each call is charged by the caller before this function."""
    request = dict(model=settings['model'], messages=messages, max_tokens=6000,
                   temperature=0, stream=True)
    # This explicit mode is documented and live-tested for the configured 50X model.
    if (urlsplit(settings['base_url']).hostname == 'api.ai.50x.energy' and
            settings['model'] == 'deepseek-ai/DeepSeek-V4.1-Flash-1017'):
        request['reasoning_effort'] = 'none'
    client = session or requests.Session()
    client.trust_env = False
    started = time.monotonic()
    response = None
    phase = 'response_headers'
    timing = dict(first_byte_seconds=None, first_answer_seconds=None)
    received = 0
    try:
        response = client.post(settings['base_url'] + '/chat/completions',
            headers={'Authorization': 'Bearer ' + settings['api_key'], 'Content-Type': 'application/json'},
            json=request, timeout=(10, READ_TIMEOUT), allow_redirects=False, stream=True)
        timing['header_seconds'] = round(time.monotonic() - started, 3)
        status = response.status_code
        if status != 200:
            fail('http_' + str(status), 'AI服务HTTP ' + str(status) + '；没有完整核验结论',
                 retryable=status in (408, 425, 429) or status >= 500, phase=phase)
        stream = 'text/event-stream' in str(response.headers.get('Content-Type', '')).lower()
        phase = 'response_body'
        buffer = bytearray()
        content, finish, done, received = [], None, False, 0
        for chunk in response.iter_content(chunk_size=1):
            # requests has an idle timeout, not a total deadline. Reserve one final
            # idle interval so a heartbeat stream cannot extend the 120s budget.
            if time.monotonic() - started >= TOTAL_TIMEOUT - READ_TIMEOUT:
                fail('total_timeout', 'AI服务总耗时超过限制；没有完整核验结论', phase=phase)
            if not chunk:
                continue
            if timing['first_byte_seconds'] is None:
                timing['first_byte_seconds'] = round(time.monotonic() - started, 3)
            received += len(chunk)
            if received > MAX_BYTES:
                fail('response_too_large', 'AI响应超出大小限制', retryable=False, phase=phase)
            buffer.extend(chunk)
            if not stream or b'\n' not in buffer:
                continue
            while b'\n' in buffer:
                line, _, rest = buffer.partition(b'\n');buffer = bytearray(rest)
                if not line.startswith(b'data:'):
                    continue
                payload = line[5:].strip()
                if payload == b'[DONE]':
                    done = True
                    break
                event = json.loads(payload)
                if event.get('error'):
                    fail('stream_error', 'AI流式服务返回错误；没有完整核验结论', phase=phase)
                for choice in event.get('choices', []):
                    if choice.get('index', 0) != 0:
                        fail('invalid_response', 'AI响应选择序号无效', phase=phase)
                    delta = choice.get('delta', {})
                    value = delta.get('content')
                    if value is not None:
                        if not isinstance(value, str):
                            fail('invalid_response', 'AI响应无法通过结构检查', phase=phase)
                        if value and timing['first_answer_seconds'] is None:
                            timing['first_answer_seconds'] = round(time.monotonic() - started, 3)
                        content.append(value)
                    if choice.get('finish_reason') is not None:
                        finish = choice['finish_reason']
            if done:
                break
        if not stream:
            body = json.loads(buffer)
            choice = body['choices'][0]
            content, finish, done = [choice['message']['content']], choice.get('finish_reason'), True
        if not done or finish != 'stop':
            fail('incomplete_output', 'AI响应未完整结束，结果不完整，未写入建议',
                 retryable=finish not in ('content_filter', 'tool_calls'), phase=phase)
        if any(not isinstance(value, str) for value in content) or not ''.join(content).strip():
            fail('invalid_response', 'AI响应无法通过结构检查', phase=phase)
        timing.update(elapsed_seconds=round(time.monotonic() - started, 3),
                      response_bytes=received, mode='stream' if stream else 'json',
                      max_tokens=request['max_tokens'],
                      reasoning_effort=request.get('reasoning_effort'), complete=True)
        return ''.join(content), timing
    except requests.exceptions.SSLError:
        fail('tls_error', 'AI服务TLS校验失败；没有核验结论', retryable=False, phase=phase)
    except requests.exceptions.ConnectTimeout:
        fail('connect_timeout', 'AI服务连接超时；没有核验结论', phase=phase)
    except requests.exceptions.ReadTimeout:
        fail('read_timeout', 'AI服务读取超时；没有核验结论', phase=phase)
    except requests.RequestException as error:
        # urllib3 wraps streamed idle timeouts in ConnectionError. Never serialize
        # the exception text, request headers or provider response body.
        kind = 'read_timeout' if 'ReadTimeout' in repr(type(error.__context__)) else 'network_error'
        fail(kind, 'AI服务网络请求失败；没有核验结论', phase=phase)
    except (KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError, UnicodeDecodeError):
        fail('invalid_response', 'AI响应无法通过结构检查', phase=phase)
    finally:
        error = sys.exc_info()[1]
        if isinstance(error, AIServiceError):
            # Diagnostics contain timing/counters only, never provider output,
            # request headers, credentials or private reasoning tokens.
            error.transport = dict(timing, elapsed_seconds=round(time.monotonic() - started, 3),
                response_bytes=received, complete=False, phase=phase)
        if response is not None:
            response.close()
        if session is None:
            client.close()

"""Explicit public JSON POST sources retain request and content identity."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from crawler import admissions_util as rules
from crawler import fetch

SOURCE = dict(url='https://example.edu/directory', api='https://example.edu/api/directory',
              format='json', selector='/data/0', method='POST', json={'yearId': '2027'},
              json_content='structured')

def body(value=None, **extra):
    return json.dumps(dict(code='0', data=[value if value is not None else {'code': '081200', 'notes': '不招同等学力'}], **extra), ensure_ascii=False).encode()

def test_explicit_post_source_uses_json_body():
    rules.validate(dict(version=1, sources={'s': SOURCE}, policies=[]), {})
    with patch.object(rules.fetch, 'fetch', return_value=(body(), {'fetched_at': '2026-10-15'}, False)) as request:
        result = rules.check_source(SOURCE, {}, True, '2026-10-15')
    request.assert_called_once_with('POST', SOURCE['api'], json_data=SOURCE['json'], refresh=True)
    assert result['status'] == 'ok' and result['hash'] == rules.fingerprint(body(), SOURCE)

@pytest.mark.parametrize('changes', [
    {'method': 'DELETE'}, {'method': 'GET'}, {'json': None}, {'json': []}, {'json': {}},
    {'json': {'nested': {}}}, {'json': {'': '2027'}}, {'json_content': 'anything'},
    {'format': 'html'}, {'method': None}, {'json_content': 'html'},
])
def test_invalid_request_contract_rejected(changes):
    with pytest.raises(ValueError):
        rules.validate(dict(version=1, sources={'s': dict(SOURCE, **changes)}, policies=[]), {})

def test_request_fields_not_allowed_without_explicit_json_post():
    source = dict(SOURCE)
    source.pop('method')
    with pytest.raises(ValueError):
        rules.validate(dict(version=1, sources={'s': source}, policies=[]), {})
    source = dict(SOURCE)
    source.pop('json_content')
    with pytest.raises(ValueError):
        rules.validate(dict(version=1, sources={'s': source}, policies=[]), {})

def test_structured_fingerprint_is_stable_but_binds_request_and_content():
    first = rules.fingerprint(body(), SOURCE)
    assert first == rules.fingerprint(body({'notes': '不招同等学力', 'code': '081200'}, views=999), SOURCE)
    assert first != rules.fingerprint(body({'code': '085404', 'notes': '不招同等学力'}), SOURCE)
    assert first != rules.fingerprint(body(), dict(SOURCE, json={'yearId': '2028'}))
    assert first != rules.fingerprint(body(), dict(SOURCE, api='https://example.edu/api/other'))

@pytest.mark.parametrize('raw', [
    b'{}', b'not-json', body({}), body([]), body('HTML is not structured data'),
    b'{"code":"BIZ_EXCEPTION","data":[{"message":"not published"}]}',
    b'{"code":"0","data":[{"value":NaN}]}',
])
def test_errors_empty_nonstructured_or_nonfinite_data_rejected(raw):
    with pytest.raises(ValueError):
        rules.fingerprint(raw, SOURCE)

def test_post_failure_retains_previous_success_and_cached_response_cannot_clear_failure():
    old = dict(status='ok', hash='a'*64, last_success='2026-10-14')
    with patch.object(rules.fetch, 'fetch', return_value=(b'{}', {'fetched_at': '2026-10-15'}, False)):
        result = rules.check_source(SOURCE, old, True, '2026-10-15')
    assert result['status'] == 'error' and result['hash'] == old['hash'] and result['last_success'] == old['last_success']
    with patch.object(rules.fetch, 'fetch', return_value=(body(), {'fetched_at': '2026-10-14'}, True)):
        cached = rules.check_source(SOURCE, result, False, '2026-10-15')
    assert cached['status'] == 'error' and cached['cached']

def test_json_transport_and_cache_distinguish_form_json_and_year(tmp_path):
    response = SimpleNamespace(content=b'{"ok":true}', status_code=200, raise_for_status=lambda: None)
    with patch.object(fetch, 'CACHE', tmp_path), patch.object(fetch, '_throttle'), patch.object(fetch, '_request', return_value=response) as request:
        _, meta, hit = fetch.fetch('POST', SOURCE['api'], json_data=SOURCE['json'])
        assert not hit and meta['json'] == SOURCE['json']
        assert request.call_args.kwargs['json'] == SOURCE['json'] and 'data' not in request.call_args.kwargs
        assert fetch.fetch('POST', SOURCE['api'], json_data=copy.deepcopy(SOURCE['json']))[2]
        fetch.fetch('POST', SOURCE['api'], json_data={'yearId': '2028'})
        fetch.fetch('POST', SOURCE['api'], data=SOURCE['json'])
        assert request.call_count == 3
        assert len(list(tmp_path.glob('*.body'))) == 3
    with pytest.raises(ValueError):
        fetch.fetch('POST', SOURCE['api'], data={}, json_data={})

@pytest.mark.parametrize('status,content', [(202, b'{"data":[]}'), (200, b'frms-fingerprint')])
def test_json_post_never_downgrades_to_browser_get(tmp_path, status, content):
    response = SimpleNamespace(content=content, status_code=status, raise_for_status=lambda: None)
    with patch.object(fetch, 'CACHE', tmp_path), patch.object(fetch, '_throttle'), patch.object(fetch, '_cdp_fallback', True), patch.object(fetch, '_request', return_value=response), patch.object(fetch, 'fetch_cdp') as browser:
        assert fetch.fetch('POST', SOURCE['api'], json_data=SOURCE['json'])[0] == content
        browser.assert_not_called()

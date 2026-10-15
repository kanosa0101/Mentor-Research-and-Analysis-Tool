"""Official JSON policy source contracts; human URL and API must share origin."""
import json
from unittest.mock import patch

import pytest
from crawler import admissions_util as rules

SOURCE = {'url': 'https://gs.example.edu/#/admission/detail?article_id=3579',
          'api': 'https://gs.example.edu/api/www/v1/article/view?id=3579',
          'format': 'json', 'selector': '/data/content'}


def body(content='<p>报名材料</p><a href="/a.pdf">附件</a>', **changes):
    return json.dumps({'error': 0, 'data': {'content': content}, 'views': 1, **changes}).encode()


def test_json_source_validated_and_api_used_for_fresh_check():
    rules.validate({'version': 1, 'sources': {'test': SOURCE}, 'policies': []}, {})
    with patch.object(rules.fetch, 'fetch', return_value=(body(), {'fetched_at': '2026-10-15'}, False)) as fetch:
        result = rules.check_source(SOURCE, {}, True, '2026-10-15')
    fetch.assert_called_once_with('GET', SOURCE['api'], refresh=True)
    assert result['status'] == 'ok' and result['last_success'] == '2026-10-15'
    assert result['cached'] is False


def test_only_selected_content_and_attachment_links_define_fingerprint():
    first = rules.fingerprint(body(), SOURCE)
    assert first == rules.fingerprint(body(views=999), SOURCE)
    assert first == rules.fingerprint(body('<p>报名材料</p><script>views=999</script><a href="/a.pdf">附件</a>'), SOURCE)
    assert first != rules.fingerprint(body('<p>报名时间</p><a href="/a.pdf">附件</a>'), SOURCE)
    assert first != rules.fingerprint(body('<p>报名材料</p><a href="/b.pdf">附件</a>'), SOURCE)


@pytest.mark.parametrize('raw', [b'not-json', b'<html>error</html>', b'{}',
    body(content=None), body(content=7), body(content=''), body(content=' <script>x</script> '),
    body(error=403), json.dumps({'error': 0, 'data': []}).encode()])
def test_invalid_json_missing_pointer_nonstring_empty_or_error_rejected(raw):
    with pytest.raises(ValueError):
        rules.fingerprint(raw, SOURCE)


@pytest.mark.parametrize('change', [
    {'selector': ''}, {'selector': 'data/content'}, {'selector': '/data/~2content'},
    {'api': 'https://other.example.edu/api'}, {'api': 'http://gs.example.edu/api'},
    {'api': 'https://user:password@gs.example.edu/api'}, {'api': ''}, {'api': None}])
def test_bad_pointer_or_external_api_rejected(change):
    source = dict(SOURCE, **change)
    with pytest.raises(ValueError):
        rules.validate({'version': 1, 'sources': {'test': source}, 'policies': []}, {})


def test_json_api_required_and_nonjson_api_disallowed():
    missing = dict(SOURCE); missing.pop('api')
    for source in [missing, dict(SOURCE, format='html', selector='body'), dict(SOURCE, format='pdf', selector='')]:
        with pytest.raises(ValueError):
            rules.validate({'version': 1, 'sources': {'test': source}, 'policies': []}, {})


def test_json_pointer_decodes_keys_and_array_indices():
    source = dict(SOURCE, selector='/data/0/a~1b~0c')
    raw = json.dumps({'data': [{'a/b~c': '<p>真实正文</p>'}]}).encode()
    assert rules.fingerprint(raw, source)


def test_failed_json_check_preserves_previous_success():
    old = {'status': 'ok', 'last_attempt': '2026-10-14', 'last_success': '2026-10-14', 'hash': 'a'*64}
    with patch.object(rules.fetch, 'fetch', return_value=(b'{}', {'fetched_at': '2026-10-15'}, False)):
        result = rules.check_source(SOURCE, old, True, '2026-10-15')
    assert result['status'] == 'error' and result['last_success'] == '2026-10-14' and result['hash'] == old['hash']

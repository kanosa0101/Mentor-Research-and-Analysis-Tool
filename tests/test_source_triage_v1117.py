from datetime import timedelta

import requests

from crawler import source_discovery as discovery
from test_source_discovery_v18 import fixture, RAW, COLUMN, PARENT, CHILD, NOW


def test_no_activity_link_is_content_wait_not_transport_retry(tmp_path):
    _, calls, _ = fixture(tmp_path)
    def fetch(url, _):
        calls.append(url)
        return RAW if url == PARENT else b'<html><p>Empty activity column</p></html>'
    result = discovery.run(tmp_path, fetcher=fetch, now=NOW)
    record = result['candidates'][0]
    assert record['status'] == 'not_column' and record['reason_code'] == 'no_activity_links'
    assert result['summary']['content_wait'] == 1 and result['summary']['source_errors'] == 0
    discovery.run(tmp_path, fetcher=fetch, now=NOW+timedelta(hours=7))
    assert calls.count(CHILD) == 1
    discovery.run(tmp_path, fetcher=fetch, now=NOW+timedelta(days=7))
    assert calls.count(CHILD) == 2


def test_parent_change_wakes_content_wait_and_revalidates_child(tmp_path):
    _, _, _ = fixture(tmp_path)
    first = discovery.run(tmp_path, fetcher=lambda url, _: RAW if url == PARENT else b'<html>empty</html>', now=NOW)
    before = first['candidates'][0]
    second = discovery.run(tmp_path, fetcher=lambda url, _: RAW+b'<!-- updated -->' if url == PARENT else COLUMN,
                           now=NOW+timedelta(hours=7))
    current = second['candidates'][0]
    assert current['status'] == 'candidate' and current['activity_count'] == 2
    assert current['first_seen'] == before['first_seen'] and current['error_kind'] is None


def test_legacy_content_error_migrates_without_fetch_and_keeps_first_seen(tmp_path):
    _, calls, fetch = fixture(tmp_path)
    first = discovery.run(tmp_path, fetcher=lambda url, _: RAW if url == PARENT else b'<html>empty</html>', now=NOW)
    first['candidates'][0]['status'] = 'error'
    discovery.atomic_json(tmp_path/'cache/source-discovery.json', first)
    second = discovery.run(tmp_path, fetcher=fetch, now=NOW+timedelta(hours=7))
    assert calls == [PARENT]
    assert second['candidates'][0]['status'] == 'not_column'
    assert second['candidates'][0]['first_seen'] == first['candidates'][0]['first_seen']


def test_real_transport_failure_keeps_six_hour_recovery(tmp_path):
    fixture(tmp_path)
    def fetch(url, _):
        if url == PARENT:
            return RAW
        raise requests.ReadTimeout('fixture connection timeout')
    record = discovery.run(tmp_path, fetcher=fetch, now=NOW)['candidates'][0]
    assert record['status'] == 'error' and record['error_kind'] == 'transport'
    assert record['next_check_at'] == (NOW+timedelta(hours=6)).isoformat()

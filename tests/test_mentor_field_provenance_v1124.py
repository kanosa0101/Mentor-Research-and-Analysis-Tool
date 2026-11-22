from datetime import datetime, timezone

import pytest
import yaml

from crawler import mentor_fields


NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
PRIMARY = 'https://example.edu.cn/profile'
AUXILIARY = 'https://example.edu.cn/current-directory'


@pytest.mark.parametrize('case', ['captured', 'wrong_url', 'wrong_digest', 'wrong_value', 'manual', 'failed'])
def test_supplemental_field_observation_binds_only_its_captured_source(tmp_path, case):
    person = dict(name='张甲', school='example', dept='cs', slug='zhangjia', detail_url=PRIMARY)
    path = tmp_path / 'data/professors/example/cs/zhangjia.yaml'
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(person, allow_unicode=True), encoding='utf-8')
    mentor_fields.seed(tmp_path, NOW)

    person['supervisor'] = '硕导'
    person['provenance'] = {'supervisor': {'origin': 'manual' if case == 'manual' else 'crawled', 'source': AUXILIARY}}
    parsed = {'supervisor': '博导' if case == 'wrong_value' else '硕导', '_field_sources': {'supervisor': AUXILIARY}}
    source = dict(url=PRIMARY if case == 'wrong_url' else AUXILIARY, sha256='invalid' if case == 'wrong_digest' else 'b' * 64,
                  fetched_at='2026-11-22T23:50:00+00:00')
    kwargs = dict(parsed=parsed, source_url=PRIMARY, source_sha256='a' * 64, fetched_at=NOW.isoformat(),
                  verified_sources=[source], now=NOW)
    mentor_fields.observation(tmp_path, person, **kwargs)
    record = mentor_fields.read(tmp_path)['records']['example/cs/zhangjia']['fields']['supervisor']
    if case in ('captured', 'failed'):
        assert record['reason_code'] == 'field_verified'
        assert (record['source_url'], record['source_sha256'], record['fetched_at']) == (
            AUXILIARY, source['sha256'], source['fetched_at'])
    else:
        assert record['reason_code'] == 'record_now_complete'
        assert 'source_sha256' not in record

    if case == 'failed':
        mentor_fields.observation(tmp_path, person, **{**kwargs, 'error': ValueError('HTTP 503'), 'verified_sources': []})
        retained = mentor_fields.read(tmp_path)['records']['example/cs/zhangjia']['fields']['supervisor']
        assert retained == record

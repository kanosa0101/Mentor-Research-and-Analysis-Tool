import copy
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from crawler import admissions_util
from crawler import policy_revalidation as rules
from crawler.material_task_util import quality


NOW = datetime.now(timezone.utc).replace(microsecond=0)
DAY = NOW.astimezone(rules.CST).date().isoformat()
OLD = (NOW - timedelta(days=35)).astimezone(rules.CST).date().isoformat()
RAW = '<article>申请条件：本科在校生。\n报名材料：成绩单与签名申请表。</article>'.encode()


def setup(tmp_path, raw=RAW):
    source = dict(url='https://test.edu.cn/policy', format='html', selector='article')
    policy = dict(id='test-2027', school='test', dept='', level='school', title='2027招生要求',
                  year=2027, degree='master', route='exam', program='', program_code='',
                  published_at=None, reviewed_at=OLD, source_id='main',
                  review_hashes={'main': admissions_util.fingerprint(raw, source)},
                  fields={'eligibility': dict(text='本科生可申请', quote='申请条件：本科在校生。', locator='第一段')},
                  material_actions=[dict(id='prepare-form', label='准备表格', stage='application',
                                         instruction=dict(text='准备成绩单及签名表', quote='报名材料：成绩单与签名申请表。', locator='第二段'))])
    data = dict(version=1, sources={'main': source}, policies=[policy])
    (tmp_path / 'data').mkdir()
    write_data(tmp_path, data)
    (tmp_path / 'data/admissions_checks.json').write_text(json.dumps({'main': dict(status='ok', hash=policy['review_hashes']['main'], last_attempt=DAY, last_success=DAY)}))
    return data


def write_data(root, data):
    (root / 'data/admissions.yaml').write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')


def load_data(root):
    return yaml.safe_load((root / 'data/admissions.yaml').read_text(encoding='utf-8'))


def test_unchanged_review_reconfirms_each_quote_without_rewriting_human_date(tmp_path):
    data = setup(tmp_path)
    result = rules.run(tmp_path, fetcher=lambda _: RAW, now=NOW)
    policy = load_data(tmp_path)['policies'][0]
    assert result['confirmed'] == 1 and result['results'][0]['evidence'][0]['match_modes'] == {'main': 'contiguous'}
    assert policy['reviewed_at'] == OLD
    assert {k: v for k, v in policy.items() if k != 'revalidation'} == data['policies'][0]
    assert rules.valid_revalidation(policy, data['sources'])
    context = {'checks': json.loads((tmp_path / 'data/admissions_checks.json').read_text()), 'sources': data['sources']}
    assert quality(policy, context)['method'] == 'unchanged_source'
    assert quality(policy, context)['confirmed_at'] == DAY
    admissions_util.validate(load_data(tmp_path), {'test': set()})
    assert rules.run(tmp_path, fetcher=lambda _: pytest.fail('must honor 14-day next attempt'), now=NOW)['attempted'] == 0


def test_successful_noop_initializes_empty_state_without_fake_attempts(tmp_path):
    data = setup(tmp_path)
    data['policies'][0]['reviewed_at'] = DAY
    write_data(tmp_path, data)
    assert rules.run(tmp_path, fetcher=lambda _: pytest.fail('fresh policy should not fetch'), now=NOW)['attempted'] == 0
    state = json.loads((tmp_path / 'cache/policy_revalidation/state.json').read_text(encoding='utf-8'))
    assert state == {'version': 1, 'policies': {}}


def test_policy_edit_or_source_config_change_invalidates_attestation(tmp_path):
    data = setup(tmp_path)
    rules.run(tmp_path, fetcher=lambda _: RAW, now=NOW)
    policy = load_data(tmp_path)['policies'][0]
    context = {'checks': json.loads((tmp_path / 'data/admissions_checks.json').read_text()), 'sources': data['sources']}
    policy['fields']['eligibility']['text'] = '本科毕业生必须获得资格'
    assert not rules.valid_revalidation(policy, data['sources'])
    assert quality(policy, context)['state'] == 'review'
    published = rules.public_policy(policy, data['sources'])
    assert 'revalidation' not in published and published['revalidation_invalid']
    policy = load_data(tmp_path)['policies'][0]
    context['sources']['main']['url'] = 'https://test.edu.cn/replaced'
    assert quality(policy, context)['state'] == 'review'


def test_source_failure_change_and_stale_check_override_fresh_attestation(tmp_path):
    data = setup(tmp_path)
    rules.run(tmp_path, fetcher=lambda _: RAW, now=NOW)
    policy = load_data(tmp_path)['policies'][0]
    checks = json.loads((tmp_path / 'data/admissions_checks.json').read_text())
    for update, expected in [({'status': 'error'}, 'error'), ({'hash': 'f' * 64}, 'changed'),
                             ({'last_success': OLD}, 'stale')]:
        changed = copy.deepcopy(checks)
        changed['main'].update(update)
        assert quality(policy, {'checks': changed, 'sources': data['sources']})['state'] == expected


def test_changed_source_cannot_renew_even_when_quote_still_matches(tmp_path):
    data = setup(tmp_path)
    result = rules.run(tmp_path, fetcher=lambda _: RAW.replace(b'</article>', b' changed</article>'), now=NOW)
    assert result['review_required'] == 1 and result['confirmed'] == 0
    assert result['results'][0]['reasons'][0]['kind'] == 'source_changed'
    assert load_data(tmp_path)['policies'][0] == data['policies'][0]


def test_missing_quote_is_not_replaced_with_ai_or_partial_match(tmp_path):
    data = setup(tmp_path)
    data['policies'][0]['fields']['eligibility']['quote'] = '不存在的额外限制'
    write_data(tmp_path, data)
    result = rules.run(tmp_path, fetcher=lambda _: RAW, now=NOW)
    assert result['review_required'] == 1
    assert result['results'][0]['reasons'][0]['kind'] == 'missing_quote'


def test_unknown_attachment_blocks_even_if_html_hash_is_unchanged(tmp_path):
    raw = RAW.replace(b'</article>', b'<a href="form.docx">form</a></article>')
    setup(tmp_path, raw)
    result = rules.run(tmp_path, fetcher=lambda _: raw, now=NOW)
    assert result['review_required'] == 1
    reason = result['results'][0]['reasons'][0]
    assert reason['kind'] == 'unbound_attachment' and reason['url'] == 'https://test.edu.cn/form.docx'


def test_failure_backoff_and_changed_observation_wake_queue(tmp_path):
    setup(tmp_path)
    def fail(_):
        raise TimeoutError('official source unavailable')
    first = rules.run(tmp_path, fetcher=fail, now=NOW)
    assert first['retry'] == 1
    assert len(first['results'][0]['reasons']) == 1
    second = rules.run(tmp_path, fetcher=fail, now=NOW + timedelta(minutes=5), force=True)
    assert second['results'][0]['pending_since'] == first['results'][0]['pending_since']
    assert rules.run(tmp_path, fetcher=lambda _: pytest.fail('retry must wait'), now=NOW + timedelta(minutes=10))['attempted'] == 0
    checks_path = tmp_path / 'data/admissions_checks.json'
    checks = json.loads(checks_path.read_text())
    checks['main']['status'] = 'ok'
    checks_path.write_text(json.dumps(checks))
    recovered = rules.run(tmp_path, fetcher=lambda _: RAW, now=NOW)
    assert recovered['confirmed'] == 1 and 'pending_since' not in recovered['results'][0]


def test_concurrent_policy_editor_is_not_overwritten(tmp_path):
    data = setup(tmp_path)
    def edit(_):
        changed = copy.deepcopy(data)
        changed['policies'][0]['title'] = '另一位维护者更新的政策标题'
        write_data(tmp_path, changed)
        return RAW
    with pytest.raises(ValueError, match='未覆盖'):
        rules.run(tmp_path, fetcher=edit, now=NOW)
    assert load_data(tmp_path)['policies'][0]['title'] == '另一位维护者更新的政策标题'


def test_ordered_paragraphs_match_every_fragment_and_keep_order():
    assert rules.quote_match('第一段的要求\n最后段的说明', '第一段的要求 中间其他内容 最后段的说明') == 'ordered_paragraphs'
    assert not rules.quote_match('最后段的说明\n第一段的要求', '第一段的要求 最后段的说明')
    assert not rules.quote_match('第一段的要求\n不存在的限制\n最后段的说明', '第一段的要求 最后段的说明')


def docx_bytes(text):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>')
    return stream.getvalue()


def test_registered_docx_is_checked_and_content_change_blocks(tmp_path):
    raw = RAW.replace(b'</article>', b'<a href="form.docx">form</a></article>')
    data = setup(tmp_path, raw)
    form = docx_bytes('本人签字并确认表格内容真实')
    data['sources']['form'] = dict(url='https://test.edu.cn/form.docx', format='docx', selector='', label='申请表')
    policy = data['policies'][0]
    policy['review_hashes']['form'] = admissions_util.fingerprint(form, data['sources']['form'])
    policy['material_actions'][0]['instruction'].update(quote='本人签字并确认表格内容真实', source_ids=['form'])
    write_data(tmp_path, data)
    admissions_util.validate(data, {'test': set()})
    result = rules.run(tmp_path, fetcher=lambda source: form if source['format'] == 'docx' else raw, now=NOW)
    assert result['confirmed'] == 1
    result = rules.run(tmp_path, fetcher=lambda source: docx_bytes('本人签字并确认表格内容真实，另加推荐信') if source['format'] == 'docx' else raw,
                       now=NOW, force=True)
    assert result['review_required'] == 1
    assert any(r['kind'] == 'source_changed' and r['source_id'] == 'form' for r in result['results'][0]['reasons'])
    assert 'revalidation' not in load_data(tmp_path)['policies'][0]


def test_attachment_parser_rejects_shell_or_invalid_zip():
    with pytest.raises(ValueError):
        admissions_util.fingerprint(b'<html>download failed</html>', dict(format='docx'))


def test_missing_extra_or_forged_attestation_fields_fail_schema(tmp_path):
    setup(tmp_path)
    rules.run(tmp_path, fetcher=lambda _: RAW, now=NOW)
    value = load_data(tmp_path)['policies'][0]['revalidation']
    for key, replacement in [('checked_at', '2026-11-16T09:00:00'), ('method', 'ai-guessed'), ('evidence_count', 0), ('source_hashes', {})]:
        changed = dict(value, **{key: replacement})
        with pytest.raises(ValueError):
            rules.validate_revalidation(changed)

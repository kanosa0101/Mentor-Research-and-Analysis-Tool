import json

from crawler import ai_review


def test_shortened_materials_are_not_repaired_by_full_quote_or_instruction(tmp_path, monkeypatch):
    text = '须提交两封副教授及以上专家亲笔签字推荐信。仅用EMS寄送，11月27日12时前送达。'
    fields = {
        'materials': dict(value='须提交两封推荐信。', quote=text.split('。')[0] + '。'),
        'application_requirements': dict(value=text, quote=text),
        'deadline_0': dict(value={'label': '材料送达截止', 'at': '2026-11-27T12:00:00+08:00'}, quote='11月27日12时前送达。'),
    }
    monkeypatch.setattr(ai_review.ai_evidence, 'config', lambda _: {'model': 'fixture'})
    monkeypatch.setattr(ai_review.ai_evidence, 'reserve_request', lambda *args: None)

    def complete(settings, messages, **kwargs):
        data = json.loads(messages[1]['content'])
        assert data['official_text'] == text
        assert data['proposed_fields'] == {key: field['value'] for key, field in fields.items()}
        assert data['proposed_fields']['materials'] == '须提交两封推荐信。'
        return json.dumps(dict(decision='manual', issues=['材料要求缺少副教授及以上和亲笔签字限制'],
            checks=[dict(field=key, consistent=key != 'materials') for key in fields])), {}

    monkeypatch.setattr(ai_review.ai_transport, 'completion', complete)
    result = ai_review.check(tmp_path, 'https://cs.pku.edu.cn/notice.htm', text, fields)
    assert result['decision'] == 'manual'
    assert result['checks'][0]['quote'] == fields['materials']['quote']
    assert result['input_fields_sha256'] == ai_review.fields_hash(fields)


def test_nested_business_values_and_date_offsets_are_not_flattened_or_truncated(tmp_path, monkeypatch):
    text = '2026年11月25日17:00网上报名截止。11月27日12:00材料送达截止。'
    value = dict(materials=['推荐信'], instruction=text,
        deadlines=[{'at': '2026-11-25T17:00:00+08:00'}, {'at': '2026-11-27T12:00:00+08:00'}],
        application_url='https://admission.pku.edu.cn/applications/')
    fields = {'application_procedure': dict(value=value, quote=text)}
    monkeypatch.setattr(ai_review.ai_evidence, 'config', lambda _: {'model': 'fixture'})
    monkeypatch.setattr(ai_review.ai_evidence, 'reserve_request', lambda *args: None)

    def complete(settings, messages, **kwargs):
        data = json.loads(messages[1]['content'])
        assert data['proposed_fields']['application_procedure'] == value
        assert data['official_text'] == text
        return json.dumps(dict(decision='consistent', issues=[],
            checks=[dict(field='application_procedure', consistent=True)])), {}

    monkeypatch.setattr(ai_review.ai_transport, 'completion', complete)
    result = ai_review.check(tmp_path, 'https://cs.pku.edu.cn/notice.htm', text, fields)
    assert result['checks'][0]['quote'] == text
    assert fields['application_procedure']['value'] == value

import json
from unittest.mock import Mock

import pytest

from crawler import ai_review


def test_complete_chinese_evidence_is_sent_without_redundant_model_echo(tmp_path, monkeypatch):
    monkeypatch.setenv('MENTOR_AI_ENABLED', 'true')
    monkeypatch.setenv('MENTOR_AI_API_KEY', 'fixture-secret')
    quote = '完整的申请条件与材料要求。' * 420
    fields = {'procedure': {'value': quote, 'quote': quote}}
    payload = {'decision': 'consistent', 'issues': [],
               'checks': [{'field': 'procedure', 'consistent': True}]}
    client = Mock()
    response = client.post.return_value
    response.status_code = 200
    response.headers = {'Content-Type': 'application/json'}
    response.iter_content.return_value = [json.dumps({'choices': [{
        'message': {'content': json.dumps(payload, ensure_ascii=False)},
        'finish_reason': 'stop'}]}, ensure_ascii=False).encode()]
    result = ai_review.check(tmp_path, 'https://cs.pku.edu.cn/info/1051/6700.htm',
                             quote, fields, session=client)
    sent = client.post.call_args.kwargs['json']
    assert sent['max_tokens'] == 6000
    proposed = json.loads(sent['messages'][1]['content'])
    assert proposed['official_text'] == quote
    assert proposed['proposed_fields'] == {'procedure': quote}
    assert result['checks'][0]['quote'] == quote
    assert result['checks'][0]['consistent'] is True
    assert len(json.dumps(payload, ensure_ascii=False)) < 150
    assert result['transport']['max_tokens'] == sent['max_tokens']
    assert json.loads((tmp_path / 'cache/ai-evidence-usage.json').read_text())['requests'] == 1


TEXT = '仅限本校本科生申请。不接受已毕业申请人。须提交成绩单。'
FIELDS = {
    'eligibility': dict(value='仅限本校本科生申请。不接受已毕业申请人。', quote='仅限本校本科生申请。不接受已毕业申请人。'),
    'materials': dict(value=['成绩单'], quote='须提交成绩单。'),
}


def payload(checks=None, decision='consistent', issues=None):
    return dict(decision=decision, issues=issues or [], checks=checks if checks is not None else [
        dict(field=key, consistent=True) for key in FIELDS])


@pytest.mark.parametrize('checks', [
    [], [dict(field='eligibility', consistent=True)],
    [dict(field='eligibility', consistent=True), dict(field='eligibility', consistent=True)],
    [dict(field='eligibility', consistent=True), dict(field='unknown', consistent=True)],
    [dict(field='eligibility', consistent=True), dict(field=[], consistent=True)],
    [dict(field='eligibility', consistent=True), dict(field='materials')],
    [dict(field='eligibility', consistent=True), dict(field='materials', consistent='true')],
    [dict(field='eligibility', consistent=True), dict(field='materials', consistent=1)],
    [dict(field='eligibility', consistent=True), dict(field='materials', consistent=None)],
    [dict(field='eligibility', consistent=True), dict(field='materials', quote='须提交成绩单。')],
    [dict(field='eligibility', consistent=True), dict(field='materials', consistent=True, quote='extra')],
])
def test_incomplete_duplicate_unknown_nonboolean_and_old_protocol_rejected(checks):
    with pytest.raises(ValueError):
        ai_review.bind_response(payload(checks), TEXT, FIELDS)


@pytest.mark.parametrize('response', [
    payload([dict(field='eligibility', consistent=False), dict(field='materials', consistent=True)]),
    payload(issues=['存在限制遗漏']), payload(decision='manual'),
])
def test_overall_decision_must_match_every_field_and_issue(response):
    with pytest.raises(ValueError, match='冲突'):
        ai_review.bind_response(response, TEXT, FIELDS)


def test_manual_semantic_conflict_preserves_original_evidence():
    response = payload([dict(field='eligibility', consistent=False), dict(field='materials', consistent=True)],
                       decision='manual', issues=['提议条件遗漏了已毕业申请人限制'])
    result = ai_review.bind_response(response, TEXT, FIELDS)
    assert result['decision'] == 'manual' and result['checks'][0]['consistent'] is False
    assert result['checks'][0]['quote'] == FIELDS['eligibility']['quote']
    assert 'quote' not in response['checks'][0]


@pytest.mark.parametrize('quote', ['外校学生均可报名', '', ' \n ', 123, None])
def test_unbound_input_quote_never_consumes_ai_budget(tmp_path, monkeypatch, quote):
    monkeypatch.setattr(ai_review.ai_evidence, 'reserve_request', lambda *a: pytest.fail('invalid evidence consumed quota'))
    monkeypatch.setattr(ai_review.ai_transport, 'completion', lambda *a, **kw: pytest.fail('invalid evidence sent to provider'))
    with pytest.raises(ValueError, match='原文摘录'):
        ai_review.check(tmp_path, 'https://cs.pku.edu.cn/info/1051/6700.htm', TEXT,
                        dict(FIELDS, eligibility=dict(value='不完整条件', quote=quote)))


def test_locally_stored_evidence_tampering_is_rejected():
    result = ai_review.bind_response(payload(), TEXT, FIELDS)
    result['checks'][0]['quote'] = '仅限本校本科生申请。'
    with pytest.raises(ValueError, match='证据不一致'):
        ai_review.validate(result, TEXT, FIELDS)


def test_all_business_values_are_sent_and_quotes_remain_bound_locally(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_review.ai_evidence, 'config', lambda _: dict(model='fixture'))
    monkeypatch.setattr(ai_review.ai_evidence, 'reserve_request', lambda *a: None)
    text = '2026年托福新计分标准：总分须达到5分。'
    fields = {'eligibility': dict(value=text, quote=text)}
    captured = []
    def complete(settings, messages, **kwargs):
        captured.extend(messages)
        return json.dumps(payload([dict(field='eligibility', consistent=True)])), {}
    monkeypatch.setattr(ai_review.ai_transport, 'completion', complete)
    result = ai_review.check(tmp_path, 'https://cs.pku.edu.cn/info/1051/6700.htm', text, fields)
    sent = json.loads(captured[1]['content'])
    assert sent['official_text'] == text
    assert sent['proposed_fields'] == {'eligibility': text}
    assert result['checks'] == [dict(field='eligibility', consistent=True, quote=text)]


def test_field_contract_does_not_override_a_reported_eligibility_omission():
    fields = dict(FIELDS, attachment_0=dict(value=TEXT, quote=TEXT))
    response = dict(decision='manual', issues=['eligibility遗漏申请人身份限制，附件完整不能补齐业务字段遗漏'],
                    checks=[dict(field=key, consistent=key != 'eligibility') for key in fields])
    result = ai_review.bind_response(response, TEXT, fields)
    assert result['decision'] == 'manual' and result['checks'][0]['consistent'] is False
    assert result['checks'][-1]['consistent'] is True
    response['decision'] = 'consistent'
    with pytest.raises(ValueError, match='冲突'):
        ai_review.bind_response(response, TEXT, fields)

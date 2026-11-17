import hashlib
import json
from datetime import timedelta

import pytest
import requests

from crawler import ai_review, automatic_evidence, automatic_review as automatic, opportunity_review as review, policy_intake
from test_automatic_review_v18 import CONFIGS, HTML, NOW, URL, accepted, extractive_advice, setup
from test_complete_evidence_v1116 import POLICY_HTML, docx, policy_setup


def finding(args, field, quote, *, kind='omission'):
    _, _, text, fields = args
    issues = [dict(field=field, kind=kind, source_quote=quote, detail='该要求未保留')]
    checks = [dict(field=key, consistent=key != field) for key in fields]
    original = ai_review.bind_response(dict(decision='manual', issues=issues, checks=checks), text, fields)
    return dict(accepted(*args), **original)


def test_counterevidence_is_source_bound_persistent_and_at_most_once(tmp_path):
    clause = '须提交两封副教授签署的推荐信及有效成绩单。'
    fields = {'materials': dict(value=[clause], quote=clause)}
    args = (tmp_path, URL, clause, fields)
    first = finding(args, 'materials', clause)
    calls = []

    def second(*inputs, counterevidence):
        assert counterevidence == [dict(field='materials', source_quote=clause)]
        calls.append(1)
        return first  # The second reviewer still refused. Its refusal remains binding.

    result = ai_review.recheck(*args, first, second, version='v1')
    assert result['decision'] == 'manual'
    assert result['counterevidence_review']['first_issues'] == first['issues']
    assert ai_review.recheck(*args, first, second, version='v1') == result
    assert calls == [1]
    assert ai_review.recheck(*args, first, second, version='v2')['decision'] == 'manual'
    assert calls == [1, 1]


@pytest.mark.parametrize('case', ['actual_omission', 'mismatch', 'ambiguity', 'other_field'])
def test_complete_quote_cannot_overrule_a_real_error_or_wrong_field(tmp_path, case):
    clause = '须提交两封副教授签署的推荐信及有效成绩单。'
    materials = clause if case in ('mismatch', 'ambiguity') else '须提交推荐信。'
    fields = {'materials': dict(value=materials, quote=clause),
              'application_requirements': dict(value=clause, quote=clause)}
    args = (tmp_path, URL, clause, fields)
    first = finding(args, 'materials', clause, kind=case if case in ('mismatch', 'ambiguity') else 'omission')
    assert ai_review.recheck(*args, first, lambda *a: pytest.fail('real problem reached recheck'), version='v1') == first
    assert not (tmp_path/'cache/ai-content-recheck.json').exists()


def test_partial_issue_excerpt_cannot_hide_a_real_omission(tmp_path):
    full = '须提交两封由副教授签署的推荐信，推荐信原件须密封并在封口处骑缝签字。'
    partial = '须提交两封由副教授签署的推荐信'
    fields = {'materials': dict(value=partial + '。', quote=full)}
    args = tmp_path, URL, full, fields
    first = finding(args, 'materials', partial)
    detail = '漏掉推荐信原件必须密封并骑缝签字的限制'
    first['findings'][0]['detail'] = detail
    first['issues'] = ['materials：' + partial + '｜' + detail]

    assert ai_review.recheck(
        *args, first, lambda *a, **kw: pytest.fail('a real omission reached the second call'), version='v1'
    ) == first
    assert not (tmp_path/'cache/ai-content-recheck.json').exists()


def test_only_budget_refused_before_sending_keeps_recheck_available(tmp_path):
    clause = '须提交两封副教授签署的推荐信及有效成绩单。'
    fields = {'materials': dict(value=clause, quote=clause)}
    args = tmp_path, URL, clause, fields
    first = finding(args, 'materials', clause)

    def quota(*args, **kwargs):
        raise ValueError('已达到AI每日调用上限；未发出新请求')

    with pytest.raises(ValueError, match='每日调用上限'):
        ai_review.recheck(*args, first, quota, version='v1')

    def sent_but_failed(*args, **kwargs):
        raise requests.Timeout('模拟已经开始请求后超时')

    with pytest.raises(requests.Timeout):
        ai_review.recheck(*args, first, sent_but_failed, version='v1')
    assert ai_review.recheck(*args, first, lambda *a: pytest.fail('indeterminate request repeated'), version='v1') == first


def test_policy_budget_wait_preserves_first_result_and_schedules_recheck(policy_setup):
    calls = []
    clause = '须提交个人简历、加盖公章的成绩单和英语证明。'

    def checker(*args, counterevidence=()):
        calls.append(counterevidence)
        if len(calls) == 1:
            return finding(args, 'materials', clause)
        if len(calls) == 2:
            raise ValueError('已达到AI每日调用上限；未发出新请求')
        assert counterevidence == [dict(field='materials', source_quote=clause)]
        return accepted(*args)

    kw = dict(fetcher=lambda _: POLICY_HTML, checker=checker)
    first = policy_intake.run(policy_setup, now=NOW, **kw)
    assert first['budget_wait'] == 1
    assert policy_intake.run(policy_setup, now=NOW+timedelta(hours=1), **kw)['attempted'] == 0
    approved = policy_intake.run(policy_setup, now=NOW+timedelta(days=1), publish=False, **kw)
    assert approved['counts'] == {'eligible': 1}
    assert approved['results'][0]['ai_reused']
    result = policy_intake.run(policy_setup, now=NOW+timedelta(days=1), fetcher=kw['fetcher'],
                               checker=lambda *a: pytest.fail('same complete proposal paid twice'))
    assert result['published'] == 1 and len(calls) == 3
    assert result['results'][0]['ai_reused']


def test_activity_reopens_when_same_complete_version_recovers_after_fetch_error(setup):
    root, queue, _ = setup
    drafts = review.read_queue(queue)
    draft = drafts['drafts'][0]
    assert review.fetch_evidence(draft, queue, lambda _: HTML, now=NOW, complete=True) == HTML
    complete = draft['fetch']
    draft['fetch'] = dict(complete, status='evidence_error', error_kind='evidence', error_code='image_evidence_required')
    draft['automatic_review'] = dict(policy_version=automatic.POLICY_VERSION, state='manual_required',
        content_sha256=complete['content_sha256'], source_sha256=complete['sha256'],
        source_binding=automatic.source_binding(draft, CONFIGS), fetch_binding=automatic.fetch_binding(draft['fetch']),
        input_revision=automatic.protected(draft), reasons=['同版本原文仍需图片证据'])
    draft['fetch'] = complete
    review.atomic_json(queue, drafts)
    result = automatic.run(root, queue, CONFIGS, publish=True, now=NOW, fetcher=lambda _: HTML, checker=accepted)
    assert result['counts'] == {'published': 1}


def test_activity_same_verdict_can_advance_on_next_day(setup, monkeypatch):
    root, queue, process = setup
    assert process(publish=False)['state'] == 'eligible'
    monkeypatch.setattr(automatic.util, 'today', lambda: NOW.date()+timedelta(days=1))
    result = process(now=NOW+timedelta(days=1), checker=lambda *a: pytest.fail('same applicant values paid twice'))
    assert result['state'] == 'published'


def test_scheduled_activity_leaves_ambiguous_source_without_using_advice(setup, monkeypatch):
    root, queue, _ = setup
    raw = HTML.replace(b'</article>', '<p>具体入营安排另行通知。</p></article>'.encode())
    monkeypatch.setattr(automatic.ai_evidence, 'suggest', lambda *a: pytest.fail('scheduled advice reached paid path'))
    args = dict(limit=1, publish=True, now=NOW, fetcher=lambda _: raw,
                checker=lambda *a: pytest.fail('ambiguous scope reached publication reviewer'))
    first = automatic.run(root, queue, CONFIGS, **args)
    assert first['counts'] == {'manual_required': 1}
    draft = review.read_queue(queue)['drafts'][0]
    assert not draft.get('ai_suggestions') and 'assistance' not in draft['automatic_review']
    assert automatic.run(root, queue, CONFIGS, **args)['counts'] == {'skipped': 1}
    requested = automatic.run(root, queue, CONFIGS, assistant=extractive_advice, **args)
    assert requested['results'][0]['assistance']['state'] == 'ready'


def test_named_official_attachment_moves_materials_into_proposal(policy_setup):
    replacement = '申请材料见附件。'.encode()
    raw = POLICY_HTML.replace('须提交个人简历、加盖公章的成绩单和英语证明。'.encode(), replacement)
    raw = raw.replace(b'</article>', b'<a href="/materials.docx">materials.docx</a></article>')
    multiple = docx('申请材料</w:t></w:r></w:p><w:p><w:r><w:t>须提交两份签字推荐信及盖章的成绩单。')
    row = policy_intake.candidates(policy_setup)[0]
    document = policy_intake.collect(raw, row, policy_setup/'cache', lambda *a: pytest.fail(), lambda *a: multiple)
    proposal = policy_intake.prepare(policy_setup, row, raw, document, NOW)
    policy_intake.validate_display_checks(proposal)
    policy = proposal['policy']
    material = policy['fields']['materials']
    assert '两份签字推荐信及盖章' in material['text']
    assert policy['review_hashes'][material['source_ids'][0]] == hashlib.sha256(multiple).hexdigest()
    assert proposal['checks']['materials']['value'] == material['text']
    assert '发送至' in proposal['checks']['application_requirements']['value']
    document['documents'].append(document['documents'][0])
    with pytest.raises(automatic_evidence.EvidenceError, match='未取得唯一'):
        policy_intake.prepare(policy_setup, row, raw, document, NOW)


def test_project_experience_remains_eligibility_and_true_special_program_is_blocked(policy_setup):
    sentence = '须具备主持或作为关键技术骨干参与国家重大专项、重要工程项目的经历。'
    raw = POLICY_HTML.replace('申请考核面向取得硕士学位的申请人。'.encode(),
                              ('申请考核面向取得硕士学位的申请人。' + sentence).encode())
    path = policy_setup/'cache/policy_intake/state.json'
    path.parent.mkdir(parents=True)
    previous = dict(status='manual_required', reason='涉及批次、变更或专项对象，需独立划分政策范围',
                    title=policy_intake.candidates(policy_setup)[0]['title'], first_seen=NOW.isoformat(),
                    policy_version=policy_intake.VERSION, next_attempt_at=(NOW+timedelta(hours=24)).isoformat())
    path.write_text(json.dumps(dict(version=1, records={URL: previous})), encoding='utf-8')
    proposal = policy_intake.run(policy_setup, now=NOW, publish=False, fetcher=lambda _: raw, checker=accepted)
    assert proposal['counts'] == {'eligible': 1}
    records = json.loads(path.read_text(encoding='utf-8'))['records']
    assert sentence in records[URL]['proposed_policy']['fields']['eligibility']['text']
    special = raw.replace(b'</article>', '本专项仅面向特定报名对象。'.encode() + b'</article>')
    refusal = policy_intake.run(policy_setup, now=NOW+timedelta(days=1), fetcher=lambda _: special,
                                checker=lambda *a: pytest.fail('special scope reached AI'))
    assert refusal['manual_required'] == 1 and '专项' in refusal['results'][0]['reason']

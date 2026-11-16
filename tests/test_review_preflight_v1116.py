import copy
from datetime import datetime, timedelta, timezone

import pytest

from crawler import automatic_review, opportunity_review as review, review_preflight as preflight, review_queue

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
CONFIGS = [dict(url='https://cs.example.edu.cn/admissions/', school='example', dept='cs')]


def html(title, body):
    return ('<html><meta charset="utf-8"><title>'+title+'</title><article><h1>'+title+'</h1>'+body+'</article></html>').encode()


PAST = html('2022年计算机夏令营报名通知', '<p>申请对象为相关专业本科生，报名截止时间为2022年6月30日。申请材料包括成绩单和个人简历。</p>')
CURRENT = html('2027年计算机冬令营报名通知', '<p>申请对象为2028届计算机专业本科生，报名截止时间为2026年12月31日。申请材料包括成绩单和个人简历。</p>')


def fixture(root, raw=PAST, title='2022年计算机夏令营报名通知', name='a'):
    path = root/'cache/opportunity_review.json'
    monitor = dict(candidates=[dict(url=CONFIGS[0]['url']+name+'.html', source=CONFIGS[0]['url'],
        school='example', dept='cs', unit='计算机学院', title=title, first_seen=NOW.isoformat(), last_seen=NOW.isoformat())])
    review.sync(monitor,path,CONFIGS,fetcher=lambda _:raw,now=NOW)
    return path,review.read_queue(path)['drafts'][-1]


def test_historical_body_is_triaged_before_ai_with_original_facts_retained(tmp_path):
    path,draft=fixture(tmp_path)
    original=copy.deepcopy(draft)
    outcome=automatic_review.run(tmp_path,path,CONFIGS,now=NOW,publish=False,
        fetcher=lambda _:pytest.fail('archived source should not be fetched'),
        checker=lambda *a:pytest.fail('historical item consumed AI'),assistant=lambda *a:pytest.fail('historical item consumed AI'))
    stored=review.read_queue(path)['drafts'][0]
    assert review.triage(stored)['classification']=='historical'
    assert stored['item']==original['item'] and stored['quotes']==original['quotes']
    assert stored['first_seen']==original['first_seen']
    assert len(stored['preflight']['evidence'])>=2 and outcome['counts']=={'skipped':1}
    assert not (tmp_path/'cache/ai-evidence-usage.json').exists()


def test_listing_title_alone_cannot_archive_current_body(tmp_path):
    path,draft=fixture(tmp_path,CURRENT)
    decision=preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)
    assert decision['classification']=='unknown' and decision['priority_hint']=='target_cohort'


@pytest.mark.parametrize('extra', ['<p>本项目延期，另行通知。</p>', '<p>下一批报名开始于2027年1月1日。</p>'])
def test_ambiguous_or_future_body_prevents_archive(tmp_path,extra):
    path,draft=fixture(tmp_path,PAST.replace(b'</article>',extra.encode()+b'</article>'))
    assert preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)['classification']=='unknown'


@pytest.mark.parametrize('kind', ['portal','directory'])
def test_official_navigation_needs_body_evidence(tmp_path,kind):
    title='夏令营网上报名系统' if kind=='portal' else '夏令营'
    body=('<p>欢迎使用夏令营网上报名系统。请用用户名登录，注册后进入申请管理。</p>' if kind=='portal' else
          '<p>本栏目汇集本学院历年优秀大学生夏令营活动资料，为本科生提供各年度活动通知的公开检索入口，请进入具体公告查看详情。</p>'+''.join(f'<a href="{year}.html">{year}年夏令营报名通知</a>' for year in (2024,2025,2026)))
    path,draft=fixture(tmp_path,html(title,body),title)
    decision=preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)
    assert decision['classification']=='irrelevant' and decision['reason_code']=='navigation_or_portal'


def test_generic_title_can_still_be_a_real_announcement(tmp_path):
    old_links=''.join(f'<a href="{year}.html">{year}年夏令营报名通知</a>' for year in (2024,2025,2026))
    raw=html('夏令营','<p>申请对象为2028届本科生，申请材料须提交成绩单，报名截止2026年12月31日，请使用报名系统申请。</p>'+old_links)
    path,draft=fixture(tmp_path,raw,'夏令营')
    assert preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)['classification']=='unknown'


@pytest.mark.parametrize('field,value', [('notes','maintainer note'),('manual_edit',{'at':'2026-11-15'}),
    ('quotes',['human quote']),('reviewed_fields',{'deadline':{'quote':'human'}}),
    ('triage',{'classification':'current','reason':'maintainer scope'})])
def test_human_fields_and_triage_are_never_overwritten(tmp_path,field,value):
    path,draft=fixture(tmp_path)
    draft[field]=value;review.atomic_json(path,{'version':1,'drafts':[draft]})
    preflight.run(tmp_path,path,CONFIGS,now=NOW)
    stored=review.read_queue(path)['drafts'][0]
    assert stored[field]==value and stored['item']==draft['item']
    assert stored['preflight']['reason_code']=='human_protected'
    assert review.triage(stored).get('classification')!='historical'


@pytest.mark.parametrize('case',['stale','mismatch','source_error'])
def test_unverified_evidence_does_not_archive(tmp_path,case):
    path,draft=fixture(tmp_path)
    if case=='stale':draft['fetch']['checked_at']=(NOW-timedelta(hours=25)).isoformat()
    elif case=='mismatch':(path.parent/'opportunity_evidence'/(draft['fetch']['sha256']+'.html')).write_bytes(b'changed')
    else:draft['fetch']['status']='error'
    assert preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)['classification']=='unknown'


def test_body_revision_or_human_change_invalidates_machine_triage(tmp_path):
    path,draft=fixture(tmp_path)
    preflight.run(tmp_path,path,CONFIGS,now=NOW)
    original=review.read_queue(path)['drafts'][0]
    assert review.triage(original)['classification']=='historical'
    for field,value in [('notes','edited'),('fetch',dict(original['fetch'],sha256='0'*64))]:
        changed=copy.deepcopy(original);changed[field]=value
        assert review.triage(changed).get('classification')!='historical'


def test_idempotent_history_and_refresh_after_stale_snapshot(tmp_path):
    path,draft=fixture(tmp_path)
    draft['fetch']['checked_at']=(NOW-timedelta(days=2)).isoformat();review.atomic_json(path,{'version':1,'drafts':[draft]})
    preflight.run(tmp_path,path,CONFIGS,now=NOW)
    assert not preflight.run(tmp_path,path,CONFIGS,now=NOW)['changed']
    queue=review.read_queue(path);queue['drafts'][0]['fetch']['checked_at']=NOW.isoformat();review.atomic_json(path,queue)
    preflight.run(tmp_path,path,CONFIGS,now=NOW)
    stored=review.read_queue(path)['drafts'][0]
    assert review.triage(stored)['classification']=='historical' and len(stored['preflight_history'])==1


def test_current_cohort_and_winter_precede_unknown_queue(tmp_path):
    path,draft=fixture(tmp_path,CURRENT,'2027年计算机冬令营报名通知')
    unknown=copy.deepcopy(draft);unknown.update(id='unknown',source_url=CONFIGS[0]['url']+'unknown.html')
    unknown['item']['title']='科研项目';unknown['fetch']['status']='error'
    review.atomic_json(path,{'version':1,'drafts':[unknown,draft]})
    preflight.run(tmp_path,path,CONFIGS,now=NOW)
    assert review_queue.ordered(review.read_queue(path),now=NOW,root=tmp_path)[0]['id']==draft['id']


def test_legacy_errors_preserve_backoff_and_ledger_without_guessing_cause(tmp_path):
    path,draft=fixture(tmp_path,CURRENT)
    draft['automatic_review']=dict(state='retry',attempts=3,failures=2,next_attempt_at='2026-11-17T00:05:00+00:00',
        reasons=['AI辅助公开证据暂时不可用'],assistance={'state':'failed','reason':'AI辅助公开证据暂时不可用'})
    review.atomic_json(path,{'version':1,'drafts':[draft]})
    ledger=tmp_path/'cache/ai-evidence-usage.json';ledger.write_text('{"requests":10}')
    before=ledger.read_bytes();preflight.run(tmp_path,path,CONFIGS,now=NOW)
    stored=review.read_queue(path)['drafts'][0]
    auto=stored['automatic_review']
    assert auto['error_code']=='legacy_unclassified' and auto['error_phase']=='legacy'
    assert auto['attempts']==3 and auto['failures']==2 and auto['next_attempt_at']==draft['automatic_review']['next_attempt_at']
    assert stored['automatic_review_history']==[draft['automatic_review']] and ledger.read_bytes()==before


def test_budget_wait_and_local_permission_are_distinct_from_transport():
    old=dict(state='budget_wait',reasons=['已达到AI每日调用上限；未发出新请求'],next_attempt_at='2026-11-17T00:05:00+00:00')
    classified=preflight.classify_old_error(old)
    assert classified['error_code']=='daily_budget_exhausted' and classified['next_attempt_at']==old['next_attempt_at']
    error=automatic_review.service_failure(PermissionError('private path must not appear'))
    assert error==dict(error_code='local_permission_denied',retryable=False,error_phase='local_storage')


def test_old_heading_and_different_year_body_require_review(tmp_path):
    raw=PAST.replace('2022年6月30日'.encode(),'2025年6月30日'.encode())
    path,draft=fixture(tmp_path,raw)
    assert preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)['classification']=='unknown'


def test_old_cohort_corrobates_old_camp_without_inventing_full_deadline(tmp_path):
    raw=html('2022年计算暑期研修班', '<p>国内各高校计算机专业在校本科生（拟2023年毕业）可申请。</p><p>报名时间：即日起至6月20日。未入选学生不再另行通知。</p>')
    path,draft=fixture(tmp_path,raw)
    decision=preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)
    assert decision['classification']=='historical'
    assert any('2023年毕业' in entry['quote'] for entry in decision['evidence'])
    assert not draft['item'].get('deadline')


def test_empty_registration_column_is_not_an_activity(tmp_path):
    raw=html('夏令营网上报名系统','<p>网站首页 网上报名 夏令营网上报名系统 站内搜索 共0条 0/0 本站为研究生院招生办公室官方信息发布平台，欢迎访问招生相关栏目。</p>')
    path,draft=fixture(tmp_path,raw)
    assert preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)['classification']=='irrelevant'


def test_paginated_international_camp_directory_is_not_a_single_activity(tmp_path):
    raw=html('暑期夏令营-计算机学院','<p>本栏目介绍本学院的国际化学生交流活动与往届项目资料，请点击下方各条独立公告查询对应完整报名要求和活动安排。</p><a href="summer.html">2023.04.12 PKU CS International Summer School</a><a href="winter.html">2021.09.28 国际学生冬令营（线上）</a><p>First Previous 1 Next Last</p>')
    path,draft=fixture(tmp_path,raw)
    assert preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)['classification']=='irrelevant'


def test_historical_deadline_reference_does_not_close_new_winter_camp(tmp_path):
    raw=html('2027年计算机冬令营报名通知','<p>申请对象为2028届计算机专业本科生，申请材料为成绩单和个人简历。往年报名截止2026年6月30日，本次时间尚未确定。</p>')
    path,draft=fixture(tmp_path,raw)
    assert preflight.classify(tmp_path,draft,CONFIGS,now=NOW,queue_path=path)['classification']=='unknown'


@pytest.mark.parametrize('state',['retry','budget_wait'])
def test_policy_upgrade_does_not_override_existing_wait(tmp_path,state):
    path,draft=fixture(tmp_path,CURRENT)
    draft['automatic_review']=dict(policy_version='old-v2',state=state,attempts=2,failures=2,
        next_attempt_at=(NOW+timedelta(hours=2)).isoformat(),content_sha256=draft['fetch']['content_sha256'],
        input_revision=automatic_review.protected(draft))
    result=automatic_review.process(tmp_path,path,draft,CONFIGS,publish=True,now=NOW,
        fetcher=lambda _:pytest.fail('upgrade bypassed source backoff'),checker=lambda *a:pytest.fail('upgrade bypassed AI backoff'))
    assert result['state']=='skipped' and result['next_attempt_at']==draft['automatic_review']['next_attempt_at']


@pytest.mark.parametrize('extra',['<p>申请表见附件。</p>','<a href="form.pdf">申请表.pdf</a>'])
def test_manual_draft_with_unresolved_attachment_never_uses_partial_html_ai(tmp_path,extra):
    raw=CURRENT.replace(b'</article>',extra.encode()+b'</article>')
    path,draft=fixture(tmp_path,raw)
    draft['manual_edit']={'at':NOW.isoformat()}
    # Legacy queue can contain status=ok even when it did not collect attachments.
    draft['fetch']['status']='ok'
    review.atomic_json(path,{'version':1,'drafts':[draft]})
    result=automatic_review.assist_pending(tmp_path,path,draft,CONFIGS,
        dict(id=draft['id'],state='manual_required',reasons=[],attempts=0),NOW,
        lambda *a:pytest.fail('partial HTML consumed AI'))
    assert result['state']=='manual_required' and result['attempts']==0
    assert review.read_queue(path)['drafts'][0]['item']==draft['item']


def test_permission_failure_is_not_a_retrying_ai_outage(tmp_path):
    path,draft=fixture(tmp_path,CURRENT)
    def fail(*args):
        raise PermissionError('private-path-or-config-must-never-leak')
    result=automatic_review.assist_pending(tmp_path,path,draft,CONFIGS,
        dict(id=draft['id'],state='manual_required',reasons=[],attempts=0),NOW,fail)
    assert result['state']=='manual_required' and result['retryable'] is False
    assert result['error_code']=='local_permission_denied'
    assert 'private-path' not in str(result)
    assert not result.get('next_attempt_at')

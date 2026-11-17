import hashlib
import json
from datetime import timedelta

import pytest

from crawler import mentor_fields as fields,mentor_quality as quality,mentor_recovery as recovery,legacy_refresh
from sites.profile_fields import clean_research,research,own_labelled_email
from sites.related_roster import parse_detail as related
from sites.ecnu.ecnu_cs import parse_detail as ecnu
from tests.test_mentor_quality_v1114 import root,put,body,NOW
from tests.test_mentor_recovery_v1115 import configure


@pytest.mark.parametrize('value,expected',[
    ('网络与系统安全、人工智能安全和软件工程、主持参与国家级项目、重点课题','网络与系统安全、人工智能安全和软件工程'),
    ('方向为操作系统、人工智能、承担国家和军队课题10余项、入选人才计划','操作系统、人工智能'),
    ('方向为操作系统、人工智能，研究领域包括多模态大模型、大模型安全，承担国家和军队课题10余项','操作系统、人工智能，研究领域包括多模态大模型、大模型安全'),
    ('项目管理、科技成果评价、论文推荐系统','项目管理、科技成果评价、论文推荐系统'),
    ('韩老师，男，教授，博士毕业。研究方向为智能制造、工程管理。承担科研项目。','智能制造、工程管理'),
    ('个人简介：韩老师，教授，毕业于某大学。',None)])
def test_topics_remove_biography_without_destroying_real_project_topics(value,expected):
    assert clean_research(value)==expected


def test_inline_research_does_not_swallow_next_paragraph():
    assert research('张老师主要研究方向为强化学习。\n主持国家重点项目。')=='强化学习'


@pytest.mark.parametrize('value',[
    '导师张三。招生联系人：李老师，邮箱：li@example.edu.cn',
    '导师张三。招生办公室邮箱：office@example.edu.cn',
    '导师张三。教务邮箱：admin@example.edu.cn'])
def test_explicit_admissions_or_office_contact_is_not_personal_email(value):
    assert own_labelled_email(value) is None


def test_explicit_own_contact_email_remains_usable():
    assert own_labelled_email('本人联系邮箱：me@example.edu.cn')=='me@example.edu.cn'


def test_related_personal_sections_supply_direction_and_qualification():
    cfg={'detail_fields':{'name':'.person h2','title':'.person h5'},'bio_selector':'.biography'}
    html='<div class="person"><h2>张老师</h2><h5>教授、博士生导师</h5></div><div class="biography">研究方向\n控制理论、机器人\n科研项目\n主持国家项目</div>'
    parsed=related(cfg,html,'https://test.edu.cn/a')
    assert parsed['research_direction_raw']=='控制理论、机器人'
    assert parsed['supervisor']=='博导'


def test_ecnu_scoped_fields_exclude_footer_email_and_education_topics():
    html='''<div><h1 class="news_title">张老师</h1><p class="news_meta"><span class="tip1">副教授</span></p></div>
    <div><div><h3 class="tit">教育经历</h3></div>研究方向：旧学位方向</div>
    <div><div><h3 class="tit">个人简介</h3></div>张老师，副教授，硕士生导师。</div>
    <div><div><h3 class="tit">研究方向</h3></div>可信机器学习</div>
    <footer>admin@ecnu.edu.cn</footer>'''
    parsed=ecnu({},html,'https://faculty.ecnu.edu.cn/a')
    assert parsed['research_direction_raw']=='可信机器学习' and parsed['supervisor']=='硕导'
    assert 'email' not in parsed and 'admin@' not in parsed['_field_scope']


def test_successful_fetch_does_not_hide_missing_fields_and_uses_cooldowns(root):
    configure(root);person=quality.load_yaml(root/'data/professors/test/cs/teacher.yaml')
    person.pop('email',None);person.pop('research_direction_raw',None);person.pop('supervisor',None);person.pop('title',None)
    put(root/'data/professors/test/cs/teacher.yaml',person)
    state=fields.seed(root,NOW)
    assert state['summary']['fields']==4
    assert state['summary']['optional_by_field']['homepage']==1
    assert state['records']['test/cs/teacher']['fields']['homepage']['optional'] is True
    fields.observation(root,person,parsed={'_field_scope':'张老师\n教授\n研究方向：'},source_sha256='a'*64,fetched_at=NOW.isoformat(),now=NOW,parser_signature=recovery.signature(root,quality.load_yaml(root/'sites/test/cs.yaml')))
    row=fields.read(root)['records']['test/cs/teacher']['fields']
    assert row['email']['status']=='waiting_source' and row['supervisor']['reason_code']=='not_found_in_checked_source'
    assert row['research_direction_raw']['reason_code']=='not_extracted'
    assert row['title']['reason_code']=='not_extracted'
    assert row['email']['next_check_at']==(NOW+timedelta(days=30)).isoformat(timespec='seconds')
    assert not fields.due(fields.read(root)['records']['test/cs/teacher'],quality.load_yaml(root/'sites/test/cs.yaml'),root,(NOW+timedelta(hours=1)).isoformat())


def test_manual_field_and_shared_contact_cannot_be_filled(root):
    configure(root);person=quality.load_yaml(root/'data/professors/test/cs/teacher.yaml');person.pop('email',None)
    person['provenance']={'research_direction_raw':{'origin':'manual'}}
    fields.observation(root,person,parsed={'_rejected_email':'admin@test.edu.cn','_field_scope':'张老师'},now=NOW)
    row=fields.read(root)['records']['test/cs/teacher']['fields']
    assert row['email']['reason_code']=='shared_contact' and row['email']['next_check_at'] is None
    assert row['research_direction_raw']['reason_code']=='manual_field'


def test_recent_evidence_reparse_keeps_source_time_and_avoids_http(root):
    cfg=configure(root);raw=body().encode();digest=hashlib.sha256(raw).hexdigest();prior=NOW-timedelta(hours=4)
    path=root/'cache/legacy_refresh/evidence'/(digest+'.body');path.parent.mkdir(parents=True);path.write_bytes(raw)
    path=root/'cache/legacy_refresh/state.json';path.write_text(json.dumps({'records':{'professor/test/cs/teacher.yaml':{'status':'ok','source_url':'https://test.edu.cn/old','last_success':prior.isoformat(),'raw_sha256':digest}}}),encoding='utf8')
    report=fields.run(root,limit=1,request_budget=1,fetcher=lambda s:pytest.fail('must reuse evidence'),now=NOW)
    assert report['requests']==0 and report['reused']==1 and report['errors']==0
    values=fields.read(root)['records']['test/cs/teacher']['fields'].values()
    assert all(v['fetched_at']==prior.isoformat() for v in values)
    second=fields.run(root,limit=1,request_budget=1,fetcher=lambda s:pytest.fail('must respect cooldown'),now=NOW+timedelta(hours=1))
    assert second['attempted']==0


def test_field_refresh_honors_actual_request_budget(root):
    configure(root);seen=[]
    report=fields.run(root,limit=10,request_budget=0,fetcher=lambda s:seen.append(s) or body(),now=NOW)
    assert not seen and report['attempted']==0 and report['requests']==0


def test_insufficient_identity_is_discoverable_but_real_conflict_is_manual():
    assert recovery.classify('备用官方详情未通过姓名与独立身份特征匹配')['next_action']=='discover_official_source'
    assert recovery.classify('备用官方详情邮箱与原记录不一致，保留矛盾待核对')['next_action']=='manual_review'
    assert recovery.classify('备用官方详情未通过姓名与独立身份特征匹配；另一候选邮箱与原记录不一致')['next_action']=='manual_review'


def test_new_official_identity_evidence_wakes_old_insufficient_identity_label(root):
    configure(root)
    quality.run(root,fetcher=lambda s:'<p>教师目录尚无个人链接</p>',now=NOW)
    path=root/'cache/mentor_quality/state.json';state=json.loads(path.read_text(encoding='utf8'))
    row=next(iter(state['records'].values()))
    row.update(reason='备用官方详情未通过姓名与独立身份特征匹配',reason_code='identity_conflict',next_action='manual_review')
    path.write_text(json.dumps(state),encoding='utf8')
    result=recovery.refresh_directories(root,max_units=1,request_budget=6,fetcher=lambda s:body() if s['url'].endswith('/new') else '<a href="/new">张老师</a>',now=NOW+timedelta(days=1))
    assert result['requeued']==1
    row=next(iter(json.loads(path.read_text(encoding='utf8'))['records'].values()))
    assert row['reason_code']=='identity_evidence_missing' and row['next_action']=='discover_official_source'


def test_normal_refresh_records_gaps_even_when_other_fields_succeeded(root):
    configure(root)
    result=legacy_refresh.run(root,kind='professors',limit=1,fetcher=lambda s:body().encode(),now=NOW)
    assert result['ok']==1
    state=fields.read(root)
    assert state['summary']['fields']>0
    assert state['records']['test/cs/teacher']['fields']['supervisor']['status']=='waiting_source'


def test_first_real_problem_starts_its_own_clock_and_persistent_failure_keeps_it(root):
    configure(root);person=quality.load_yaml(root/'data/professors/test/cs/teacher.yaml')
    fields.seed(root,NOW)
    first=NOW+timedelta(days=4)
    fields.observation(root,person,error='HTTP 503',now=first)
    row=fields.read(root)['records']['test/cs/teacher']['fields']['supervisor']
    assert row['first_seen']==NOW.isoformat(timespec='seconds')
    assert row['pending_since']==first.isoformat(timespec='seconds')
    fields.observation(root,person,error='HTTP 503',now=first+timedelta(hours=2))
    assert fields.read(root)['records']['test/cs/teacher']['fields']['supervisor']['pending_since']==row['pending_since']
    fields.observation(root,person,parsed={'_field_scope':'张老师，暂未列出资格'},now=first+timedelta(days=1))
    assert fields.read(root)['records']['test/cs/teacher']['fields']['supervisor']['status']=='waiting_source'
    later=first+timedelta(days=31)
    fields.observation(root,person,error='HTTP 503',now=later)
    assert fields.read(root)['records']['test/cs/teacher']['fields']['supervisor']['pending_since']==later.isoformat(timespec='seconds')

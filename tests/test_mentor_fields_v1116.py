from datetime import timedelta

import pytest

from crawler import mentor_quality as quality, mentor_recovery as recovery
from sites.profile_fields import research,own_labelled_email,qualification
from sites.ucas.cas_lists import parse_generic_detail
from sites.sjtu.sjtu_cs import parse_detail as sjtu_detail
from tests.test_mentor_quality_v1114 import root,put,body,NOW
from tests.test_mentor_recovery_v1115 import configure


def test_cas_personal_section_does_not_include_projects_or_infer_qualification():
    html='''<div class="gunius-detail"><div class="gunius-info"><h3 class="name">张老师<span>/博士研究生</span></h3>
    <li>职　　称: <span>副研究员</span></li><li>电子邮件: <span>a@ia.ac.cn</span></li></div>
    <div class="gunius-list"><h3>研究方向</h3><div class="gunitem">群体智能、强化学习</div></div>
    <div class="gunius-list"><h3>承担科研项目情况</h3><div class="gunitem">无关项目</div></div></div>'''
    p=parse_generic_detail({},html,'https://ia.cas.cn/person')
    assert p['name']=='张老师' and p['title']=='副研究员' and p['email']=='a@ia.ac.cn'
    assert p['research_direction_raw']=='群体智能、强化学习' and 'supervisor' not in p


def test_research_stops_at_actual_cas_project_heading():
    assert research('个人简历\n博士毕业\n研究方向\n人工智能\n图像处理\n承担科研项目情况\n项目一')=='人工智能 图像处理'


def test_research_does_not_use_a_publication_direction():
    assert research('个人简介\n介绍尚未更新\n发表论文\n某团队研究方向为机器学习。') is None


@pytest.mark.parametrize('text,expected',[
    ('个人简介\n张老师，某大学副教授、博士生导师。','博导'),
    ('张老师，教授、博导、硕导。','博导、硕导'),
    ('张老师，博士研究生毕业，师从王教授。',None),
    ('张老师，合作导师是博士生导师王教授。',None),
    ('王老师，教授、博士生导师。',None),
    ('张老师，曾任教授、博士生导师。',None),
    ('张老师，教授，非博士生导师。',None),
    ('张老师，目前尚未取得硕士生导师资格。',None),
    ('张老师，曾担任博士生导师，现已退休。',None),
    ('张老师，硕士生导师，研究无人自主系统。','硕导'),
    ('张老师，团队招收博士。',None)])
def test_qualification_requires_current_named_self_description(text,expected):
    assert qualification(text,'张老师')==expected


def test_sjtu_explicit_research_statement_is_collected():
    html='<div class="js-info"><div class="name">张老师</div><div class="zw">教授</div></div><div class="js-dt">个人简介\n张老师主要研究方向为密码学与计算数论。博士毕业于某大学。</div>'
    p=sjtu_detail({'base_url':'https://www.cs.sjtu.edu.cn'},html,'https://www.cs.sjtu.edu.cn/jiaoshiml/test.html')
    assert p['research_direction_raw']=='密码学与计算数论' and 'supervisor' not in p


@pytest.mark.parametrize('value,expected',[
    ('欢迎咨询交流（邮箱：teacher@csu.edu.cn）','teacher@csu.edu.cn'),
    ('学生邮箱：student@csu.edu.cn',None),
    ('合作导师邮箱：other@csu.edu.cn',None),
    ('邮箱：one@csu.edu.cn；电子邮箱：two@csu.edu.cn',None),
    ('teacher@csu.edu.cn 出现在论文引用里',None)])
def test_biography_contact_requires_one_explicit_personal_label(value,expected):
    assert own_labelled_email(value)==expected


def test_exhausted_transport_budget_preserves_next_directory(root):
    cfg=configure(root)
    cfg['profile_lookup_urls']=['https://test.edu.cn/'+str(i) for i in range(5)]
    seen=[]
    def fetch(source):
        if len(seen)==2:raise recovery.DiscoveryBudgetExhausted('stop')
        seen.append(source['url']);return '<p>教师目录</p>'
    first=recovery.directory_index(root,cfg,quality.Sources(root,fetch,NOW.isoformat()))
    assert first['pages_checked']==2 and first['frontier'][0][0]=='https://test.edu.cn/2'
    second=recovery.directory_index(root,cfg,quality.Sources(root,lambda s:seen.append(s['url']) or '<p>教师目录</p>',(NOW+timedelta(hours=1)).isoformat()),refresh=True)
    assert 'https://test.edu.cn/2' in seen and seen.count('https://test.edu.cn/0')==1
    assert not second['frontier']


@pytest.mark.parametrize('email,expected',[('teacher@test.edu.cn',1),('other@test.edu.cn',0)])
def test_independent_directory_job_wakes_only_identity_verified_new_source(root,email,expected):
    configure(root)
    quality.run(root,fetcher=lambda s:'<p>暂无个人链接</p>',now=NOW)
    old=quality.load_yaml(root/'data/professors/test/cs/teacher.yaml')
    def fetch(source):
        return body(email=email) if source['url'].endswith('/new') else '<a href="/new">张老师</a>'
    result=recovery.refresh_directories(root,max_units=1,request_budget=6,fetcher=fetch,now=NOW+timedelta(days=1))
    assert result['requeued']==expected and result['requests']<=6
    assert quality.load_yaml(root/'data/professors/test/cs/teacher.yaml')==old
    import json
    record=next(iter(json.loads((root/'cache/mentor_quality/state.json').read_text(encoding='utf8'))['records'].values()))
    assert record['pending_since']==NOW.isoformat(timespec='seconds')


def test_directory_job_keeps_manual_review_blocked(root):
    configure(root)
    quality.run(root,fetcher=lambda s:'<p>暂无个人链接</p>',now=NOW)
    import json
    path=root/'cache/mentor_quality/state.json';state=json.loads(path.read_text(encoding='utf8'))
    row=next(iter(state['records'].values()));row['next_action']='manual_review';original_due=row['next_check_at']
    path.write_text(json.dumps(state),encoding='utf8')
    def fetch(source):
        assert not source['url'].endswith('/new')
        return '<a href="/new">张老师</a>'
    result=recovery.refresh_directories(root,max_units=1,request_budget=4,fetcher=fetch,now=NOW+timedelta(days=1))
    assert result['requeued']==0
    assert next(iter(json.loads(path.read_text(encoding='utf8'))['records'].values()))['next_check_at']==original_due


def test_hit_public_template_contact_body_and_identity_are_separate():
    import json
    from sites.hit.hit_cs import parse_detail
    html='<h3 class="chineseName">张老师</h3><div id="col-r"><p class="EmailText">nc.ude.tih@t</p></div><script src="scripts/utils/newUtils.js"></script><div id="teacher_info"><span class="user-label">计算机视觉</span></div><div class="teacher-body" data-tid="'+'a'*32+'"></div>'
    body='<div class="part_box"><div class="part_t_l"><em>个人简介</em></div>名称 张老师，教授、博导，智能接口与人机交互研究中心。团队招收博士。</div>'
    calls=[]
    parsed=parse_detail({'_read_source':lambda url:calls.append(url) or (b'',json.dumps(body))},html,'https://homepage.hit.edu.cn/zhang')
    assert parsed['email']=='t@hit.edu.cn' and parsed['research_direction_raw']=='计算机视觉'
    assert parsed['title']=='教授' and not parsed.get('supervisor')
    assert calls==['https://homepage.hit.edu.cn/TeacherHome/teacherBody.do?id='+'a'*32+'&versionId=']
    original=dict(name='张老师',detail_url='http://www.cs.hit.edu.cn/jsml/list.htm',institutes=['智能接口与人机交互研究中心'])
    assert recovery.identity(original,parsed,'https://homepage.hit.edu.cn/zhang')=='official_named_link_and_same_research_centre'
    assert recovery.identity(dict(original,institutes=['另一研究中心']),parsed,'https://homepage.hit.edu.cn/zhang') is None
    assert recovery.identity(original,dict(parsed,_identity_bio=''), 'https://homepage.hit.edu.cn/zhang') is None


def test_hit_gateway_conversion_is_exact_and_still_needs_named_link():
    old='http://homepage-hit-edu-cn.ivpn.hit.edu.cn:1080/zhang'
    assert recovery.directory_target(old,'https://cs.hit.edu.cn')=='https://homepage.hit.edu.cn/zhang'
    assert recovery.named_link('<a href="'+old+'">张老师</a>','https://cs.hit.edu.cn/22196/list.htm','https://homepage.hit.edu.cn/zhang','张老师')
    assert not recovery.named_link('<a href="'+old+'">王老师</a>','https://cs.hit.edu.cn/22196/list.htm','https://homepage.hit.edu.cn/zhang','张老师')
    assert not recovery.allowed(recovery.directory_target(old,'https://other.edu.cn'),'https://other.edu.cn')


def test_shared_parser_dependency_change_invalidates_repair_signature(root):
    cfg=configure(root);cfg['parser_dependencies']=['shared.py']
    dep=root/'sites/shared.py';dep.write_text('version=1')
    before=recovery.signature(root,cfg);dep.write_text('version=2')
    assert recovery.signature(root,cfg)!=before


def test_roster_differences_are_audited_without_new_records(root):
    import json
    cfg=configure(root);cfg.update(roster_discovery=True,list={'person_href':r'/person/new$'})
    sources=quality.Sources(root,lambda source:pytest.fail('candidate inventory must not fetch personal pages'),NOW.isoformat())
    index={'links':[dict(name='新老师',url='https://test.edu.cn/person/new',directory_url='https://test.edu.cn/people')]}
    result=recovery.collect_roster_candidates(root,cfg,index,sources)
    assert result['candidates']==1
    assert not list((root/'data/professors/test/cs').glob('discovered-*.yaml'))
    path=root/'cache/mentor_quality/roster-candidates.json'
    state=json.loads(path.read_text(encoding='utf8'))
    assert next(iter(state['records'].values()))['status']=='pending'
    recovery.collect_roster_candidates(root,cfg,index,sources)
    assert len(json.loads(path.read_text(encoding='utf8'))['records'])==1


@pytest.mark.parametrize('kind',['normal','allowed','oversize','redirect','private'])
def test_explicit_json_body_keeps_transport_boundaries(monkeypatch,kind):
    from unittest.mock import MagicMock
    from crawler import source_discovery as discovery
    session=MagicMock();session.__enter__.return_value=session
    response=MagicMock();response.__enter__.return_value=response
    response.status_code=302 if kind=='redirect' else 200
    response.headers={'Content-Type':'text/json;charset=UTF-8','Location':'https://evil.edu.cn/body'}
    response.iter_content.return_value=[b'x'*(discovery.MAX_BYTES+1)] if kind=='oversize' else [b'"public biography"']
    session.get.return_value=response
    monkeypatch.setattr(discovery.requests,'Session',lambda:session)
    monkeypatch.setattr(discovery.socket,'getaddrinfo',lambda *a,**k:[(None,None,None,None,('127.0.0.1' if kind=='private' else '8.8.8.8',443))])
    kwargs={} if kind=='normal' else {'accepted_types':('text/json','application/json')}
    if kind=='allowed':assert discovery.fetch_html('https://homepage.hit.edu.cn/body','https://cs.hit.edu.cn',**kwargs)==b'"public biography"'
    else:
        with pytest.raises(ValueError):discovery.fetch_html('https://homepage.hit.edu.cn/body','https://cs.hit.edu.cn',**kwargs)
    if kind=='private':session.get.assert_not_called()

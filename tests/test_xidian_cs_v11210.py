from pathlib import Path
from datetime import datetime, timezone

import pytest
import yaml

from crawler import mentor_fields
from crawler.mentor_recovery import IdentityConflict
from sites.xidian import xidian_cs


UNIT = 'xidian/cs'
ROSTER = 'https://cs.xidian.edu.cn/szdw/dsjs.htm'
FACULTY = 'https://faculty.xidian.edu.cn/ZJ/zh_CN/index.htm'
WEB = 'https://web.xidian.edu.cn/zhangjia/'
HOME = 'https://cs.xidian.edu.cn/zhangjia.htm'
NAME = '张甲'
EMAIL = 'zhangjia@example.edu'
NOW = datetime(2026, 11, 23, 1, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((REPO/'sites/xidian/cs.yaml').read_bytes())


def faculty(body, name=NAME, key='ZJ'):
    return (f'<title>西安电子科技大学主页平台管理系统 {name} 首页 中文主页</title>'
            f'<div class="t_photo"><span>{name}</span></div>'
            f'<a href="/{key}/zh_CN/index/43/list/index.htm">首页</a>{body}')


def web(body='', *, info='', name=NAME):
    return (f'<title>{name} | 个人信息 | 西安电子科技大学个人主页</title>'
            f'<div id="top"><ul><li><a href="/zhangjia/index.html">{name}的主页:</a></li></ul></div>'
            f'<div id="n0"><p>姓名：{name}</p><p>工作单位：计算机科学与技术学院</p>{info}</div>{body}')


def person(url=WEB, **values):
    return {'slug':'one','school':'xidian','dept':'cs','name':NAME,'detail_url':url,**values}


def provenance(url):
    return {'source':url,'origin':'crawled','fetched_at':'2026-11-01','confidence':'auto'}


def parse(page, url=WEB, **values):
    p=person(url,**values)
    return xidian_cs.parse_detail(dict(CFG,_original_profile=p,_expected_name=NAME),page,url)


def contact(page, url=WEB, previous=None, **values):
    if previous and 'provenance' not in values:
        values['provenance']={'email':provenance(url)}
    p=person(url,**values)
    def read(target):
        assert target == url
        return page.encode(),page
    return xidian_cs.parse_contact(dict(CFG,_read_source=read,_previous_email=previous),p)


def tabs(research, social='期刊编委'):
    return ('<div class="slideTxtBox2"><div class="hd"><ul><li>研究方向 <span>Research Focus</span></li>'
            '<li>社会兼职 <span>Social Affiliations</span></li></ul></div>'
            f'<div class="bd"><ul>{research}</ul><ul class="shjz-list"><li>{social}</li></ul></div></div>')


def web_direction(content):
    return f'<div class="mo"><div class="drag"><span id="t1">主要研究方向</span></div><div id="n1">{content}</div></div>'


@pytest.mark.parametrize(('html','url','expected'), [
    (faculty(tabs('<li>数据安全</li><li>加密数据库</li>')),FACULTY,'数据安全、加密数据库'),
    (faculty('<div class="rightconside1"><h2>研究方向</h2><div class="rightfont"><p>深度学习</p></div></div>'),FACULTY,'深度学习'),
    (web(web_direction('<p>1. 数据安全</p><p>2. 联邦学习、大语言模型</p>')),WEB,'1. 数据安全、2. 联邦学习、大语言模型'),
])
def test_only_bounded_research_pane_with_order(html,url,expected):
    value=parse(html,url)
    assert value['research_direction_raw']==expected and value['research_directions']==[expected]


@pytest.mark.parametrize('prior_source',[FACULTY,'https://cs.xidian.edu.cn/older.htm'])
@pytest.mark.parametrize('origin',['crawled','manual'])
def test_same_source_placeholder_replacement_and_protected_directions(prior_source,origin):
    proof=dict(provenance(prior_source),origin=origin)
    page=faculty(tabs('<li>数据安全</li>'))
    parsed=parse(page,FACULTY, research_direction_raw='Research Focus',provenance={'research_direction_raw':proof})
    assert parsed.get('research_direction_raw')==('数据安全' if prior_source==FACULTY and origin=='crawled' else None)
    unchanged=parse(page,FACULTY,research_direction_raw='数据安全',provenance={'research_direction_raw':proof})
    assert unchanged.get('research_direction_raw')==('数据安全' if prior_source==FACULTY and origin=='crawled' else None)


def test_no_research_from_placeholders_or_unrelated_part():
    for value in ('暂无内容','教学工作','网络安全，近年承担重点科研项目','目前也跟随团队进行数据管理相关科研任务'):
        assert 'research_direction_raw' not in parse(faculty(tabs(f'<li>{value}</li>','密码学')),FACULTY)
    assert 'research_direction_raw' not in parse(web('<div><p>研究方向：图挖掘</p></div>'))
    mixed=faculty('<div class="rightconside1"><h2>研究方向</h2><h2>教学工作</h2>'
                  '<div class="rightfont"><p>密码学</p></div></div>')
    assert 'research_direction_raw' not in parse(mixed,FACULTY)


def test_keeps_verified_same_source_value_and_provenance_out_of_auto_refresh():
    verified=dict(provenance(FACULTY),confidence='verified')
    page=faculty(tabs('<li>数据安全</li>'))
    parsed=parse(page,FACULTY,research_direction_raw='数据安全',provenance={'research_direction_raw':verified})
    assert 'research_direction_raw' not in parsed


def test_wrong_portal_self_link_or_explicit_person_has_typed_conflict():
    with pytest.raises(IdentityConflict):
        parse(faculty(tabs('<li>数据安全</li>'),key='OTHER'),FACULTY)
    with pytest.raises(IdentityConflict):
        parse(web(name='李乙',info=f'<p>联系方式：{EMAIL}</p>'))
    with pytest.raises(IdentityConflict):
        xidian_cs.parse_detail(dict(CFG,_expected_name=NAME,_original_profile=person()),faculty(''),FACULTY)


def test_home_identity_marker_needs_an_exact_secure_registered_profile_home():
    assert parse(faculty(''),FACULTY)['_identity_profile_home']==FACULTY
    assert '_identity_profile_home' not in parse(faculty(''),FACULTY.replace('/zh_CN/index.htm',''))
    assert '_identity_profile_home' not in parse(faculty(''),FACULTY.replace('https:','http:'))
    assert '_identity_profile_home' not in parse(web())


def test_old_faculty_http_short_address_is_held():
    short=FACULTY.replace('https:','http:').replace('/zh_CN/index.htm','')
    with pytest.raises(ValueError,match='缺少可持续安全入口'):
        parse(faculty(tabs('<li>数据安全</li>')),short)


def test_short_registered_profile_conflicting_declared_contact_cannot_recover():
    short=FACULTY.replace('/zh_CN/index.htm','')
    row=person(short,email=EMAIL)
    markup=faculty('<div class="p_left"><div class="t_jbxx_nr"><p>电子邮箱：other@example.edu</p></div></div>')
    settings=dict(CFG,_expected_name=NAME,_original_profile=row)
    with pytest.raises(IdentityConflict):
        xidian_cs.parse_detail(settings,markup,FACULTY)


@pytest.mark.parametrize('field',['detail_url','profile_url'])
@pytest.mark.parametrize('proof',[{'origin':'manual'},{'confidence':'verified'}])
def test_short_url_recovery_keeps_protected_registration(field,proof):
    short=FACULTY.replace('/zh_CN/index.htm','')
    row=person(short,provenance={field:dict(provenance(short),**proof)})
    with pytest.raises(IdentityConflict):
        xidian_cs.parse_detail(dict(CFG,_expected_name=NAME,_original_profile=row),faculty(''),FACULTY)


def test_keep_encrypted_contact_and_plaintext_out_of_ordinary_parser(monkeypatch):
    def unavailable(*args,**kwargs):
        pytest.fail('unexpected request to recover an encrypted site field')
    monkeypatch.setattr(xidian_cs.fetch,'fetch_text',unavailable)
    raw=faculty('<script>var _tsites_com_view_mode_type_=8;</script>'
                '<div class="t_jbxx_nr"><p>电子邮箱：<span id="tsemail" _tsites_encrypt_field="1">deadbeef</span></p>'
                f'<p>{EMAIL}</p></div>')
    assert 'email' not in parse(raw,FACULTY)
    assert 'email' not in contact(raw,FACULTY)
    assert 'email' not in parse(web(info=f'<p>联系方式：{EMAIL}</p>'))


@pytest.mark.parametrize('label', ['联系方式：zhangjia [AT] example.edu',
                                  '电子邮箱：zhangjia (at) example (dot) edu',
                                  f'电子邮箱：</p><p><a href="mailto:{EMAIL}">{EMAIL}</a>'])
def test_named_contact_label_and_recheck_match_bound_source(label):
    page=web(info=f'<p>{label}</p>')
    result=contact(page,previous=EMAIL)
    assert result=={'email':EMAIL,'_verified_roster_name':NAME,'_field_sources':{'email':WEB}}
    assert contact(page,previous='other@example.edu')=={}
    assert contact(page,email='other@example.edu')=={}
    assert contact(page,previous=EMAIL,provenance={'email':provenance(HOME)})=={}
    manual=dict(provenance(WEB),origin='manual')
    assert contact(page,provenance={'email':manual})=={}


@pytest.mark.parametrize('text', [
    f'<p>{EMAIL}</p>',
    f'<p>联系方式：{EMAIL}</p><p>电子邮箱：other@example.edu</p>',
    f'<p>电子邮箱：<a href="mailto:other@example.edu">{EMAIL}</a></p>',
    f'<p>电子邮箱：</p><p>{EMAIL}</p><p>other@example.edu</p>',
    f'<p>联系电话：{EMAIL}</p>',
])
def test_does_not_pick_ambiguous_unlabelled_or_other_mailbox(text):
    assert contact(web(info=text))=={}
    assert contact(web(f'<div class="news"><p>电子邮箱：{EMAIL}</p></div>'))=={}


def test_roster_excludes_navigation_and_ambiguous_names_without_profile_overwrite(monkeypatch):
    html=('<div id="vsb_content_2"><table class="yjsds_table"><tr><td>'
          f'<a href="{WEB}">张甲</a><a href="{WEB}index.html">张甲</a>'
          f'<a href="{FACULTY}">常乙</a><a href="https://web.xidian.edu.cn/other/">常乙</a>'
          f'<a href="{FACULTY}" title="不同名">同名</a></td></tr></table></div>'
          '<footer><a href="https://web.xidian.edu.cn/dept/">了解学院</a></footer>')
    monkeypatch.setattr(xidian_cs.fetch,'fetch_text',lambda *args:(html,{'fetched_at':'2026-11-23'},None))
    roster,_=xidian_cs.iter_roster(CFG)
    assert roster==[{'name':NAME,'url':WEB}]


@pytest.mark.parametrize(('target_name','existing_owner'),[(NAME,False),('李乙',False),(None,True)])
def test_field_queue_enforces_owner_and_fetches_distinct_homepage_target(tmp_path,target_name,existing_owner):
    config=tmp_path/'sites/xidian'
    config.mkdir(parents=True)
    for name in ('xidian_cs.py','cs.yaml'):
        (config/name).write_bytes((REPO/'sites/xidian'/name).read_bytes())
    folder=tmp_path/'data/professors/xidian/cs'
    folder.mkdir(parents=True)
    path=folder/'one.yaml'
    original=person()
    path.write_text(yaml.safe_dump(original),encoding='utf-8')
    if existing_owner:
        other=person('https://web.xidian.edu.cn/another/',slug='another',name='李乙',email=EMAIL)
        (folder/'another.yaml').write_text(yaml.safe_dump(other),encoding='utf-8')
    details=f'<p>联系方式：{EMAIL}</p>'
    if target_name:
        details+=(f'<p>个人主页：<a href="{HOME}">访问本人主页</a></p>'
                  '<p>个人主页：<a href="/zhangjia/index.html">原登记主页</a></p>')
    html=web(info=details)
    reached=[]
    def fetch(request):
        url=request['url'];reached.append(url)
        if url==WEB:return html.encode()
        if url==HOME:return f'<h1>{target_name}</h1>'.encode()
        raise AssertionError(url)
    result=mentor_fields.run(tmp_path,units=(UNIT,),limit=2,request_budget=8,domain_budget=8,workers=1,now=NOW,fetcher=fetch)
    current=yaml.safe_load(path.read_bytes())
    assert current.get('email')==(None if existing_owner else EMAIL)
    assert current.get('homepage')==(HOME if target_name==NAME else None)
    assert (HOME in reached)==bool(target_name) and WEB+'index.html' not in reached
    assert any(r['id']==UNIT+'/one' for r in result['results'])

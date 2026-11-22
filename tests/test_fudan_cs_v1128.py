import pytest

from sites.fudan import fudan_cs

PRIMARY = 'https://ai.fudan.edu.cn/wh_37219/list.htm'
FACULTY = 'https://faculty.fudan.edu.cn/weihui/zh_CN/index.htm'
NAME = '危辉'
ADDRESS = 'weihui@fudan.edu.cn'


def primary(*, path='/wh_37219/list.htm', name=NAME, research='', bio='', email=ADDRESS, homepage=FACULTY):
    return (f'<li class="col_path"><a href="{path}">中文信息</a></li><div class="news_con">'
            f'<div class="news_wz"><div class="news_title">{name}</div></div>'
            f'<div class="news_ex"><span class="bt">研究领域：</span><span class="nr">{research}</span></div>'
            f'<div class="news_jj"><span class="bt">个人简介：</span><p class="nr">{bio}</p></div>'
            f'<div class="news_email"><span class="nr">{email}</span></div>'
            f'<div class="news_gr"><a href="{homepage}">个人主页</a></div></div>'
            '<footer>邮箱：college@fudan.edu.cn</footer>')


def faculty(*, name=NAME, affiliation='计算与智能创新学院', address=ADDRESS, research='认知科学；智能机器人'):
    return (f'<title>{name} 中文主页--首页</title><div class="banner-nr"><h5>{name}<span>教授</span></h5>'
            f'<ul><li>所在单位：{affiliation}</li><li>邮箱：{address}</li></ul></div>'
            '<div class="slideTxtBox"><div class="hd"><ul><li>研究方向</li><li>社会兼职</li></ul></div>'
            f'<div class="bd"><ul><li>{research}</li></ul><ul><li>不应进入方向的兼职</li></ul></div></div>')


def cfg(**profile):
    return {'contact_hook_only':True, '_original_profile':{'name':NAME,'detail_url':PRIMARY,'homepage':FACULTY,**profile}}


def test_current_primary_path_rejects_other_registration_and_same_name_wrong_body():
    with pytest.raises(ValueError,match='已登记本人路径'):
        fudan_cs.parse_detail(cfg(),primary(path='/wh-2/list.htm'),'https://ai.fudan.edu.cn/wh-2/list.htm')
    with pytest.raises(ValueError,match='中文本人页路径'):
        fudan_cs.parse_detail(cfg(),primary(path='/wh-2/list.htm'),PRIMARY)
    with pytest.raises(ValueError,match='姓名'):
        fudan_cs.parse_detail(cfg(),primary(name='其他人'),PRIMARY)
    assert fudan_cs.parse_detail(cfg(detail_url=PRIMARY.removesuffix('list.htm')),
                                primary(research='数据库系统'),PRIMARY)['research_direction_raw']=='数据库系统'


def test_primary_bio_only_uses_explicit_owned_direction():
    body=primary(bio='复旦大学计算与智能创新学院副教授、博士生导师，主要研究方向为自然语言处理和机器学习。'
                     '在国际期刊发表多篇论文。')
    assert fudan_cs.parse_detail(cfg(),body,PRIMARY)['research_direction_raw']=='自然语言处理和机器学习'
    body=primary(bio='当前研究方向为多模态大模型和类脑智能，在顶级期刊（如TPAMI）发表论文。')
    assert fudan_cs.parse_detail(cfg(),body,PRIMARY)['research_direction_raw']=='多模态大模型和类脑智能'
    for text in ('下文为合作者王乙的简介。研究方向为机器学习。', '学生王乙主要研究方向为机器学习。',
                 '1993年开始从事非单调逻辑研究。现讲授计算理论。'):
        assert 'research_direction_raw' not in fudan_cs.parse_detail(cfg(),primary(bio=text),PRIMARY)


def test_primary_declaration_has_priority_and_preserves_other_existing_direction():
    context=cfg()
    context['_read_source']=lambda url: pytest.fail('independent homepage should not be needed')
    assert fudan_cs.parse_detail(context,primary(research='学术检索'),PRIMARY)['research_direction_raw']=='学术检索'
    assert 'research_direction_raw' not in fudan_cs.parse_detail(cfg(research_direction_raw='手工核过的方向'),
                                                               primary(research='学术检索'),PRIMARY)
    with pytest.raises(ValueError,match='不同研究方向'):
        fudan_cs.parse_detail(context,primary(bio='目前研究方向为机器学习。当前研究领域为生物信息。'),PRIMARY)


def test_declared_alternate_direction_has_bound_source_and_verifies_both_people():
    context=cfg(email=ADDRESS)
    seen=[]
    def read(url):
        seen.append(url)
        return b'',faculty()
    context['_read_source']=read
    result=fudan_cs.parse_detail(context,primary(),PRIMARY)
    assert result['research_direction_raw']=='认知科学；智能机器人'
    assert result['_field_sources']=={'research_direction_raw':FACULTY}
    assert seen==[FACULTY]
    for page in (faculty(name='同名以外'),faculty(affiliation='别的学院'),faculty(address='other@fudan.edu.cn')):
        result=fudan_cs.parse_detail(dict(context,_read_source=lambda url:(b'',page)),primary(),PRIMARY)
        assert 'research_direction_raw' not in result
    assert 'research_direction_raw' not in fudan_cs.parse_detail(context,primary(homepage='https://faculty.fudan.edu.cn/another/'),PRIMARY)


def test_faculty_alternate_keeps_each_labelled_direction_line():
    content=(f'<title>{NAME} 中文主页--首页</title><div class="name"><strong>{NAME}</strong></div>'
             '<div class="item"><p>所属院系：计算与智能创新学院</p></div><div class="shworklist shworklist2">'
             '<h2>研究方向</h2><div class="yjfx"><p>·1、学术研究方向：计算机视觉；机器学习'
             '<br>2、应用研究领域：自动驾驶，服务机器人</p></div></div>')
    result=fudan_cs.parse_detail(dict(cfg(),_read_source=lambda url:(b'',content)),primary(),PRIMARY)
    assert result['research_direction_raw']=='计算机视觉；机器学习；自动驾驶，服务机器人'


def test_contact_hook_only_returns_owned_primary_fields_and_rejects_old_conflict():
    profile=cfg(homepage=None)['_original_profile']
    context={'_read_source':lambda url:(b'',primary())}
    reply=fudan_cs.parse_contact(context,profile)
    assert reply['email']==ADDRESS and reply['homepage']==FACULTY
    assert reply['_field_sources']=={'email':PRIMARY,'homepage':PRIMARY}
    assert 'email' not in fudan_cs.parse_contact(dict(context,_previous_email='old@fudan.edu.cn'),profile)
    blank={'_read_source':lambda url:(b'',primary(email='',homepage=''))}
    assert fudan_cs.parse_contact(blank,profile)=={}
    assert 'homepage' not in fudan_cs.parse_detail(cfg(),primary(),PRIMARY)


def test_opted_in_roster_returns_identity_only_and_does_not_fabricate_metadata(monkeypatch):
    row={'title':NAME,'cnUrl':PRIMARY,'email':ADDRESS,'exField4':'旧方向','exField5':FACULTY}
    monkeypatch.setattr(fudan_cs,'_query',lambda:[row])
    roster,meta=fudan_cs.iter_roster(cfg())
    assert meta is None
    assert roster==[{'name':NAME,'url':PRIMARY,'institutes':[]}]


def test_opted_in_fixture_preserves_nonempty_card_fields_and_does_not_infer_supervision():
    body=primary(research='具身智能').replace('</footer>', '</footer><div class="news_cara">'
                         '<span class="nr1">副教授</span><span class="nr2">非博士生导师</span></div>'
                         '<div class="news_tel"><span class="nr">000</span></div>')
    result=fudan_cs.parse_detail(cfg(title='教授',phone='123'),body,PRIMARY)
    assert not {'title','phone','supervisor'} & result.keys()
    assert result['research_direction_raw']=='具身智能'

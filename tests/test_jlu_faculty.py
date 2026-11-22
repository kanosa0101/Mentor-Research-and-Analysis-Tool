import pytest

from sites.jlu import jlu_cs


PERSON = 'https://ccst.jlu.edu.cn/info/1367/1234.htm'
ROSTER = 'https://ccst.jlu.edu.cn/szdw/zpzpjs.htm'
NEXT = 'https://ccst.jlu.edu.cn/szdw/zpzpjs/1.htm'


def profile(body, name='张老师'):
    return f'<title>{name}-吉林大学计算机科学与技术学院</title><div class="v_news_content">{body}</div>'


def config(**person):
    return {'_expected_name': '张老师', '_original_profile': {'name': '张老师', 'detail_url': PERSON, **person}}


def test_jlu_explicit_named_table_and_contact_are_bounded_to_self():
    html = profile('''<table><tr><td>所研究方向：</td><td>软件工程、形式化方法</td></tr>
        <tr><td>Email：</td><td>teacher@jlu.edu.cn</td></tr></table>
        <p>实验室学生邮箱：student@jlu.edu.cn</p><p>承担科研项目：无关项目</p>''')
    parsed = jlu_cs.parse_detail(config(), html, PERSON)
    assert parsed['name'] == '张老师'
    assert parsed['research_direction_raw'] == '软件工程、形式化方法'
    assert parsed['email'] == 'teacher@jlu.edu.cn'


def test_jlu_maintenance_preserves_registered_fields_and_does_not_guess_image_email(monkeypatch):
    def fail(*args):
        pytest.fail('maintenance may not fill a missing mailbox by guessing from an image')

    monkeypatch.setattr(jlu_cs, '_ocr_email_image', fail)
    html = profile('''<table><tr><td>所研究方向：</td><td>软件工程</td></tr>
        <tr><td>Email：</td><td><img vurl="/__local/contact.png"></td></tr></table>''')
    cfg = config(research_direction_raw='人工保留的方向', provenance={'research_direction_raw': {'origin': 'manual'}})
    parsed = jlu_cs.parse_detail(cfg, html, PERSON)
    assert 'research_direction_raw' not in parsed and 'email' not in parsed


def test_jlu_decodes_only_exact_named_contact_tokens_and_preserves_manual_markers():
    html = profile('''<table><tr><td><p>Email：</p></td><td><p>ruiATjluDOTeduDOTcn</p></td></tr></table>
        <p>研究团队邮箱：unrelatedATjluDOTeduDOTcn</p>''')
    assert jlu_cs.parse_detail(config(), html, PERSON)['email'] == 'rui@jlu.edu.cn'
    manual = config(provenance={'email': {'origin': 'manual'}})
    assert 'email' not in jlu_cs.parse_detail(manual, html, PERSON)
    ambiguous = profile('<p>Email：someoneATjlu</p><p>Email：otherATlabATjluDOTeduDOTcn</p>')
    assert 'email' not in jlu_cs.parse_detail(config(), ambiguous, PERSON)


def test_jlu_numbered_direction_keeps_same_section_and_stops_at_new_heading():
    html = profile('''<p>研究方向：</p><p>[1] 移动计算 / 群智感知</p><p>[2] 人工智能 / 大数据</p>
        <p>[3] 智能物联网 / 边缘计算</p><p>[4] 推荐系统 / 隐私保护</p>
        <p>教育背景</p><p>[1] 另一章节内容</p>''')
    assert jlu_cs.parse_detail(config(), html, PERSON)['research_direction_raw'] == (
        '[1] 移动计算 / 群智感知 [2] 人工智能 / 大数据 [3] 智能物联网 / 边缘计算 [4] 推荐系统 / 隐私保护')


def test_jlu_recurring_parse_reads_published_fields_and_current_personal_change():
    cfg = config(email='old@jlu.edu.cn', research_direction_raw='数据系统')
    source = profile('<p>研究方向：数据系统</p><p>Email：old@jlu.edu.cn</p>')
    old = jlu_cs.parse_detail(cfg, source, PERSON)
    assert (old['email'], old['research_direction_raw']) == ('old@jlu.edu.cn', '数据系统')
    updated = profile('<p>研究方向：机器学习</p><p>Email：new@jlu.edu.cn</p>'
                      '<p>招生信息：简历投递邮箱：team@jlu.edu.cn; other@jlu.edu.cn</p>')
    current = jlu_cs.parse_detail(cfg, updated, PERSON)
    assert (current['email'], current['research_direction_raw']) == ('new@jlu.edu.cn', '机器学习')


def card(name, href, direction, address):
    return (f'<div class="text fr"><a class="name" href="{href}">{name}</a>'
            f'<p class="info"><span>email：</span>{address}</p>'
            f'<p class="info yjfx"><span>研究方向：</span>{direction}</p></div>')


def test_jlu_current_roster_fallback_requires_person_link_and_tracks_page_proof():
    roster = '<title>准聘长聘教师-吉林大学计算机科学与技术学院</title><a href="zpzpjs/1.htm">2</a>'
    nested = ('<title>准聘长聘教师-吉林大学计算机科学与技术学院</title>' +
              card('张老师', '/info/1367/1235.htm', '其他人的方向', 'other@jlu.edu.cn') +
              card('张老师', '/info/1367/1234.htm', '数据系统', 'teacher@jlu.edu.cn'))
    pages = {ROSTER: roster, NEXT: nested}
    cfg = {**config(), 'profile_field_roster': ROSTER, '_read_source': lambda url: (b'', pages[url])}
    parsed = jlu_cs.parse_detail(cfg, profile('<p>暂无个人简介</p>'), PERSON)
    assert parsed['email'] == 'teacher@jlu.edu.cn' and parsed['research_direction_raw'] == '数据系统'
    assert parsed['_field_sources'] == {'email': NEXT, 'research_direction_raw': NEXT}
    published = config(email='teacher@jlu.edu.cn', research_direction_raw='数据系统')
    reread = jlu_cs.parse_detail({**cfg, **published}, profile('<p>暂无个人简介</p>'), PERSON)
    assert reread == parsed
    conflicting = profile('<p>Email：teacher@jlu.edu.cn</p><p>Email：second@jlu.edu.cn</p>')
    assert 'email' not in jlu_cs.parse_detail(cfg, conflicting, PERSON)
    with pytest.raises(ValueError, match='姓名'):
        jlu_cs.parse_detail(cfg, profile('<p>研究方向：数据系统</p>', '其他人'), PERSON)

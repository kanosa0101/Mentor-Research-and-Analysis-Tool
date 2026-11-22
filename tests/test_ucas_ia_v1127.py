import pytest

from sites.ucas.ucas_ia import parse_contact, parse_detail


DETAIL = 'https://ia.cas.cn/rcdw/yjy/202404/t20240422_7129847.html'
HOSTED = 'https://people.ucas.ac.cn/~chengjian'


def page(*sections, name='程健', card=''):
    parts = ''.join(f'<div class="gunius-list"><h3>{heading}</h3><div class="gunitem">{body}</div></div>'
                    for heading, body in sections)
    return (f'<title>{name}----中国科学院自动化研究所</title><div class="gunius-detail">'
            f'<div class="gunius-info"><span class="name">{name} / 研究员</span><ul>{card}</ul></div>'
            f'{parts}</div><footer>电子邮件: casia@ia.ac.cn</footer>')


@pytest.mark.parametrize(('section', 'expected'), [
    (('个人简历', '<table><tr><td>姓名</td><td>程健</td></tr>'
               '<tr><td>研究领域</td><td>智能控制与机器人</td></tr></table>'), '智能控制与机器人'),
    (('个人简历', '<p>研究方向</p><p>生成式模型、视觉内容鉴别</p><p>代表论著：论文内容</p>'),
     '生成式模型、视觉内容鉴别'),
    (('个人简介', '<p>研究方向 ： 自然语言处理、知识工程</p><p>科研项目：项目介绍</p>'),
     '自然语言处理、知识工程'),
    (('研究方向', '<p>高效神经网络计算、智能科学计算（AI4S）、无人自主系统</p>'
                f'<p>招生信息请访问个人主页：<a href="{HOSTED}">{HOSTED}</a></p>'),
     '高效神经网络计算、智能科学计算（AI4S）、无人自主系统'),
])
def test_extracts_only_official_direction_blocks(section, expected):
    result = parse_detail({'_expected_name': '程健'}, page(section), DETAIL)
    assert result['research_direction_raw'] == expected


def test_direction_withholds_other_people_and_conflicting_slots():
    other = ('个人简历', '<table><tr><td>姓名</td><td>程龙</td></tr>'
                      '<tr><td>研究领域</td><td>智能控制</td></tr></table>'
                      '<p>程龙的主要研究方向为人工智能。</p>')
    result = parse_detail({}, page(other, ('代表论著', '<p>研究方向：智能控制</p>')), DETAIL)
    assert 'research_direction_raw' not in result
    conflict = page(('个人简介', '<p>研究方向：智能控制</p><p>研究方向：知识工程</p>'))
    assert 'research_direction_raw' not in parse_detail({}, conflict, DETAIL)
    assert parse_detail({'_expected_name': '别人'}, page(other), DETAIL) == {}


@pytest.mark.parametrize('handoff', ['以下内容为合作者李乙的研究资料。', '下文介绍实验室整体情况。'])
def test_resume_topic_cannot_inherit_a_third_person_intro(handoff):
    other = f'<p>{handoff}</p><p>研究方向：数据库系统</p>'
    assert 'research_direction_raw' not in parse_detail({}, page(('个人简历', other)), DETAIL)
    own = '<p>中国科学院自动化研究所某实验室任职。</p><p>研究方向：控制理论</p>'
    assert parse_detail({}, page(('个人简历', own)), DETAIL)['research_direction_raw'] == '控制理论'
    restored = other+'<p>本人研究方向：模式识别</p>'
    assert parse_detail({}, page(('个人简历', restored)), DETAIL)['research_direction_raw'] == '模式识别'


def test_numbered_directions_keep_the_complete_labelled_section():
    section = ('个人简历', '<p>【研究领域】</p><p>1. 大模型驱动的信息检索与智能建模分析</p>'
               '<p>2. 多模态图像分析：针对科研设施项目需求（科研仪器研制项目，经费约8000万），开展磁信号成像研究。'
               '构建了智能控制与感知系统。</p><p>【学术成果与项目】</p><p>3. 学术成果</p>')
    result = parse_detail({}, page(section), DETAIL)
    assert result['research_direction_raw'] == ('1. 大模型驱动的信息检索与智能建模分析；'
                                                '2. 多模态图像分析：针对科研设施项目需求，开展磁信号成像研究')


def test_bulleted_directions_stop_when_the_resume_moves_on():
    section = ('个人简历', '<p>研究方向</p><p>· 复杂系统建模与仿真</p><p>· 博弈智能</p>'
               '<p>个人简历</p><p>工作及学习经历</p>')
    assert parse_detail({}, page(section), DETAIL)['research_direction_raw'] == '· 复杂系统建模与仿真；· 博弈智能'


@pytest.mark.parametrize('text', ['国家专用集成电路设计工程中心', '随着科研发展。微观重建团队聚焦于脑图谱新技术研究。'])
def test_named_direction_slot_may_describe_an_affiliation_or_team(text):
    section = ('个人简历', '<table><tr><td>姓名</td><td>程健</td></tr>'
               f'<tr><td>研究领域</td><td>{text}</td></tr></table>')
    assert 'research_direction_raw' not in parse_detail({}, page(section), DETAIL)


def test_named_person_explicitly_owns_the_following_topic_list():
    section = ('个人简历', '<table><tr><td>姓名</td><td>程健</td></tr><tr><td>研究领域</td>'
               '<td>这里是领域背景。本人及领导的团队致力于交叉研究，主要研究领域包括：医学影像、机器学习。'
               '</td></tr></table>')
    assert parse_detail({}, page(section), DETAIL)['research_direction_raw'] == '医学影像、机器学习'


def test_homepage_uses_only_a_declared_distinct_link():
    original = {'name': '程健', 'detail_url': DETAIL, 'profile_url': DETAIL}
    identity = {'_expected_name': '程健', '_original_profile': original}
    section = ('研究方向', f'<p>招生信息请访问个人主页：<a href="{HOSTED}">{HOSTED}</a></p>')
    assert 'homepage' not in parse_detail(identity, page(section), DETAIL)
    assert parse_contact({'_read_source': lambda url: (b'', page(section))}, original)['homepage'] == HOSTED
    for body in (f'<p>{HOSTED}</p>', f'<p>个人主页：{HOSTED}</p>',
                 f'<p>团队主页：<a href="{HOSTED}">团队网站</a></p>',
                 f'<p>个人主页：<a href="{DETAIL}">{DETAIL}</a></p>',
                 f'<p>学生个人主页：<a href="{HOSTED}">{HOSTED}</a></p>'):
        cfg = {'_read_source': lambda url: (b'', page(('个人简历', body)))}
        assert 'homepage' not in parse_contact(cfg, original)


def test_owned_contact_withholds_card_table_conflict_and_team_address():
    card = '<li>电子邮件: jian.cheng@ia.ac.cn</li>'
    no_direct = page(('个人简介', '<p>团队公共邮箱: group@ia.ac.cn</p>'))
    assert 'email' not in parse_detail({}, no_direct, DETAIL)
    assert parse_detail({}, page(card=card), DETAIL)['email'] == 'jian.cheng@ia.ac.cn'
    row = ('个人简历', '<table><tr><td>姓名</td><td>程健</td><td>联系方式</td>'
                     '<td>second@nlpr.ia.ac.cn</td></tr></table>')
    assert 'email' not in parse_detail({}, page(row, card=card), DETAIL)


def test_contact_hook_returns_only_verified_same_person_current_article_email():
    card = '<li>电子邮件: jian.cheng@ia.ac.cn</li>'
    person = {'name': '程健', 'detail_url': DETAIL}
    calls = []

    def read_source(url):
        calls.append(url)
        html = page(card=card)
        return html.encode(), html

    cfg = {'_read_source': read_source}
    assert parse_contact(cfg, person) == {'email': 'jian.cheng@ia.ac.cn', '_verified_roster_name': '程健',
                                         '_field_sources': {'email': DETAIL}}
    assert parse_contact(dict(cfg, _previous_email='jian.cheng@ia.ac.cn'), person)['email'] == 'jian.cheng@ia.ac.cn'
    assert parse_contact(dict(cfg, _previous_email='another@ia.ac.cn'), person) == {}
    assert parse_contact(cfg, dict(person, name='程龙')) == {}
    assert calls == [DETAIL] * 4

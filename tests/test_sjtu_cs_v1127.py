from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile

import pytest
import yaml

from crawler import mentor_fields, store
from scripts import crawl
from sites.sjtu import sjtu_cs
from sites.sjtu.sjtu_cs import parse_contact, parse_detail


ROOT = 'https://www.cs.sjtu.edu.cn'
DETAIL = ROOT + '/jiaoshiml/teacher.html'
HOME = ROOT + '/~teacher/'
NAME = '张　甲'
COLLEGE = '上海交通大学计算机学院（网络空间安全学院、密码学院）'


def card(*, name='张甲', title_name=None, biography='', extra='', contact=''):
    return f'''<title>{title_name or name}-{COLLEGE}</title>
    <div class="js-info"><div class="name">{name}</div><div class="zw">教授</div>
    <div class="dt">{contact}</div></div>
    <div class="js-dt"><div class="item"><div class="name">个人简介</div>
      <div class="txt">{biography}</div></div>{extra}</div>
    <footer><p>邮箱：scs@sjtu.edu.cn</p><p>研究方向：公共信息</p></footer>'''


def primary(**values):
    return dict({'name': NAME, 'detail_url': DETAIL, 'title': '教授'}, **values)


def parse(html, row=None):
    return parse_detail({'base_url': ROOT, '_expected_name': NAME, '_original_profile': row or primary()}, html, DETAIL)


def contact(html, **old):
    def read(url):
        assert url == DETAIL
        return html.encode(), html
    return parse_contact({'base_url': ROOT, '_read_source': read}, primary(**old))


@pytest.mark.parametrize(('intro', 'direction'), [
    ('以服务国家重大战略需求为目标，从事逻辑推理、图数据库等方面基础理论和关键应用研究。先后主持若干课题。',
     '逻辑推理、图数据库等方面基础理论和关键应用研究'),
    ('本科毕业于某大学。研究方向聚焦机器学习理论与算法，迄今累计发表多篇论文。', '机器学习理论与算法'),
    ('研究聚焦于密码工程、侧信道分析与防护等方向，提出若干方法。', '密码工程、侧信道分析与防护等方向'),
    ('张甲，现任教授。主要从事高性能计算、并行计算等方面的研究。', '高性能计算、并行计算等方面的研究'),
    ('张甲博士长期从事模式识别的基础研究，深耕分类和聚类，担任期刊编委。', '模式识别的基础研究，深耕分类和聚类'),
])
def test_only_named_intro_claim_is_extracted(intro, direction):
    parsed = parse(card(biography=intro))
    assert parsed['name'] == NAME
    assert parsed['research_direction_raw'] == direction


@pytest.mark.parametrize('intro', [
    '张甲的导师研究方向为机器学习。', '曾从事信号处理研究。', '欢迎申请人与本人交流研究方向。',
    '团队研究方向聚焦计算机体系结构。', '从事学生招生工作。', '主要从事并行计算系统的教学和研究工作。',
    '以下为合作者李乙的个人资料。研究方向聚焦图数据库。',
    '张甲参与筹建课题组：以下介绍团队整体情况。主要从事数据库相关研究。',
])
def test_mixed_or_other_person_topics_stay_blank(intro):
    extra = '<div class="item"><div class="name">论文发表</div><div class="txt">研究方向聚焦数据库。</div></div>'
    assert 'research_direction_raw' not in parse(card(biography=intro, extra=extra))


def test_dedicated_research_section_respects_its_own_boundary():
    extra = '''<div class="item"><div class="name">研究方向</div><div class="txt">密码学、网络安全</div></div>
    <div class="item"><div class="name">课程</div><div class="txt">人工智能</div></div>'''
    assert parse(card(extra=extra))['research_direction_raw'] == '密码学、网络安全'


def test_unsupported_unstructured_course_page_is_not_a_personal_introduction():
    html=card().replace('class="js-dt"', 'class="unrelated"')
    html+='<section class="js-dt"><h3>教学课程</h3><p>研究方向：数据库设计</p></section>'
    assert 'research_direction_raw' not in parse(html)


def test_verified_direction_before_team_introduction_is_retained():
    html=card(biography='研究方向聚焦图计算。以下介绍团队情况。主要从事数据库相关研究。')
    assert parse(html)['research_direction_raw']=='图计算'


def test_ajax_directory_ignores_foreign_and_inconsistent_people(monkeypatch):
    html=('<div class="rc-item"><a href="/jiaoshiml/teacher.html">张甲</a>'
          '<a href="/jiaoshiml/teacher.html">张甲（兼）</a>'
          '<a href="/jiaoshiml/conflict.html">张甲</a><a href="/jiaoshiml/conflict.html">张乙</a>'
          '<a href="https://other.edu.cn/jiaoshiml/foreign.html">张乙</a></div>')
    monkeypatch.setattr(sjtu_cs.fetch,'fetch_text',lambda *args:(json.dumps({'content':html}),{'fetched_at':'2026-11-23'},True))
    roster,_=sjtu_cs.iter_roster({'base_url': ROOT,'list':{'method':'POST','url':ROOT+'/ajax','params':{}}})
    assert roster==[{'name':'张甲','url':DETAIL,'institutes':[]}]


@pytest.mark.parametrize('html', [card(name='张乙'), card(title_name='张乙'),
                                  card()+ '<div class="js-info"><div class="name">张甲</div></div>'])
def test_identity_conflict_blocks_detail_and_contact(html):
    with pytest.raises(ValueError):
        parse(html)
    with pytest.raises(ValueError):
        contact(html)


@pytest.mark.parametrize('row', [primary(research_direction_raw='其它已登记方向'),
                                 primary(provenance={'research_direction_raw': {'origin': 'manual'}})])
def test_different_nonempty_or_manual_direction_is_not_proposed(row):
    assert 'research_direction_raw' not in parse(card(biography='研究方向聚焦机器学习。'), row)


@pytest.mark.parametrize(('printed', 'present'), [
    ('<p>邮箱：teacher@sjtu.edu.cn</p>', True),
    ('<p>邮箱：teacher@sjtu.edu.cn other@sjtu.edu.cn</p>', False),
    ('<p>邮箱：scs@sjtu.edu.cn</p>', False),
    ('<p>助理邮箱：teacher@sjtu.edu.cn</p>', False),
    ('<p>邮箱：<a href="mailto:wrong@sjtu.edu.cn">teacher@sjtu.edu.cn</a></p>', False),
])
def test_email_proves_visible_own_unique_address(printed, present):
    claimed = contact(card(contact=printed))
    if present:
        assert claimed['_verified_roster_name'] == NAME
        assert claimed['email'] == 'teacher@sjtu.edu.cn'
        assert claimed['_field_sources']['email'] == DETAIL
    else:
        assert 'email' not in claimed


def test_manual_existing_and_ambiguous_contacts_are_preserved():
    markup = card(contact='<p>邮箱：teacher@sjtu.edu.cn other@sjtu.edu.cn</p>')
    assert contact(markup, email='teacher@sjtu.edu.cn')['email'] == 'teacher@sjtu.edu.cn'
    assert 'email' not in contact(markup, email='old@sjtu.edu.cn')
    assert 'email' not in contact(markup, email='teacher@sjtu.edu.cn', provenance={'email': {'origin': 'manual'}})


def test_homepage_is_an_independent_visible_candidate_only():
    html = card(contact=f'<p>个人主页：<a href="{HOME}">{HOME}</a></p>')
    hit = contact(html)
    assert (hit['homepage'], hit['_field_sources']['homepage']) == (HOME, DETAIL)
    assert 'homepage' not in parse(html)
    for link in (DETAIL, 'javascript:void(0)'):
        assert 'homepage' not in contact(card(contact=f'<p>个人主页：<a href="{link}">查看</a></p>'))
    assert 'homepage' not in contact(card(contact='<p>个人主页：teacher.example.edu.cn</p>'))
    assert 'homepage' not in contact(html, provenance={'homepage': {'origin': 'manual'}})


def test_ordinary_cli_enrich_does_not_write_unverified_homepage_or_email(tmp_path,monkeypatch):
    path=tmp_path/'data/professors/sjtu/cs/first.yaml'
    path.parent.mkdir(parents=True)
    original=primary(slug='first',school='sjtu',dept='cs')
    path.write_text(yaml.safe_dump(original,allow_unicode=True),encoding='utf8')
    html=card(contact=f'<p>邮箱：teacher@sjtu.edu.cn</p><p>个人主页：<a href="{HOME}">{HOME}</a></p>')
    cfg=dict(school='sjtu',dept='cs',base_url=ROOT,hook='sjtu_cs',contact_hook_only=True)
    monkeypatch.setattr(store,'DATA',tmp_path/'data')
    monkeypatch.setattr(crawl.fetch,'fetch_text',lambda *args,**kw:(html,{'fetched_at':'2026-11-23'},True))
    report=crawl.phase_enrich(cfg,sjtu_cs,False)
    assert report['enriched']==1
    row=yaml.safe_load(path.read_bytes())
    assert not row.get('homepage') and not row.get('email')


@pytest.mark.parametrize('case', ['fill', 'occupied', 'other_person', 'manual'])
def test_stock_field_queue_validates_sjtu_contact_ownership_and_target(tmp_path, case):
    unit = tmp_path / 'sites/sjtu'
    unit.mkdir(parents=True)
    (unit / 'cs.yaml').write_text(yaml.safe_dump({'school': 'sjtu', 'dept': 'cs', 'base_url': ROOT,
        'hook': 'sjtu_cs', 'contact_hook_only': True, 'list': {'urls': [ROOT+'/jiaoshiml']}}), encoding='utf8')
    copyfile(Path(__file__).resolve().parents[1]/'sites/sjtu/sjtu_cs.py', unit/'sjtu_cs.py')
    path = tmp_path/'data/professors/sjtu/cs/first.yaml'
    path.parent.mkdir(parents=True)
    row = primary(slug='first', school='sjtu', dept='cs')
    email = 'teacher@sjtu.edu.cn'
    if case == 'occupied':
        owner = tmp_path/'data/professors/other/cs/second.yaml'
        owner.parent.mkdir(parents=True)
        owner.write_text(yaml.safe_dump(dict(row, slug='second', school='other',
                          detail_url='https://other.edu.cn/teacher', email=email),allow_unicode=True),encoding='utf8')
    if case == 'manual':
        row['provenance'] = {key:dict(origin='manual',source=DETAIL,fetched_at='2026-10-01',confidence='verified')
                             for key in ('email','homepage')}
    path.write_text(yaml.safe_dump(row,allow_unicode=True),encoding='utf8')
    links = '' if case == 'occupied' else f'<p>个人主页：<a href="{HOME}">{HOME}</a></p>'
    detail=card(contact=f'<p>邮箱：{email}</p>{links}').encode()
    home=('<h1>张乙</h1>' if case=='other_person' else f'<h1>{NAME}</h1>').encode()

    def fetch(source):
        return {DETAIL: detail, HOME: home}[source['url']]

    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    report = mentor_fields.run(tmp_path, units=('sjtu/cs',), limit=3, workers=1, fetcher=fetch, now=now)
    item = yaml.safe_load(path.read_bytes())
    assert report['attempted'] == 1
    assert item.get('email') == (email if case in ('fill','other_person') else None)
    assert item.get('homepage') == (HOME if case == 'fill' else None)
    if case == 'fill':
        proof = report['results'][0]['field_evidence']
        assert proof['email']['sha256'] == sha256(detail).hexdigest()
        assert proof['homepage']['sha256'] == sha256(detail).hexdigest()
        assert proof['homepage']['target_evidence']['sha256'] == sha256(home).hexdigest()
    if case == 'manual':
        assert all(item['provenance'][key] == row['provenance'][key] for key in ('email','homepage'))

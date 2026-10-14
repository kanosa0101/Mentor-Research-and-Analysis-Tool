import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def hook():
    spec = importlib.util.spec_from_file_location('related_v7', ROOT / 'sites/related_v7.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cfg(school, dept):
    return yaml.safe_load((ROOT / 'sites' / school / (dept + '.yaml')).read_text(encoding='utf-8'))


def test_csu_scope_attributes_and_pair_dedup():
    c = cfg('csu', 'auto')
    html = '''<div class="teachers-name">
    <a dept="人工智能系" title="副教授" type="博导" href="https://faculty.csu.edu.cn/a/zh_CN/index.htm">张三</a>
    <a dept="人工智能系" href="https://faculty.csu.edu.cn/a/zh_CN/index.htm">张三</a>
    <a dept="人工智能系" href="https://faculty.csu.edu.cn/b/zh_CN/index.htm">张三</a>
    <a dept="学生工作办公室" title="教授" href="https://faculty.csu.edu.cn/c/zh_CN/index.htm">李四</a>
    <a dept="人工智能系" title="博士" href="https://soa.csu.edu.cn/szdw/jcrc.htm">王五</a></div>'''
    rows = hook().collect(c, c['list']['urls'][0], html, '2020-01-02')
    assert len(rows) == 2
    assert rows[0]['title'] == '副教授'
    assert rows[0]['supervisor'] == '博导'
    assert rows[0]['roster_fetched_at'] == '2020-01-02'
    assert rows[0]['institutes'] == ['人工智能系']


def test_person_fields_exclude_navigation_papers_previous_jobs_and_cipher():
    html = '''<nav>博士生导师 教授 邮箱：public@csu.edu.cn</nav>
    <div class="jbqk"><p>职称：博士</p><p>所在单位：自动化学院</p>
    <p>电子邮箱：<span _tsites_encrypt_field="x">abc123</span></p></div>
    <div class="con_bload"><h2>个人简介</h2><p>曾任教授。论文通讯作者：paper@csu.edu.cn</p></div>
    <div class="con_bload"><h2>研究方向</h2><p>机器视觉</p></div>'''
    d = hook().parse_profile(cfg('csu', 'auto'), html, 'https://faculty.csu.edu.cn/a/zh_CN/index.htm')
    assert not d.get('title') and not d.get('supervisor') and not d.get('email')
    assert d['research_directions'] == ['机器视觉']
    assert '曾任教授' in d['bio_raw']


def test_explicit_identity_and_contact():
    html = '''<div class="jbqk"><p>职称：副教授</p><p>博士生导师 硕士生导师</p>
    <p>所在单位：自动化学院</p><p>邮箱：my@csu.edu.cn</p></div>'''
    d = hook().parse_profile(cfg('csu', 'auto'), html, 'https://faculty.csu.edu.cn/a/zh_CN/index.htm')
    assert d['title'] == '副教授'
    assert d['supervisor'] == '博导、硕导'
    assert d['email'] == 'my@csu.edu.cn'


def test_split_supervision_and_direction_heading_are_not_values():
    html = '''<div class="jbqk">教授<p>博士生导师</p><p>硕士生导师</p><p>所在单位：自动化学院</p></div>
    <div class="blockwhite"><div class="title"><div class="info"><h2>研究方向</h2><p>Research focus</p></div></div><div class="cont"><li>机器人</li></div></div>'''
    d = hook().parse_profile(cfg('csu', 'auto'), html, 'https://faculty.csu.edu.cn/a/zh_CN/index.htm')
    assert d['supervisor'] == '博导、硕导'
    assert d['research_directions'] == ['机器人']


def test_h1_template_reads_named_profile_section_and_identity():
    html = '''<div class="photobox"><div class="name"><h1>桂康</h1><p>助理研究员</p></div></div>
    <div class="brief"><div class="data">所在单位：重点实验室</div></div>
    <div class="itembox"><div class="part_tit"><h1>个人简介</h1></div><div class="part_nr">这是本人公开简介。</div></div>'''
    d = hook().parse_profile(cfg('hust', 'aia'), html, 'http://faculty.hust.edu.cn/a/zh_CN/index.htm')
    assert d['title'] == '助理研究员'
    assert '这是本人公开简介' in d['bio_raw']


def test_nested_direction_section_stops_at_other_fields():
    html = '''<div class="jbqk">职称：教授<p>所在单位：自动化学院</p></div><div class="con_bload"><h2>个人简介</h2>
    <p>某某教授发表论文。<h2>研究方向</h2><p>机器视觉</p><p>招生：联系other@csu.edu.cn</p>
    <h2>科研项目</h2><p>不可并入方向的项目</p></p></div>'''
    d = hook().parse_profile(cfg('csu', 'auto'), html, 'https://faculty.csu.edu.cn/a/zh_CN/index.htm')
    assert d['research_directions'] == ['机器视觉']


def test_empty_and_failed_rosters_do_not_mean_no_teachers():
    h = hook()
    with patch.object(h.fetch, 'fetch_text', return_value=('<html/>', {'fetched_at': '2020-01-02'}, True)):
        with pytest.raises(ValueError):
            h.iter_roster(cfg('csu', 'auto'))


def test_unregistered_pagination_fails_closed():
    h = hook()
    with patch.object(h.fetch, 'fetch_text', return_value=('<a>下一页</a>', {'fetched_at': '2020-01-02'}, True)):
        with pytest.raises(ValueError, match='分页'):
            h.iter_roster(cfg('hust', 'aia'))


def test_only_new_units_and_explicit_supervision():
    for school, dept in [('hust', 'aia'), ('csu', 'auto')]:
        c = cfg(school, dept)
        assert c['explicit_supervisor_only'] is True
        assert c['hook'] == 'related_v7'
        assert c['roster_pending']


def test_detail_requires_same_person_before_field_import():
    h = hook()
    c = cfg('csu', 'auto')
    u = 'https://faculty.csu.edu.cn/a/zh_CN/index.htm'
    c['_roster_names'] = {u: '张三'}
    with pytest.raises(ValueError, match='身份'):
        h.parse_detail(c, '<title>中南大学 李四</title><div class="jbqk">职称：教授<p>邮箱：other@csu.edu.cn</p></div>', u)


def test_english_title_with_explicit_chinese_identity_is_supported():
    h = hook()
    c = cfg('csu', 'auto')
    u = 'https://faculty.csu.edu.cn/a/zh_CN/index.htm'
    c['_roster_names'] = {u: '张三'}
    d = h.parse_detail(c, '<title>Central South University Zhang San</title><div class="name">张三</div><div class="jbqk">职称：教授</div>', u)
    assert d['title'] == '教授'

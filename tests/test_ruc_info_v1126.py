from html import escape

import pytest

from crawler import legacy_refresh
from sites.ruc import ruc_info


SCHOOL = 'https://info.ruc.edu.cn'
PAGE = f'{SCHOOL}/jsky/szdw/ajxjgcx/jjxxglx1/fjs_a/' + '1' * 32 + '.htm'
ROSTER = f'{SCHOOL}/jsky/szdw/ajxjgcx/bx/bx1/index.htm'
NAME = '王老师'


def profile(intro='', details='', contact='', name=NAME):
    return (f'<title>{name} - 中国人民大学信息学院</title><div class="content">'
            f'<div class="card_box"><div class="card"><div class="name">{name}</div>'
            f'<div class="self_intro">{intro}</div><div class="contact">{contact}</div></div></div>'
            f'{details}</div>')


def section(heading, contents):
    return f'<div class="pro_info"><div class="h2"><div class="name">{heading}</div></div>{contents}</div>'


def test_named_section_keeps_long_explicit_directions_and_stops_at_unrelated_subsection():
    topics = ['智能数据系统' + '算法优化' * 255, '多模态检索', '端侧视觉计算']
    details = section('主要研究方向', ''.join(f'<p>{text}</p>' for text in topics) +
                      '<p>指导学生</p><p>这行属于学生履历</p>') + section('讲授课程', '<p>计算机入门</p>')
    raw = profile('研究方向是简介中的旧领域。', details)
    parsed = ruc_info.parse_detail({'_expected_name': NAME}, raw, PAGE)
    assert parsed['name'] == NAME and parsed['research_direction_raw'] == '；'.join(topics)
    original = dict(name=NAME, slug='wanglaoshi', school='ruc', dept='info', detail_url=PAGE)
    updated, changed, _ = legacy_refresh.merge_profile(original, parsed, raw.encode(), '2026-11-23')
    assert 'research_direction_raw' in changed and updated['research_direction_raw'] == '；'.join(topics)


def test_in_section_labels_do_not_truncate_explicit_context_through_common_merge():
    raw = profile(details=section('研究方向', '<p>我们研究端侧系统。具体研究方向包括：</p>'
                                             '<p>多模态检索。</p><p>高效架构。</p>'))
    person = dict(name=NAME, slug='wanglaoshi', school='ruc', dept='info', detail_url=PAGE)
    parsed = ruc_info.parse_detail({'_original_profile': person}, raw, PAGE)
    updated, _, _ = legacy_refresh.merge_profile(person, parsed, raw.encode(), '2026-11-23')
    assert updated['research_direction_raw'] == '我们研究端侧系统；多模态检索；高效架构'


def test_personal_intro_requires_explicit_topic_and_handles_both_role_names():
    raw = profile('教授、管理科学专业博导、硕导。主要研究方向为信息系统与决策优化。发表论文若干。',
                  section('研究方向', '<div class="para"></div>'))
    parsed = ruc_info.parse_detail({}, raw, PAGE)
    assert parsed['research_direction_raw'] == '信息系统与决策优化'
    assert parsed['supervisor'] == '博导、硕导'
    unrelated = profile('教授，曾任博士生导师。', section('科研成果', '<p>研究方向是生成模型的论文获奖</p>'))
    rejected = ruc_info.parse_detail({}, unrelated, PAGE)
    assert 'research_direction_raw' not in rejected and 'supervisor' not in rejected


def test_contact_requires_unique_label_in_identified_persons_own_contact_scope():
    raw = profile(details=section('招生信息', '<p>电子邮箱：team@ruc.edu.cn</p>'),
                  contact='<p>电子邮箱：<a href="mailto:other@ruc.edu.cn">person@ruc.edu.cn</a> DBLP</p>')
    assert ruc_info.parse_detail({}, raw, PAGE)['email'] == 'person@ruc.edu.cn'
    assert 'email' not in ruc_info.parse_detail({'_original_profile': {'name': NAME, 'email': 'old@ruc.edu.cn'}}, raw, PAGE)
    both = profile(contact='<p>电子邮箱：one@ruc.edu.cn; two@ruc.edu.cn</p>')
    assert 'email' not in ruc_info.parse_detail({}, both, PAGE)
    placeholder = profile(contact='<p>电子邮箱：unresolved@(RUC邮箱地址)</p>')
    assert 'email' not in ruc_info.parse_detail({}, placeholder, PAGE)


def test_alias_or_retired_page_does_not_establish_current_fields():
    raw = profile('博士生导师。', section('研究方向', '<p>信息系统</p>'), '<p>电子邮箱：person@ruc.edu.cn</p>')
    with pytest.raises(ValueError, match='姓名'):
        ruc_info.parse_detail({'_expected_name': '李老师'}, raw, PAGE)
    retired = ruc_info.parse_detail({}, raw, f'{SCHOOL}/jsky/rtjs/' + '1' * 32 + '.htm')
    assert not {'email', 'supervisor', 'research_direction_raw'}.intersection(retired)


def test_roster_reads_explicit_child_name_and_withholds_conflicting_hrefs(monkeypatch):
    def card(name, href):
        return f'<a href="{escape(href)}"><div class="research-text"><div class="text1">{name}</div>研究方向：数据库</div></a>'

    same_name = PAGE.replace('1' * 32, '2' * 32)
    other = PAGE.replace('1' * 32, '3' * 32)
    first = card(NAME, PAGE) + card('田老师', other)
    second = card(NAME, same_name)
    pages = {ROSTER: first, ROSTER.removesuffix('index.htm') + 'index2.htm': second}
    monkeypatch.setattr(ruc_info.fetch, 'fetch_text', lambda method, url: (pages.get(url, ''), {}, False))
    rows, _ = ruc_info.iter_roster({'list': {'channels': [{'url': ROSTER}]}})
    assert [(row['name'], row['url']) for row in rows] == [('田老师', other)]

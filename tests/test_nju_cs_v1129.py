import pytest

from crawler.mentor_recovery import IdentityConflict
from sites.nju import nju_cs


URL = 'https://cs.nju.edu.cn/58/16/c2639a153622/page.htm'
PERSON = {'name': '甲教师', 'detail_url': URL}


def article(body='', *, title='甲 教师（院士、博导）', head=''):
    return f'<html><head>{head}</head><div class="article"><h1 class="arti_title">{title}</h1>' \
           f'<div class="wp_articlecontent">{body}</div></div></html>'


def parsed(body, *, person=PERSON):
    return nju_cs.parse_detail({'_expected_name': person['name'], '_original_profile': person}, article(body), URL)


def contact(body, *, person=PERSON, previous=None):
    html = article(body)
    return nju_cs.parse_contact({'_read_source': lambda _: (html.encode(), html), '_previous_email': previous}, person)


def test_numbered_direction_keeps_all_seven_parts_and_stops_at_next_section():
    details = '软件测试与软件质量保证；智能计算及其应用；智能与学习软件设计与测试；' \
              '软硬件故障大数据挖掘与应用；容错与可靠性；软件形式化方法与应用；应用驱动的大数据系统设计与测试'
    fields = parsed(f'<p>1 、个人简介：南京大学计算机学院</p><p>2 、<b>研究方向：</b>{details}</p>'
                    '<p>3 、科研项目：与研究无关的历史项目</p>')
    assert fields['research_direction_raw'] == details
    assert fields['research_directions'] == [details]


def test_standalone_heading_with_numbered_items_and_inline_fragments():
    fields = parsed('<p>学术任职</p><p>学术委员会委员</p><p>具体研究方向：</p>'
                    '<div>1.量子信息论<br>2.分布式<span>数据结构</span><div></div></div>'
                    '<p>代表性论文：</p><p>期刊论文标题</p>')
    assert fields['research_direction_raw'] == '1.量子信息论；2.分布式数据结构'


def test_named_direction_keeps_application_stops_before_publications():
    fields = parsed('<p>甲教师，南京大学计算机学院教授，研究方向为程序分析，专注模型推理，'
                    '在软件领域相关国际顶级期刊和会议，如TOPLAS、PLDI等发表学术论文30余篇。</p>')
    assert fields['research_direction_raw'] == '程序分析，专注模型推理'


def test_self_statement_preserves_current_topics_stops_before_grants():
    fields = parsed('<p>甲教师博士长期从事智能计算系统、云边端协同计算等研究工作，近期聚焦大模型性能优化、'
                    '分布式机器学习与异构算力调度等研究主题，近年来先后主持国家自然科学基金重点项目。</p>')
    assert fields['research_direction_raw'] == '智能计算系统、云边端协同计算等，近期聚焦大模型性能优化、分布式机器学习与异构算力调度等研究主题'


@pytest.mark.parametrize('body', [
    '<p>以下内容为合作者李乙的研究资料。</p><p>研究方向：数据库系统</p>',
    '<p>下文介绍实验室整体情况。</p><p>研究方向：数据库系统</p>',
    '<p>课题组简介</p><p>研究方向：数据库系统</p>',
    '<p>甲教师曾在外校从事博士后研究工作。</p><p>师从李乙教授，李乙的研究领域为数据库系统。</p>',
    '<p>以《研究方向：数据库系统》为题发表会议论文。</p><p>主讲数据库系统与通信网络。</p>',
    '<p>研究方向：数据库系统</p><p>研究方向：通信网络</p>',
    '<p hidden>研究方向：数据库系统</p><p style="display: none">研究方向：通信网络</p>',
    '<p>姓名一致但正文只有名片。</p>',
])
def test_ambiguous_or_non_personal_directions_are_not_extracted(body):
    assert parsed(body) == {'name': PERSON['name']}


def test_return_same_value_for_recheck_preserve_different_direction():
    body = '<p>研究方向：数据库系统</p>'
    assert 'research_direction_raw' not in parsed(body, person={**PERSON, 'research_direction_raw': '非空人工方向'})
    assert parsed(body, person={**PERSON, 'research_direction_raw': '数据库系统'})['research_direction_raw'] == '数据库系统'


def test_normal_maintenance_can_recheck_only_exact_unchanged_crawled_biography():
    biography = '甲教师，南京大学计算机学院教授、博士生导师。'
    html = article(f'<p>{biography}</p>')
    proof = {'origin': 'crawled', 'source': URL}

    def reader(_):
        pytest.fail('The already supplied source should not be read again')

    def verify(previous_bio, source=proof):
        record = {**PERSON, 'bio_raw': previous_bio, 'provenance': {'bio_raw': source}}
        return nju_cs.parse_detail({'_original_profile': record, '_read_source': reader}, html, URL)

    assert verify(biography) == {'name': PERSON['name'], 'bio_raw': biography}
    assert verify(biography, {**proof, 'origin': 'manual'}) == {'name': PERSON['name']}
    assert verify(biography, {**proof, 'source': 'https://cs.nju.edu.cn/another/'}) == {'name': PERSON['name']}
    assert verify('不同已登记简介') == {'name': PERSON['name']}
    assert verify(None) == {'name': PERSON['name']}
    assert parsed(f'<p>{biography}</p>', person={**PERSON, 'bio_raw': biography,
                                                 'provenance': {'bio_raw': proof}}) == {'name': PERSON['name']}


def test_reject_wrong_registered_path_and_conflicting_title_or_canonical():
    other = URL.replace('a153622', 'a153623')
    ctx = {'_original_profile': PERSON}
    for html, url in ((article(title='李乙'), URL), (article(), other),
                      (article(head=f'<link rel="canonical" href="{other}">'), URL)):
        with pytest.raises(IdentityConflict):
            nju_cs.parse_detail(ctx, html, url)


def test_contact_hook_requires_exact_personal_label_and_keeps_the_literal_target():
    home = 'https://cs.nju.edu.cn/~jia/'
    body = f'<div>电话：12345 个人主页网址：<a href="/~jia/">{home}</a> 电子邮件：jia @ nju.edu.cn</div>'
    fields = contact(body)
    assert fields == {'homepage': home, 'email': 'jia@nju.edu.cn', '_verified_roster_name': PERSON['name'],
                      '_field_sources': {'homepage': URL, 'email': URL}}
    assert nju_cs.parse_detail({'_original_profile': PERSON}, article(body), URL) == {'name': PERSON['name']}
    assert not contact(body, person={**PERSON, 'homepage': 'http://SecLa'}, previous='other@nju.edu.cn')


@pytest.mark.parametrize('body', [
    '<p><a href="/lab/">实验室主页</a></p>',
    '<p>个人主页：http://cs.nju.edu.cn/jia</p>',
    '<p>个人主页：https://another.nju.edu.cn/jia</p>',
    '<p>个人主页：<a href="/lab/">https://cs.nju.edu.cn/jia</a></p>',
    '<p>个人主页：<a href="https://cs.nju.edu.cn/jia?q=wrong">https://cs.nju.edu.cn/jia</a></p>',
    '<p>电子邮箱：<a href="mailto:other@nju.edu.cn">jia@nju.edu.cn</a></p>',
    '<p>学生联系方式：邮箱：jia@nju.edu.cn</p>',
    '<p>电子邮件：jia at nju.edu.cn</p>',
    '<p>电子邮件：jia@nju.edu.cn</p><p>电子邮件：other@nju.edu.cn</p>',
    '<p>电子邮件：info@nju.edu.cn</p>',
])
def test_contact_hook_refuses_team_links_mixed_addresses_and_incomplete_urls(body):
    assert not contact(body)

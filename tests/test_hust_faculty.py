from pathlib import Path

import pytest
import yaml

from crawler import legacy_refresh
from sites.hust import hust_faculty


URL = 'https://cse.hust.edu.cn/info/1128/1000.htm'
HTML = '''
<h1 class="am-article-title">张三</h1>
<div class="am-article-hd"><h1>张三</h1></div>
<div class="v_news_content">
  <p><span>张三</span><br><span>邮箱:</span><span>zhangs</span><span>@hust.edu.cn</span></p>
  <p>学生邮箱：student@example.org</p>
  <p style="display:none">邮箱：hidden@example.org</p>
  <p>个人简介</p><p>张三，教授，博士生导师。主要研究方向为人工智能、数据管理。</p>
</div><footer>邮箱：cyberse@hust.edu.cn</footer>
'''


def test_college_article_visible_contact_reaches_scheduled_hooks(tmp_path):
    original = {'name': '张三', 'slug': 'zhangsan', 'school': 'hust', 'dept': 'cyber', 'detail_url': URL}
    cfg = {'school': 'hust', 'dept': 'cyber', 'hook': 'hust_faculty'}
    assert hust_faculty.parse_contact(dict(cfg, _read_source=lambda url: (HTML.encode(), HTML)), original) == {
        'name': '张三', 'email': 'zhangs@hust.edu.cn', '_field_sources': {'email': URL},
    }
    with pytest.raises(ValueError, match='所登记人员不符'):
        hust_faculty.parse_detail(dict(cfg, _expected_name='李四'), HTML, URL)

    hook_path = tmp_path / 'sites/hust/hust_faculty.py'
    hook_path.parent.mkdir(parents=True)
    hook_path.write_bytes(Path(hust_faculty.__file__).read_bytes())
    hook_path.with_name('cyber.yaml').write_text(yaml.safe_dump(cfg), encoding='utf-8')
    profile = tmp_path / 'data/professors/hust/cyber/zhangsan.yaml'
    profile.parent.mkdir(parents=True)
    profile.write_text(yaml.safe_dump(original), encoding='utf-8')
    report = legacy_refresh.run(tmp_path, kind='professors', limit=1, workers=1,
                                fetcher=lambda source: HTML.encode())
    assert report['ok'] == 1
    restored = yaml.safe_load(profile.read_bytes())
    assert restored['email'] == 'zhangs@hust.edu.cn'
    assert restored['provenance']['email']['source'] == URL


def test_ambiguous_addresses_and_mixed_roster_ranks_stay_unknown():
    ambiguous = HTML.replace('学生邮箱：student@example.org', '邮箱：other@hust.edu.cn')
    parsed = hust_faculty.parse_detail({'school': 'hust', 'dept': 'cyber', '_expected_name': '张三'}, ambiguous, URL)
    assert 'email' not in parsed
    html = '''<div class="jcrc">
        <div class="rc_bt"><h6>教授/研究员</h6></div><div class="bt"><a href="/info/1/1.htm">王五</a></div>
        <div class="rc_bt"><h6>副教授</h6></div><div class="bt"><a href="/info/1/2.htm">张三</a></div>
    </div>'''
    assert hust_faculty.cyber_titles(html, URL) == [('张三', 'https://cse.hust.edu.cn/info/1/2.htm', '副教授')]


def test_lab_uses_only_matching_faculty_card_and_registers_its_source():
    lab = 'https://cse-sinclab.hust.edu.cn/ryjj.htm'
    official = '<div class="member"><table><tr><td><p><b>张 三</b> 教授</p><p>华中科技大学 网络空间安全学院</p><p>邮箱：zhang@hust.edu.cn</p></td></tr></table></div>'
    other_unit = official.replace('网络空间安全学院', '数学与统计学院')
    empty = HTML.replace('<span>zhangs</span><span>@hust.edu.cn</span>', '')
    profile = {'name': '张三', 'detail_url': URL}

    def reader(url):
        value = {URL: empty, lab: official + other_unit}[url]
        return value.encode(), value

    assert hust_faculty.parse_contact({'dept': 'cyber', '_read_source': reader, 'contact_lab_url': lab}, profile) == {
        'name': '张三', 'email': 'zhang@hust.edu.cn', '_field_sources': {'email': lab},
    }
    assert not hust_faculty.cyber_lab_email(official * 2, '张三')


def test_aia_secondary_email_uses_the_current_named_article():
    portal = 'http://faculty.hust.edu.cn/known/zh_CN/index.htm'
    directory = 'https://aia.hust.edu.cn/szdw1/axmpyszmlb/X.htm'
    article = 'https://aia.hust.edu.cn/info/1594/1234.htm'
    bodies = {
        portal: '<title>华中科技大学主页平台管理系统 张三--中文主页--首页</title>',
        directory: '<div class="list"><ul><li><a href="/info/1594/1234.htm"><h2>张三</h2></a></li></ul></div>',
        article: '<div class="content_title"><h1>张三</h1></div><div class="v_news_content"><div class="txt"><p>邮箱：name@hust.edu.cn</p></div></div>',
    }

    def reader(url):
        return bodies[url].encode(), bodies[url]

    person = {'name': '张三', 'slug': 'x-fixture', 'detail_url': portal}
    cfg = {'dept': 'aia', 'contact_article_directories': {'x': directory}, '_read_source': reader}
    result = hust_faculty.parse_contact(cfg, person)
    assert result['email'] == 'name@hust.edu.cn' and result['_field_sources']['email'] == article
    assert result['_contact_locator']['email']['article_url'] == directory
    bodies[article] = bodies[article].replace('张三', '李四')
    with pytest.raises(ValueError, match='所登记人员不符'):
        hust_faculty.parse_contact(cfg, person)


@pytest.mark.parametrize(('raw','expected'),[
    ('软件供应链安全、移动安全、人工智能安全等，在包括CCS等会议/期刊上', '软件供应链安全、移动安全、人工智能安全等'),
    ('云原生安全、操作系统与虚拟化安全，在安全顶级会议和期刊上', '云原生安全、操作系统与虚拟化安全'),
    ('多模态大模型和智慧医疗：首次提出面向病理图像的视觉定位任务', '多模态大模型和智慧医疗'),
    ('（1）理论计算机科学：致力于具有可证... More+', None),
])
def test_direction_uses_topics_without_truncated_or_publication_prose(raw, expected):
    assert hust_faculty.clean_direction(raw) == expected


def test_truncated_profile_uses_same_person_full_biography_with_its_provenance():
    portal = 'http://faculty.hust.edu.cn/known/zh_CN/index.htm'
    full = 'http://faculty.hust.edu.cn/known/zh_CN/more/42/jsjjgd/index.htm'
    title = '<title>华中科技大学主页平台管理系统 张三--中文主页--首页</title>'
    biography = title + '<div class="dft-midcont"><div class="Psl-info"><div class="cont">主要研究方向包括：理论计算机科学... <a href="'+full+'">More+</a></div></div></div>'
    article = title + '<div class="zw-article"><div class="atccont">主要研究方向包括：理论计算机科学、可信人工智能。</div></div>'
    cfg = {'school':'hust','dept':'aia','_expected_name':'张三'}
    assert not hust_faculty.parse_detail(cfg, biography, portal).get('research_direction_raw')

    def reader(url):
        assert url == full
        return article.encode(), article

    result = hust_faculty.parse_detail(dict(cfg,_read_source=reader), biography, portal)
    assert result['research_direction_raw'] == '理论计算机科学、可信人工智能'
    assert result['_field_sources']['research_direction_raw'] == full

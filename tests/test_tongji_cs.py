from pathlib import Path
from shutil import copyfile
from urllib.parse import parse_qs, urlsplit

import yaml

from crawler import legacy_refresh
from sites.tongji import tongji_cs


ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / 'sites/tongji/cs.yaml').read_text(encoding='utf-8'))


def test_academy_roster_follows_category_next_page_and_allows_only_named_official_profiles():
    page = CFG['list']['channels'][0]['url']
    rows, following = tongji_cs.parse_roster_page(CFG, '''
      <a class="con" href="../../info/1065/3462.htm"><h4 class="tit">测试甲</h4></a>
      <a class="con" href="http://faculty.tongji.edu.cn/sample/zh_CN/index.htm"><h4 class="tit">测试乙</h4></a>
      <a class="con" href="https://example.invalid/info/1065/3463.htm"><h4 class="tit">测试丙</h4></a>
      <a class="con" href="../../info/1065/3464.htm" title="他人"><h4 class="tit">公开新闻介绍</h4></a>
      <span class="p_next"><a href="js_yjy_/4.htm">下页</a></span>
    ''', page)
    assert [r['name'] for r in rows] == ['测试甲', '测试乙']
    assert rows[1]['url'] == 'https://faculty.tongji.edu.cn/sample/zh_CN/index.htm'
    assert rows[0]['roster_source'] == page
    assert following == 'https://cs.tongji.edu.cn/szdw/jsmlx/js_yjy_/4.htm'
    assert tongji_cs.parse_roster_page(CFG, '<span class="p_next"><a href="3.htm">下页</a></span>', following)[1].endswith('/js_yjy_/3.htm')


def test_university_roster_requires_the_computer_science_unit_on_each_row():
    page = CFG['list']['channels'][-1]['url']
    rows, following = tongji_cs.parse_roster_page(CFG, '''
      <a href="/first/zh_CN/index.htm"><p>测试甲</p><p>计算机科学与技术学院</p></a>
      <a href="/second/zh_CN/index.htm"><p>测试乙</p><p>软件学院</p></a>
      <a class="Next" href="?id=3543&amp;PAGENUM=2">下页</a>
    ''', page)
    assert [r['name'] for r in rows] == ['测试甲']
    assert following is None


def test_academy_profile_uses_the_persons_own_fields_and_keeps_their_source_lines():
    url = 'https://cs.tongji.edu.cn/info/1065/3462.htm'
    html = '''<title>测试甲-同济大学计算机科学与技术学院</title>
      <div class="teamnr"><div class="txt"><h5>测试甲</h5><p>职　称：长聘副教授</p>
      <p>电子邮件：first@example.edu.cn</p><p>导师类型：博导/硕导</p></div></div>
      <div class="teamtxt"><div class="v_news_content">
        <p>测试甲，现任同济大学计算机科学与技术学院长聘副教授。主要研究方向为多模态检索、视觉生成。</p>
        <p>代表性论文</p><p>其他研究方向为无关研究</p>
      </div></div><footer>电子邮箱：cs@example.edu.cn</footer>'''
    fields, quotes = tongji_cs.parse_detail_evidence(html, url)
    assert fields['email'] == 'first@example.edu.cn'
    assert fields['title'] == '长聘副教授'
    assert fields['supervisor'] == '博导、硕导'
    assert fields['research_direction_raw'] == '多模态检索、视觉生成'
    assert quotes['email'] == '电子邮件：first@example.edu.cn'
    assert {key for key in quotes} == {'email', 'title', 'supervisor', 'research_direction_raw'}
    assert tongji_cs.parse_detail({'_expected_name': '测试乙'}, html, url) == {}
    assert tongji_cs.parse_detail({}, html.replace('h5>测试甲', 'h5>测试乙'), url) == {}


def test_profile_excludes_research_from_education_and_normalizes_the_labelled_address_only():
    url = 'https://cs.tongji.edu.cn/info/1065/3462.htm'
    html = '''<title>测试甲-同济大学计算机科学与技术学院</title>
      <div class="teamnr"><div class="txt"><h5>测试甲</h5>
      <p>电子邮件：first (at) example.edu.cn</p></div></div>
      <div class="teamtxt"><div class="v_news_content">
        <p>教育经历</p><p>研究方向：历史关系挖掘</p><p>学位：博士</p>
        <p>研究兴趣</p><p>研究方向</p><p>:</p><p>图表示学习、流数据</p>
        <p>相关领域</p><p>另一个关联领域</p>
      </div></div>'''
    fields, proof = tongji_cs.parse_detail_evidence(html, url)
    assert fields['research_direction_raw'] == '图表示学习、流数据'
    assert fields['email'] == 'first@example.edu.cn'
    assert proof['email'] == '电子邮件：first (at) example.edu.cn'


def test_university_profile_distinguishes_its_own_advisor_status_from_navigation_and_old_roles():
    url = 'https://faculty.tongji.edu.cn/first/zh_CN/index.htm'
    html = '''<title>同济大学主页平台管理系统 测试甲--中文主页--首页</title>
      <div class="leftside"><p class="name">测试甲</p><p>长聘教授</p>
      <a>同专业博导</a><a>同专业硕导</a><p>邮箱：office@example.edu.cn</p></div>
      <div><h2>个人简介</h2><p>测试甲，曾任同济大学博士生导师，已退休。</p></div>
      <div><h2>研究方向</h2><p>空间智能</p><p>向量数据管理</p></div>'''
    fields, _ = tongji_cs.parse_detail_evidence(html, url)
    assert fields['title'] == '长聘教授'
    assert fields['research_direction_raw'] == '空间智能 向量数据管理'
    assert 'supervisor' not in fields
    assert 'email' not in fields
    updated, _ = tongji_cs.parse_detail_evidence(html.replace('曾任同济大学博士生导师，已退休', '现任同济大学研究员，硕博导师'), url)
    assert updated['supervisor'] == '博导、硕导'


def test_scheduled_refresh_replays_the_public_person_profile_and_its_email_display(tmp_path):
    url = 'https://faculty.tongji.edu.cn/first/zh_CN/index.htm'
    site = tmp_path / 'sites/tongji'
    site.mkdir(parents=True)
    for file in ('cs.yaml', 'tongji_cs.py'):
        copyfile(ROOT / 'sites/tongji' / file, site / file)
    path = tmp_path / 'data/professors/tongji/cs/fixture.yaml'
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({'slug': 'fixture', 'name': '测试甲', 'school': 'tongji',
                                   'dept': 'cs', 'detail_url': url}), encoding='utf-8')
    profile = '''<title>同济大学主页平台管理系统 测试甲--中文主页--首页</title>
      <div class="leftside"><p class="name">测试甲</p>
      <script>var _tsites_com_view_mode_type_=8;</script>
      <script src="/system/resource/tsites/tsitesencrypt.js"></script>
      <li>电子邮箱：<span id="_tsites_encryp_tsteacher_tsemail" _tsites_encrypt_field="_tsites_encrypt_field">1234567890abcdef</span></li>
      </div><div><h2>个人简介</h2><p>测试甲，现任同济大学计算机科学与技术学院研究员，博士生导师。</p>
      <p>主要研究方向为图表示学习。</p></div>'''.encode('utf-8')
    remote_calls = []

    def fetch(source):
        remote_calls.append(source['url'])
        if source['url'] == url:
            return profile
        response_url = urlsplit(source['url'])
        assert response_url.hostname == 'faculty.tongji.edu.cn' and response_url.path.endswith('/tsitesencrypt.jsp')
        assert parse_qs(response_url.query) == {'id': ['_tsites_encryp_tsteacher_tsemail'],
                                               'content': ['1234567890abcdef'], 'mode': ['8']}
        assert source['official_scope'] == 'https://cs.tongji.edu.cn'
        return b'{"content":"first@example.edu.cn"}'

    report = legacy_refresh.run(tmp_path, kind='professors', limit=1, workers=1, fetcher=fetch)
    assert report['ok'] == 1 and len(remote_calls) == 2
    assert len(report['results'][0]['supplemental_evidence']) == 1
    actual = yaml.safe_load(path.read_bytes())
    assert actual['email'] == 'first@example.edu.cn'
    assert actual['supervisor'] == '博导'
    assert actual['title'] == '研究员'
    assert actual['research_direction_raw'] == '图表示学习'
    assert actual['provenance']['email']['source'] == url

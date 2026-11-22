import pytest

from crawler.legacy_refresh import merge_profile
from sites.bupt import bupt_cs
from sites.xmu import xmu_cs


def test_bupt_reads_own_research_anchors_from_named_faculty_page():
    url = "https://teacher.bupt.edu.cn/chengbo"
    html = """
    <title>北京邮电大学主页平台管理系统 程渤--中文主页--首页</title>
    <a href="/chengbo/zh_CN/yjgk/59219/list/index.htm">研究领域</a>
    <a href="/chengbo/zh_CN/yjfx/59217/content/2815.htm#yjfx">[1] 自然语言处理</a>
    <a href="/chengbo/zh_CN/yjfx/59217/content/2106.htm#yjfx">计算机视觉</a>
    <a href="/another/zh_CN/yjfx/59217/content/2106.htm#yjfx">他人方向</a>
    <a href="https://example.com/chengbo/zh_CN/yjfx/59217/content/2110.htm">站外内容</a>
    <a href="/chengbo/zh_CN/yjfx/59217/content/2107.htm#yjfx">暂无内容</a>
    """
    assert bupt_cs.parse_detail({"_expected_name": "程渤"}, html, url)["research_direction_raw"] == "自然语言处理；计算机视觉"


def test_bupt_explicit_bio_is_bounded_to_research_sentence():
    url = "https://teacher.bupt.edu.cn/shichuan"
    html = """
    <title>北京邮电大学主页平台管理系统 石川--中文主页--首页</title>
    <div class="teacher_mid_midRlanmT fl">个人简介</div>
    <div class="teacher_mid_midRlanmB fl">
      <p><span>主要研究方向</span><strong>：</strong>数据挖掘、图学习。主持国家科研项目。</p>
      <p>发表论文。欢迎联系。</p>
    </div>
    """
    assert bupt_cs.parse_detail({"_expected_name": "石川"}, html, url)["research_direction_raw"] == "数据挖掘、图学习"


def test_bupt_rejects_an_unstructured_direction_mixed_with_teaching_and_client_work():
    url = "https://teacher.bupt.edu.cn/example"
    html = """
    <title>北京邮电大学主页平台管理系统 陈甲--中文主页--首页</title>
    <a href="/example/zh_CN/yjfx/1/content/20.htm#yjfx">
      理论方面专注于数理逻辑的研究和教学工作。在应用方面专注于面向客户，研究技术数据分析的应用系统。
      银行方面：银行风险相关管理系统，包括反洗钱和内部控制。航运方面：包括船舶定位和搜救管理。
      贸易方面：研究多种商品贸易流。金融方面：研究套利算法和套期保值等算法和实践。
    </a>
    """
    assert "research_direction_raw" not in bupt_cs.parse_detail({"_expected_name": "陈甲"}, html, url)


def test_bupt_keeps_long_direction_link_when_it_describes_only_research():
    url = "https://teacher.bupt.edu.cn/example"
    topics = ("长期从事自然语言处理、低资源信息抽取、人机协同知识图谱与可信数据融合的科学研究。"
              "目前主要研究多语言语义表示、行业视觉文本对齐、复杂情境下的流式信息检索、可解释的领域知识建模、"
              "跨任务学习评价、隐私保护的数据治理、语音与文本的联合表示以及机器学习&amp;深度学习在文档分类中的应用")
    html = f"""
    <title>北京邮电大学主页平台管理系统 陈甲--中文主页--首页</title>
    <a href="/example/zh_CN/yjfx/1/content/20.htm#yjfx">{topics}</a>
    """
    parsed = bupt_cs.parse_detail({"_expected_name": "陈甲"}, html, url)
    assert len(topics) > 120
    assert parsed["research_direction_raw"] == topics.replace("&amp;", "&")


def test_bupt_admissions_people_with_same_name_require_matching_homepage():
    url = "https://scs.bupt.edu.cn/info/1020/2302.htm"
    html = """
    <title>计算机学院导师联系方式、研究方向-北京邮电大学 计算机学院</title>
    <div class="v_news_content"><table>
      <tr><td>招生团队</td><td>导师姓名</td><td>导师类型</td><td>联系方式</td><td>研究方向</td></tr>
      <tr><td>计算机01组</td><td><a href="https://teacher.bupt.edu.cn/liuwei1">刘伟</a></td>
        <td>硕导</td><td>first@bupt.edu.cn</td><td>软件工程</td></tr>
      <tr><td>计算机05组</td><td><a href="https://teacher.bupt.edu.cn/liuwei3">刘伟</a></td>
        <td>硕导</td><td>third@bupt.edu.cn</td><td>物联网</td></tr>
    </table></div>
    """
    cfg = {"admissions_profile_url": url, "_read_source": lambda target: (html.encode(), html)}
    person = {"name": "刘伟", "detail_url": "https://teacher.bupt.edu.cn/liuwei3/zh_CN/index.htm"}
    assert bupt_cs.parse_contact(cfg, person) == {
        "_verified_roster_name": "刘伟", "email": "third@bupt.edu.cn", "_field_sources": {"email": url},
    }
    assert not bupt_cs.parse_contact(dict(cfg, _previous_email="first@bupt.edu.cn"), person)


def test_xmu_contacts_require_unique_named_rows_and_personal_address():
    url = "https://informatics.xmu.edu.cn/list_teacher.jsp"
    html = """
    <title>计算机科学与技术系-厦门大学信息学院</title>
    <table>
      <tr><th>姓名</th><th>职称</th><th>邮箱</th></tr>
      <tr><td><a href="#">曹刘娟</a></td><td>教授</td><td>caoliujuan@xmu.edu.cn</td></tr>
      <tr><td>陈甲</td><td>教授</td><td>first@xmu.edu.cn</td></tr>
      <tr><td>陈甲</td><td>教授</td><td>second@xmu.edu.cn</td></tr>
      <tr><td>李乙</td><td>教授</td><td>admin@xmu.edu.cn</td></tr>
      <tr><td>吴丙</td><td>教授</td><td>first@xmu.edu.cn;second@xmu.edu.cn</td></tr>
    </table>
    <table><tr><th>姓名</th><th>职称</th><th>办公室</th></tr>
      <tr><td>孙丙</td><td>教授</td><td>teacher@xmu.edu.cn</td></tr>
    </table>
    """
    cfg = {"contact_roster_url": url, "_read_source": lambda target: (html.encode(), html)}
    assert xmu_cs.parse_contact(cfg, {"name": "曹刘娟"})["email"] == "caoliujuan@xmu.edu.cn"
    assert not xmu_cs.parse_contact(cfg, {"name": "陈甲"})
    assert not xmu_cs.parse_contact(cfg, {"name": "李乙"})
    assert not xmu_cs.parse_contact(cfg, {"name": "孙丙"})
    assert not xmu_cs.parse_contact(cfg, {"name": "吴丙"})


def test_xmu_teacher_cards_keep_personal_direction_and_original_link():
    url = "https://cs.xmu.edu.cn/szll/fjs.htm"
    html = """
    <title>副教授-厦门大学计算机科学与技术系</title>
    <a href="https://informatics.xmu.edu.cn/info/1425/43960.htm">
      <div class="sz-con">
        <div class="sz-name">陈龙彪</div>
        <div class="sz-info">研究方向: 群智感知、普适计算、城市计算</div>
      </div>
    </a>
    """
    assert xmu_cs.faculty_cards(html, url)["陈龙彪"] == {
        "detail_url": "https://informatics.xmu.edu.cn/info/1425/43960.htm",
        "research_direction_raw": "群智感知、普适计算、城市计算",
    }


def test_xmu_profile_distinguishes_explicit_research_from_recruitment_instructions():
    url = "https://faculty.xmu.edu.cn/SSQ1/zh_CN/index.htm"
    html = """
    <title>厦门大学平台管理系统 沈思淇--中文主页--首页</title>
    <div class="rightconside1"><h2>个人简介</h2>
      <p>请对本人研究领域有兴趣的同学通过电子邮件联系我。</p>
      <p>目前主要从事多智能体感知与计算相关领域的研究。</p>
    </div>
    """
    parsed = xmu_cs.profile_details(html, url)
    assert parsed == {"name": "沈思淇", "research_direction_raw": "多智能体感知与计算"}


def test_xmu_roster_as_current_source_uses_expected_teacher_and_no_homepage():
    url = "https://cs.xmu.edu.cn/szll/fjs.htm"
    html = """
    <title>副教授-厦门大学计算机科学与技术系</title>
    <a href="https://informatics.xmu.edu.cn/info/1425/43960.htm">
      <div class="sz-con"><div class="sz-name">陈龙彪</div><div class="sz-info">研究方向: 城市计算</div></div>
    </a>
    <a href="https://informatics.xmu.edu.cn/info/1425/43961.htm">
      <div class="sz-con"><div class="sz-name">陈甲</div><div class="sz-info">研究方向: 人机交互</div></div>
    </a>
    """
    config = {"list": {"channels": [{"url": url}]}}
    assert not xmu_cs.parse_detail(config, html, url)
    assert xmu_cs.parse_detail(dict(config, _expected_name="陈龙彪"), html, url) == {
        "name": "陈龙彪", "_verified_roster_name": "陈龙彪", "research_direction_raw": "城市计算",
    }
    registered = dict(config, _expected_name="陈龙彪", _original_profile={"research_direction_raw": "群智感知"})
    assert "research_direction_raw" not in xmu_cs.parse_detail(registered, html, url)


@pytest.mark.parametrize(("registered_title", "source", "observed_at", "protected"), [
    ("副教授（已荣休）", "https://dblab.xmu.edu.cn/post/retirement/", "2026-11-23", True),
    ("副教授(已退休)", "https://informatics.xmu.edu.cn/info/1102/16518.htm", "2026-11-23", True),
    ("讲师", "https://informatics.xmu.edu.cn/info/1102/16518.htm", "2026-11-23", False),
    ("副教授（荣休名录编辑）", "https://informatics.xmu.edu.cn/info/1102/16518.htm", "2026-11-23", False),
    ("副教授（已荣休）", "https://xmu.edu.cn.example.org/retirement", "2026-11-23", False),
    ("副教授（已荣休）", "https://dblab.xmu.edu.cn/post/retirement/", None, False),
])
def test_xmu_personal_page_preserves_officially_documented_retirement(registered_title, source, observed_at, protected):
    url = "https://informatics.xmu.edu.cn/info/1425/43960.htm"
    name = "陈甲"
    profile = {"name": name, "slug": "chenjia", "school": "xmu", "dept": "cs", "detail_url": url,
               "title": registered_title, "provenance": {"title": {"source": source}}}
    if observed_at:
        profile["provenance"]["title"]["fetched_at"] = observed_at
    html = """
    <title>陈甲-厦门大学信息学院</title>
    <div class="v_news_content">
      <p>姓名：陈甲</p><p>职称：教授</p><p>研究方向：软件工程</p>
    </div>
    """
    parsed = xmu_cs.parse_detail({"_expected_name": name, "_original_profile": profile}, html, url)
    assert parsed.get("title") == (None if protected else "教授")
    merged, _, _ = merge_profile(profile, parsed, html, "2026-11-24")
    assert merged["research_direction_raw"] == "软件工程"
    assert merged["title"] == (registered_title if protected else "教授")
    if protected:
        assert merged["provenance"]["title"] == profile["provenance"]["title"]
    assert "supervisor" not in merged

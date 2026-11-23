from copy import deepcopy

import pytest

from crawler import fetch
from crawler.mentor_recovery import IdentityConflict
from sites.ustc import ustc_cs


HOST = "http://cs.ustc.edu.cn"
ARTICLE = HOST + "/2020/0906/c23239a460124/page.htm"
OTHER = HOST + "/2020/0906/c23239a460125/page.htm"
ROSTER = HOST + "/js_23235/list.htm"
PAGE_2 = HOST + "/js_23235/list2.htm"
TOPICS = "高性能计算、并行算法"


def person_html(*lines, name="李原"):
    return f'<h1 class="arti_title">{name}</h1><div class="wp_articlecontent">' + "".join(
        f"<p>{line}</p>" for line in lines) + "</div>"


def profile(**values):
    return {"name": "李原", "email": "origin@ustc.edu.cn", "detail_url": ARTICLE, "provenance": {}, **values}


def test_personal_field_has_boundaries_and_explicit_identity():
    html = person_html("E-Mail：origin@ustc.edu.cn", f"<strong>主 要研究方向：</strong> {TOPICS}",
                       "李原，教授、博士生导师。发表论文二十余篇。", "代表性论著：", "计算机科学教育")
    out = ustc_cs.parse_detail({"_original_profile": profile()}, html, ARTICLE)
    assert out["research_direction_raw"] == TOPICS
    assert out["research_directions"] == [TOPICS]
    assert out["name"] == "李原"
    assert ustc_cs.parse_detail({"_original_profile": profile()}, html, ARTICLE.replace("cs.ustc", "foreign.ustc")) == {}
    with pytest.raises(IdentityConflict, match="姓名"):
        ustc_cs.parse_detail({"_original_profile": profile(name="王众")}, html, ARTICLE)
    with pytest.raises(IdentityConflict, match="邮箱"):
        ustc_cs.parse_detail({"_original_profile": profile(email="other@ustc.edu.cn")}, html, ARTICLE)


@pytest.mark.parametrize("lines", [
    ("E-Mail：origin@ustc.edu.cn", "科研项目：", "研究方向：分布式人工智能"),
    ("E-Mail：origin@ustc.edu.cn", "研究方向：高性能计算。曾获全国教学成果奖"),
    ("E-Mail：origin@ustc.edu.cn", "研究方向：高性能计算", "研究方向：计算机图形学"),
    ("E-Mail：origin@ustc.edu.cn", "<span hidden>研究方向：计算机图形学</span>"),
    ("E-Mail：origin@ustc.edu.cn；other@ustc.edu.cn", "研究方向：高性能计算"),
    ("E-Mail：origin@ustc.edu.cn", "E-Mail：other@ustc.edu.cn", "研究方向：高性能计算"),
    ("团队成员：", "E-Mail：origin@ustc.edu.cn", "研究方向：高性能计算"),
])
def test_ambiguous_and_nonpersonal_fields_are_held(lines):
    parsed = ustc_cs.parse_detail({"_original_profile": profile()}, person_html(*lines), ARTICLE)
    assert "research_direction_raw" not in parsed


def test_repair_requires_old_crawled_registered_source_and_explicit_field():
    old = TOPICS + "。李原，教授、博士生导师。1995年毕业。"
    html = person_html("E-Mail：origin@ustc.edu.cn", f"主要研究方向：{TOPICS}",
                       "李原，现任副教授。已经发表多篇论文。")
    base = profile(research_direction_raw=old,
                   provenance={"research_direction_raw": {"origin": "crawled", "source": ARTICLE}})
    assert ustc_cs.parse_detail({"_original_profile": base}, html, ARTICLE)["research_direction_raw"] == TOPICS
    for change in ({"origin": "manual"}, {"source": OTHER}):
        original = deepcopy(base)
        original["provenance"]["research_direction_raw"].update(change)
        assert "research_direction_raw" not in ustc_cs.parse_detail({"_original_profile": original}, html, ARTICLE)
    conflict = dict(base, research_direction_raw="视觉识别、数学建模")
    assert "research_direction_raw" not in ustc_cs.parse_detail({"_original_profile": conflict}, html, ARTICLE)
    corrected = dict(base, research_direction_raw=TOPICS)
    assert ustc_cs.parse_detail({"_original_profile": corrected}, html, ARTICLE)["research_direction_raw"] == TOPICS


def test_outcome_suffix_requires_contiguous_current_personal_biography():
    old = TOPICS + "等，研发了并行计算系统，发表了多篇论文"
    base = profile(research_direction_raw=old,
                   provenance={"research_direction_raw": {"origin": "crawled", "source": ARTICLE}})
    html = person_html("E-Mail：origin@ustc.edu.cn", f"主要研究方向：{TOPICS}",
                       f"李原，教授。其主要研究方向包括{old}。")
    assert ustc_cs.parse_detail({"_original_profile": base}, html, ARTICLE)["research_direction_raw"] == TOPICS
    assert "research_direction_raw" not in ustc_cs.parse_detail(
        {"_original_profile": base}, html.replace("研发了并行计算系统", "博士研究生参与并行计算系统"), ARTICLE)


def test_normal_roster_uses_person_cards_and_official_pagination(monkeypatch):
    requests = []

    def listing(url, name, following=""):
        body = ('<div id="wp_news_w6"><ul class="news_list"><li class="news"><span class="news_title">'
                f'<a href="{url}">{name}</a></span></li></ul></div>')
        footer = ('<div class="foot-right"><div class="share" id="wp_news_w91">'
                  '<a title="了解学院" href="/2020/0415/c19994a418234/page.htm">了解学院</a></div></div>')
        pager = f'<div id="wp_paging_w6"><a class="next" href="{following}">下一页</a></div>' if following else ''
        return body + footer + pager

    pages = {ROSTER: listing(ARTICLE, "李原", "/js_23235/list2.htm"), PAGE_2: listing(OTHER, "黄实")}

    def read(method, url):
        requests.append((method, url))
        return pages[url], {"fetched_at": "2026-11-23"}, False

    monkeypatch.setattr(fetch, "fetch_text", read)
    cfg = {"list": {"channels": [{"url": ROSTER, "cat": "教授"}]}}
    people, _ = ustc_cs.iter_roster(cfg)
    assert requests == [("GET", ROSTER), ("GET", PAGE_2)]
    assert [(row["name"], row["url"], row["roster_source"]) for row in people] == [
        ("李原", ARTICLE, ROSTER), ("黄实", OTHER, PAGE_2)]
    assert all("profile_url" not in row for row in people)
    pages[ROSTER] = listing(ARTICLE, "李原", "https://outside.edu.cn/js_23235/list2.htm")
    with pytest.raises(ValueError, match="翻页"):
        ustc_cs.iter_roster(cfg)


def test_qr_target_is_not_a_named_person_detail():
    qr = person_html('<img src="/college.png">', name="了解学院")
    with pytest.raises(ValueError, match="具名正文"):
        ustc_cs.parse_detail({"_expected_name": "了解学院"}, qr, ARTICLE)


def test_contact_reads_tls_alias_and_keeps_only_explicit_personal_homepage():
    https = ARTICLE.replace("http:", "https:")
    home = "https://faculty.ustc.edu.cn/li/"
    lab = "https://faculty.ustc.edu.cn/lab/"
    html = person_html("E-Mail：origin@ustc.edu.cn", f'个人主页：<a href="{home}">{home}</a>',
                       f'实验室网站：<a href="{lab}">团队网站</a>', f"研究方向：{TOPICS}")

    def read(url):
        assert url == https
        return html.encode(), html

    fields = ustc_cs.parse_contact({"_read_source": read}, profile())
    assert fields["homepage"] == home
    assert fields["email"] == "origin@ustc.edu.cn"
    assert fields["_field_sources"] == {"homepage": https, "email": https}
    with pytest.raises(IdentityConflict):
        ustc_cs.parse_contact({"_read_source": read}, profile(email="other@ustc.edu.cn"))
    locked = profile(provenance={"email": {"origin": "manual"}, "homepage": {"origin": "manual"}})
    assert ustc_cs.parse_contact({"_read_source": read}, locked) == {}

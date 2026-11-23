from pathlib import Path

import pytest
import yaml

from crawler.mentor_recovery import IdentityConflict
from sites.scu import scu_cs


URL = "https://faculty.scu.edu.cn/lihui/zh_CN/index.htm"
PATH = "/lihui/zh_CN"
ROOT = Path(__file__).resolve().parents[1]


def page(section, *, name="李辉", path=PATH, card=None):
    return (
        f"<title>四川大学主页平台管理系统 {name}--中文主页--首页</title>"
        f"<body><a href='{path}/index/9125/list/index.htm'>首页</a>"
        f"<h2>{card or name}</h2>{section}</body>"
    )


def links(path=PATH):
    return (
        f"<a href='{path}/yjfx/10583/content/1548.htm#yjfx'>[1]推荐系统</a>"
        f"<a href='{path}/yjfx/10583/content/1549.htm#yjfx'>[2]数据挖掘</a>"
    )


def config(**values):
    return {"_expected_name": "李辉", "_original_profile": {"name": "李辉", "detail_url": URL, **values}}


@pytest.mark.parametrize(
    "section",
    [
        '<div class="teacher_tit">研究方向</div><div class="research_det">{}</div>',
        '<div class="teacher_tit"><div class="teacher_tit_one">研究方向</div>'
        '<a href="/lihui/zh_CN/yjfx/7/list/index.htm">+更多</a></div><div class="research_det">{}</div>',
        '<li class="direction"><h4>研究方向</h4><div class="sec-item">{}</div><a href="/journal">查看更多</a></li>',
        '<div class="com_tit02"><span>研究方向</span></div><div class="text lists">{}</div>',
        '<div class="home-bx"><div class="title"><h2>研究方向</h2></div><div class="ct">{}</div></div>',
        '<div><h4 class="panel-title">研究方向 <span>Research Focus</span></h4></div><div class="panel-collapse">{}</div>',
        '<ul><li class="TabbedPanelsTab">个人简介</li><li class="TabbedPanelsTab">研究方向</li></ul>'
        '<div class="TabbedPanelsContentGroup"><div class="TabbedPanelsContent">论文、项目、工作经历</div>'
        '<div class="TabbedPanelsContent">{}</div></div>',
    ],
)
def test_research_widget_selects_ordered_personal_links(section):
    observed = scu_cs.parse_detail(config(), page(section.format(links())), URL)
    assert observed["research_directions"] == ["[1]推荐系统", "[2]数据挖掘"]


@pytest.mark.parametrize(
    "wrong",
    [
        page("", path="/lihuixiao/zh_CN"),
        page("", name="郭兵"),
        page("") + '<a href="/lihuixiao/zh_CN/index.htm">首页</a>',
    ],
)
def test_identity_conflict_holds_even_when_two_bodies_have_the_same_name(wrong):
    with pytest.raises(IdentityConflict):
        scu_cs.parse_detail(config(), wrong, URL)


@pytest.mark.parametrize(
    "section",
    [
        '<div class="teacher_tit">研究方向</div><div class="research_det">暂无内容</div>',
        '<li class="direction"><h4>研究方向</h4><div class="sec-item"></div><a href="/journal">查看更多</a></li>',
        f'<nav><a href="/lihui/zh_CN/yjgk/9126/list/index.htm">研究领域</a></nav><p>个人简介 {links()}</p>',
        f'<li class="direction"><h4>研究方向</h4><div class="sec-item">{links("/lihuixiao/zh_CN")}</div></li>',
        '<div class="home-bx"><div class="title"><h2>研究方向</h2></div><h2>个人简介</h2>'
        f'<div class="ct">{links()}</div></div>',
        f'<div class="teacher_tit">研究方向</div><div class="research_det">{links()}</div>'
        '<li class="direction"><h4>研究方向</h4><div class="sec-item">其他团队</div></li>',
        '<ul><li class="TabbedPanelsTab">个人简介</li><li class="TabbedPanelsTab">研究方向</li></ul>'
        f'<div class="TabbedPanelsContentGroup"><div class="TabbedPanelsContent">{links()}</div></div>',
    ],
)
def test_research_rejects_empty_ambiguous_foreign_or_other_sections(section):
    assert "research_directions" not in scu_cs.parse_detail(config(), page(section), URL)


def test_existing_direction_preserved_and_same_value_recheck():
    html = page(f'<li class="direction"><h4>研究方向</h4><div class="sec-item">{links()}</div></li>')
    for previous in (
        config(research_direction_raw="人工保留方向", provenance={"research_direction_raw": {"origin": "manual"}}),
        config(research_direction_raw=None, provenance={"research_direction_raw": {"origin": "manual"}}),
        config(research_direction_raw="既有另一官方来源方向", provenance={"research_direction_raw": {"origin": "crawled"}}),
        config(research_direction_raw="[1]推荐系统、[2]数据挖掘",
               provenance={"research_direction_raw": {"origin": "crawled", "source": URL, "confidence": "verified"}}),
    ):
        assert "research_directions" not in scu_cs.parse_detail(previous, html, URL)
    provenance = {"research_direction_raw": {"origin": "crawled", "source": URL}}
    for saved in ("[1]推荐系统、[2]数据挖掘", "[1]、推荐系统、[2]、数据挖掘"):
        same = config(research_direction_raw=saved, provenance=provenance)
        observed = scu_cs.parse_detail(same, html, URL)
        assert observed["research_direction_raw"] == saved
        assert observed["research_directions"] == [saved]
    combined = "[1]、推荐系统、检索、[2]、数据挖掘"
    same = config(research_direction_raw=combined, provenance=provenance)
    observed = scu_cs.parse_detail(same, html.replace("推荐系统</a>", "推荐系统、检索</a>"), URL)
    assert observed["research_direction_raw"] == combined


def test_old_parser_can_verify_same_title_without_fetching_encrypted_slots(monkeypatch):
    official = {
        "title": {"origin": "crawled", "source": URL},
        "supervisor": {"origin": "manual", "source": URL},
    }
    html = page(
        '<div class="bs"><p>职务：讲师</p><p>所在单位：计算机学院</p></div>'
        '<script>var _tsites_com_view_mode_type_=8;</script>'
        '<p>电子邮箱：<span _tsites_encrypt_field="_tsites_encrypt_field" id="_tsites_encryp_tsteacher_tsemail">abcdef</span></p>'
        '<footer><a href="mailto:someone@scu.edu.cn">其他联系人</a> 硕士生导师</footer>'
    )
    requests = []

    def unexpected(*args, **kwargs):
        requests.append(args)
        raise AssertionError("unbudgeted fetch")

    monkeypatch.setattr(scu_cs.fetch, "fetch_text", unexpected)
    observed = scu_cs.parse_detail(config(title="讲师", supervisor="硕导", provenance=official), html, URL)
    assert observed == {"name": "李辉", "title": "讲师"}
    assert requests == []


def test_same_name_roster_rows_keep_exact_paths_and_only_report_identity(monkeypatch):
    cfg = yaml.safe_load((ROOT / "sites/scu/cs.yaml").read_bytes())
    cfg["list"]["pages"] = 2
    first, second = (cfg["list"]["page_url_template"].format(n=number) for number in range(1, 3))
    pages = {
        first: '<div>共2条 1/2</div><script>widget.addimg("/photo.jpg","/lihui/zh_CN/index.htm","李辉","1525");</script>',
        second: '<div>共2条 2/2</div><script>widget.addimg("/photo.jpg","/lihuixiao/zh_CN/index.htm","李辉","1524");</script>',
    }
    monkeypatch.setattr(scu_cs.fetch, "fetch_text", lambda method, url: (pages[url], {"fetched_at": "2026-11-23"}, False))
    rows, _ = scu_cs.iter_roster(cfg)
    assert len(rows) == 2
    assert [row["url"] for row in rows] == [URL, URL.replace("/lihui/", "/lihuixiao/")]
    assert [row["roster_source"] for row in rows] == [first, second]
    assert all(not (row.keys() & {"profile_url", "email", "photo_url", "homepage", "research_direction_raw"}) for row in rows)
    pages[second] = pages[second].replace('"1524"', '"1525"')
    with pytest.raises(ValueError, match="重复 UID"):
        scu_cs.iter_roster(cfg)
    pages[second] = pages[first]
    with pytest.raises(ValueError, match="页码"):
        scu_cs.iter_roster(cfg)

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from crawler import legacy_refresh, mentor_fields, mentor_quality
from sites.ucas import ucas_ict


URL = "https://www.ict.ac.cn/sourcedb/cn/jssrck/202412/t20241206_7452148.html"
CONTACT = "https://acs.ict.ac.cn/teacher/"
NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
CFG = {"school": "ucas", "dept": "ict", "hook": "ucas_ict", "base_url": "https://www.ict.ac.cn",
       "contact_hook_only": True, "parser_dependencies": ["profile_fields.py"]}
PERSON = {"name": "张甲", "slug": "zhangjia", "school": "ucas", "dept": "ict", "detail_url": URL}
PROVENANCE = {"source": URL, "origin": "crawled", "confidence": "auto", "fetched_at": "2026-10-25"}


def profile(*, name="张甲", topic="<p>数据存储系统；计算机系统结构</p>", category="博导计算机系统结构",
            bio="<p>张甲。研究方向为流计算；智能检索。曾参与研究课题。</p>",
            email="zhangjia@ict.ac.cn", homepage="", binding=True):
    fields = {"xm": name, "zc": "研究员", "yjfx": topic, "qtbz": category, "dzyj": email, "grwy": homepage}
    assignments = "\n".join("var " + k + "=" + json.dumps(v, ensure_ascii=False) for k, v in fields.items())
    setter = """var textContent = yjfx.replace(/<[^>]*>?/gm, '');
        $("#yj").html(textContent)""" if binding else ""
    return f"""<title>{name}--中国科学院计算技术研究所</title>
    <div class="main"><div class="swwls_ryxl"><dl><dd class="swwls_imgtextlist_dd">
      <h5><span>{name}  研究员</span></h5>
      <p class="p-people-content"><b id="yjfx">研究方向：</b><span id="yj"></span></p>
      <p class="p-people-content"><b id="qtbz">导师类别：</b><span>{category}</span></p>
      <p class="p-people-content"><b id="dzyj">联系方式：</b><span>{email}</span></p>
      <p class="p-people-content"><b id="grwy">个人网页：</b><span><a href="{homepage}">{homepage}</a></span></p>
    </dd></dl></div>
    <div class="tem01-people-content"><h3 id="jl">简 历：</h3><div>{bio}</div></div>
    <div class="tem01-people-content"><h3 id="cdkyxm">科研项目：</h3><div>研究方向为外部课题。</div></div>
    </div><script>{assignments}\n{setter}</script><footer>office@ict.ac.cn</footer>"""


def with_registered_direction(value="计算机系统结构", **provenance):
    return {**PERSON, "research_direction_raw": value,
            "provenance": {"research_direction_raw": {**PROVENANCE, **provenance}}}


def test_dedicated_bound_label_precedes_cv_or_category():
    result = ucas_ict.parse_detail({"_original_profile": PERSON}, profile(), URL)
    assert result["research_direction_raw"] == "数据存储系统；计算机系统结构"
    assert result["research_directions"] == [result["research_direction_raw"]]


@pytest.mark.parametrize("topic,binding", [("", True), ("虚构隐藏字段", False)])
def test_empty_unbound_direction_uses_only_explicit_named_cv_sentence(topic, binding):
    result = ucas_ict.parse_detail({"_original_profile": PERSON}, profile(topic=topic, binding=binding), URL)
    assert result["research_direction_raw"] == "流计算；智能检索"


@pytest.mark.parametrize("bio", [
    "<p>张甲，师从李乙，导师研究方向为人工智能。</p>",
    "<p>张甲。所在课题组研究方向为智能检索。</p>",
    "<p>张甲，主持项目研究方向为智能检索。</p>",
    "<p>张甲，研究员。李乙研究方向为数据库。</p>",
    "<p>张甲，研究员。李乙担任副研究员。研究方向为数据库。</p>",
    "<p>李乙，研究方向为机器人。</p>",
    "<p>张甲，教授算法课程。</p><p>研究方向为课题组成果。</p>",
])
def test_rejects_third_person_project_course_and_category_as_research(bio):
    result = ucas_ict.parse_detail({"_original_profile": PERSON}, profile(topic="", bio=bio), URL)
    assert "research_direction_raw" not in result


def test_corrects_only_historical_admissions_subject_from_same_source():
    before = with_registered_direction()
    result = ucas_ict.parse_detail({"_original_profile": before}, profile(), URL)
    assert result["research_direction_raw"] == "数据存储系统；计算机系统结构"
    for original in (with_registered_direction(origin="manual"),
                     with_registered_direction(source=CONTACT),
                     with_registered_direction("人工核验的数据仓库")):
        assert "research_direction_raw" not in ucas_ict.parse_detail(
            {"_original_profile": original}, profile(), URL)
    assert "research_direction_raw" not in ucas_ict.parse_detail(
        {"_original_profile": before}, profile(topic=""), URL)


def test_dedicated_direction_drops_labelled_group_homepage_suffix():
    html = profile(topic="计算机系统结构；数据存储；（研究组主页：https://acs.ict.ac.cn/ ）")
    assert ucas_ict.parse_detail({}, html, URL)["research_direction_raw"] == "计算机系统结构；数据存储"
    assert "homepage" not in ucas_ict.parse_detail({}, html, URL)


def test_requires_official_named_card_and_expected_identity():
    with pytest.raises(ValueError, match="姓名"):
        ucas_ict.parse_detail({"_original_profile": PERSON}, profile(name="张乙"), URL)
    assert not ucas_ict.parse_detail({}, profile(), URL.replace("www.ict.ac.cn", "example.org"))
    assert not ucas_ict.parse_detail({}, profile().replace('class="swwls_ryxl"', ''), URL)


@pytest.mark.parametrize("shown", ["ictoffice@ict.ac.cn", "", "a@ict.ac.cn; b@ict.ac.cn", "联系人：a@ict.ac.cn"])
def test_rejects_public_ambiguous_or_delegated_email(shown):
    body = profile(email=shown)
    assert "email" not in ucas_ict.parse_contact({"_read_source": lambda url: (b"", body)}, PERSON)


def test_contact_hook_protects_existing_and_manual_values():
    body = profile(homepage=CONTACT)
    cfg = {"_read_source": lambda url: (b"", body)}
    row = ucas_ict.parse_contact(cfg, PERSON)
    assert row["email"] == "zhangjia@ict.ac.cn"
    assert row["homepage"] == CONTACT and row["_field_sources"] == dict(email=URL, homepage=URL)
    assert "email" not in ucas_ict.parse_contact(cfg, dict(PERSON, email="old@ict.ac.cn"))
    assert "email" not in ucas_ict.parse_contact(cfg, dict(PERSON, provenance={"email": {"origin": "manual"}}))
    assert "homepage" not in ucas_ict.parse_contact(cfg, dict(PERSON, homepage="https://elsewhere.edu.cn/"))
    assert "homepage" not in ucas_ict.parse_detail({}, body, URL)
    with_self = {"_read_source": lambda url: (b"", profile(homepage=URL))}
    assert "homepage" not in ucas_ict.parse_contact(with_self, PERSON)


def prepare(root, before):
    path = root / "data/professors/ucas/ict/zhangjia.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(before, allow_unicode=True), encoding="utf-8")
    site = root / "sites/ucas"
    site.mkdir(parents=True)
    (site / "ict.yaml").write_text(yaml.safe_dump(CFG), encoding="utf-8")
    (site / "ucas_ict.py").write_bytes(Path(ucas_ict.__file__).read_bytes())
    return path


@pytest.mark.parametrize("entry", ["legacy", "quality", "field"])
def test_normal_entrypoints_keep_writes_bound_to_evidence(tmp_path, entry):
    original = PERSON if entry == "field" else with_registered_direction()
    path = prepare(tmp_path, original)
    raw = profile(homepage=CONTACT).encode()

    def fetch(source):
        if source["url"] == URL:
            return raw
        assert source["url"] == CONTACT
        return "<title>张甲</title><h1>张甲</h1>".encode()

    if entry == "legacy":
        assert legacy_refresh.run(tmp_path, kind="professors", fetcher=fetch, now=NOW)["ok"] == 1
    elif entry == "quality":
        issues = tmp_path / "data/issues"
        issues.mkdir()
        (issues / "ucas-ict.yaml").write_text(yaml.safe_dump([dict(
            kind="fetch_or_parse_error", ref="zhangjia", message="旧字段审核", resolved=False,
            first_seen="2026-11-22")]), encoding="utf-8")
        assert mentor_quality.run(tmp_path, units=("ucas/ict",), fetcher=fetch, now=NOW)["resolved"] == 1
    else:
        report = mentor_fields.run(tmp_path, units=("ucas/ict",), fetcher=fetch, now=NOW)
        assert report["results"][0]["field_evidence"]["homepage"]["target_evidence"]["url"] == CONTACT

    current = yaml.safe_load(path.read_bytes())
    assert current["research_direction_raw"] == "数据存储系统；计算机系统结构"
    assert current["provenance"]["research_direction_raw"]["source"] == URL
    if entry == "field":
        assert current["email"] == "zhangjia@ict.ac.cn"
        assert current["homepage"] == CONTACT
    else:
        assert "email" not in current and "homepage" not in current

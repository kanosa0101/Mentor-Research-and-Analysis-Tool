from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from crawler import legacy_refresh, mentor_fields, mentor_quality
from crawler.mentor_recovery import IdentityConflict
from sites.uestc import uestc_cs


DIR = "https://yjsjy.uestc.edu.cn/gmis/jcsjgl/dsfc/index/"
DETAIL = "https://yjsjy.uestc.edu.cn/gmis/jcsjgl/dsfc/dsgrjj/20243?yxsh=08"
OLD = "https://www.scse.uestc.edu.cn/info/1081/11400.htm"
COLLEGE = "计算机科学与工程学院（网络空间安全学院）"
MAIL = "zhangjia@uestc.edu.cn"
PERSON = dict(name="张甲", school="uestc", dept="cs", slug="zhangjia", detail_url=OLD, profile_url=OLD,
              email=MAIL, title="教授")
CFG = {"school": "uestc", "dept": "cs", "hook": "uestc_cs", "base_url": DIR, "contact_hook_only": True,
       "list": {"urls": [DIR]}}
NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def profile(*, name="张甲", college=COLLEGE, code="20243", mailbox=MAIL,
            intro="张甲，教授、博士研究生导师。主要研究方向为分布式数据库、算法博弈论，已发表多篇论文。",
            experience="", subject="计算机技术（博士学位）"):
    user, sep, domain = mailbox.partition("@")
    return f'''<title>导师个人信息 - 电子科大研招网</title>
    <h4 id="Labelxymc">{college}</h4><table>
    <tr><td>导师代码：</td><td><span id="Labeldsdm">{code}</span></td></tr>
    <tr><td>导师姓名：</td><td><span id="Labeldsxm">{name}</span></td></tr>
    <tr><td>职称：</td><td><span id="Labelzc">教授</span></td></tr>
    <tr><td>电子邮件：</td><td><span id="Labelemail">{user}</span><span>{sep}</span><span>{domain}</span></td></tr>
    <tr><td>个人简介：</td><td><span id="Labelgrjj">{intro}</span></td></tr>
    <tr><td>学术经历：</td><td><span id="Labelxsjl">{experience}</span></td></tr>
    <tr><td>专业研究方向：</td><td>{subject}</td></tr>
    </table>'''


def roster(*entries, college=COLLEGE):
    links = "".join(
        f'<tr><td><a href="/gmis/jcsjgl/dsfc/dsgrjj/{code}?yxsh={dept}"><span>{code}</span><div>{name}</div></a></td></tr>'
        for code, name, dept in entries
    )
    return f'<table><tr><td class="yx_class" id="08">08 {college}</td></tr>{links}</table>'


CURRENT = roster(("20243", "张甲", "08"), ("10123", "张甲", "09"))


def graduate_parse(body, person=PERSON, directory=CURRENT):
    return uestc_cs.parse_detail({
        "_original_profile": person, "_read_source": lambda url: (b"", directory) if url == DIR else pytest.fail(url)
    }, body, DETAIL)


def test_migration_requires_current_08_roster_name_code_email_and_college():
    row = graduate_parse(profile())
    assert {k: row[k] for k in ("name", "email", "research_direction_raw", "supervisor")} == {
        "name": "张甲", "email": MAIL, "research_direction_raw": "分布式数据库、算法博弈论", "supervisor": "博导"}
    assert "homepage" not in row
    for body in (profile(name="陈乙"), profile(code="23333"), profile(college="信息与软件工程学院"),
                 profile(mailbox="other@uestc.edu.cn")):
        with pytest.raises(IdentityConflict):
            graduate_parse(body)
    with pytest.raises(ValueError, match="缺少唯一姓名"):
        graduate_parse(profile().replace('id="Labeldsxm"', 'id="unknown"'))
    with pytest.raises(ValueError, match="独立身份"):
        graduate_parse(profile(), dict(PERSON, email=None))
    with pytest.raises(ValueError, match="唯一实名"):
        graduate_parse(profile(), directory=roster(("20243", "张甲", "08"), ("21233", "张甲", "08")))
    with pytest.raises(ValueError, match="计算机学院08"):
        graduate_parse(profile(), directory=roster(("20243", "张甲", "08"), college="其他学院"))
    assert uestc_cs.parse_detail({}, profile(), DETAIL.replace("yxsh=08", "yxsh=09")) == {}


def test_research_admissions_directory_does_not_enter_full_roster_writer(monkeypatch):
    monkeypatch.setattr(uestc_cs.fetch, "fetch_text", lambda *args: pytest.fail("unexpected roster request"))
    with pytest.raises(ValueError, match="不能作为完整院系师资名单"):
        uestc_cs.iter_roster(CFG)


@pytest.mark.parametrize("identity", ["", "<p>姓名：陈乙</p>"])
def test_old_200_body_with_unbound_name_never_reaches_managed_writer(tmp_path, identity):
    path = prepare(tmp_path, PERSON)
    before = path.read_bytes()
    content = identity + "<p>专业技术职务：副教授</p><p>【研究方向】</p><p>错误主题</p><p>【教育背景】</p>"
    result = legacy_refresh.run(tmp_path, kind="professors", fetcher=lambda _: content.encode(), now=NOW)
    assert result["error"] == 1 and path.read_bytes() == before


@pytest.mark.parametrize("intro", [
    "张甲曾任教授。以下为合作者陈乙的个人资料。研究方向为并行计算。",
    "张甲在读时师从陈乙。主要研究方向为稀疏编码。",
    "张甲参与团队整体工作。长期从事精密测量研究。",
    "张甲：讲授编译原理课程，负责项目的实验教学。",
    "张甲。主要研究方向为招生专业计算机科学与技术。",
    "张甲。研究方向为操作系统。研究领域为形式化方法。",
])
def test_no_research_from_projects_courses_other_people_or_conflicts(intro):
    row = graduate_parse(profile(intro=intro))
    assert "research_direction_raw" not in row
    assert "supervisor" not in row


def test_no_qualification_from_program_table_or_past_promotion():
    row = graduate_parse(profile(intro="张甲，2010年晋升为博士生导师。", experience="研究领域：系统软件。"))
    assert row["research_direction_raw"] == "系统软件"
    assert "supervisor" not in row


@pytest.mark.parametrize(("intro", "direction"), [
    ("主要研究方向为云计算与系统建模，近5年已在各类学术期刊和会议上发表论文19篇。", "云计算与系统建模"),
    ("研究方向为系统安全与人工智能安全，在国际知名期刊、会议发表论文28篇。", "系统安全与人工智能安全"),
    ("研究方向：物联网体系结构与安全 张甲博士，研究员，博导。", "物联网体系结构与安全"),
    ("当前研究方向：1、数据工程。2、计算机视觉。举例说明。3、知识工程。发表论文。", "数据工程；计算机视觉；知识工程"),
])
def test_complete_directions_exclude_career_clauses(intro, direction):
    assert graduate_parse(profile(intro=intro))["research_direction_raw"] == direction


def test_protected_nonempty_fields_and_manual_empty_fields():
    known = dict(PERSON, research_direction_raw="已核人工方向", supervisor="硕导")
    assert "research_direction_raw" not in graduate_parse(profile(), known)
    assert "supervisor" not in graduate_parse(profile(), known)
    provenance = {key: {"origin": "manual"} for key in ("title", "research_direction_raw", "supervisor")}
    row = graduate_parse(profile(), dict(PERSON, provenance=provenance))
    assert not set(provenance) & row.keys()


def test_only_registered_person_page_can_supply_an_email_claim():
    read = {"_read_source": lambda url: (b"", profile()) if url == DETAIL else pytest.fail(url)}
    person = dict(PERSON, detail_url=DETAIL, profile_url=DETAIL, email=None)
    assert uestc_cs.parse_contact(read, person)["email"] == MAIL
    with pytest.raises(IdentityConflict):
        uestc_cs.parse_contact(read, dict(person, email="old@uestc.edu.cn"))
    assert uestc_cs.parse_contact(read, dict(person, provenance={"email": {"origin": "manual"}})) == {}
    assert uestc_cs.parse_contact(read, PERSON) == {}
    for mailbox in ("office@uestc.edu.cn", "", "person@uestc.edu.cn,other@uestc.edu.cn"):
        assert uestc_cs.parse_contact({"_read_source": lambda url: (b"", profile(mailbox=mailbox))}, person) == {}


def prepare(root, person):
    site = root / "sites/uestc"
    site.mkdir(parents=True)
    (site / "cs.yaml").write_bytes(yaml.safe_dump(CFG).encode())
    (site / "uestc_cs.py").write_bytes(Path(uestc_cs.__file__).read_bytes())
    target = root / "data/professors/uestc/cs/zhangjia.yaml"
    target.parent.mkdir(parents=True)
    target.write_bytes(yaml.safe_dump(person, allow_unicode=True).encode())
    return target


@pytest.mark.parametrize("another_owner", [False, True])
def test_field_queue_enforces_global_mailbox_owner_on_bound_page(tmp_path, another_owner):
    path = prepare(tmp_path, dict(PERSON, detail_url=DETAIL, profile_url=DETAIL, email=None))
    if another_owner:
        other = tmp_path / "data/professors/other/cs/chenyi.yaml"
        other.parent.mkdir(parents=True)
        other.write_bytes(yaml.safe_dump(dict(PERSON, school="other", name="陈乙", slug="chenyi"),
                                         allow_unicode=True).encode())
    def fetch(source):
        assert source["url"] == DETAIL
        return profile().encode()
    rows = mentor_fields.run(tmp_path, units=("uestc/cs",), fetcher=fetch, now=NOW)
    value = yaml.safe_load(path.read_bytes())
    assert value.get("email") == (None if another_owner else MAIL)
    assert value["research_direction_raw"] == "分布式数据库、算法博弈论"
    assert rows["attempted"] == 1


def test_legacy_updates_bound_fields_without_ordinary_email_write(tmp_path):
    row = dict(PERSON, detail_url=DETAIL, profile_url=DETAIL, email=None)
    path = prepare(tmp_path, row)
    reply = legacy_refresh.run(tmp_path, kind="professors", fetcher=lambda _: profile().encode(), now=NOW)
    current = yaml.safe_load(path.read_bytes())
    assert reply["ok"] == 1
    assert current["research_direction_raw"] == "分布式数据库、算法博弈论" and current["supervisor"] == "博导"
    assert current.get("email") is None


def test_quality_moves_existing_profile_through_named_directory_without_old_request(tmp_path):
    path = prepare(tmp_path, PERSON)
    issues = tmp_path / "data/issues"
    issues.mkdir()
    (issues / "uestc-cs.yaml").write_bytes(yaml.safe_dump([dict(
        kind="fetch_or_parse_error", ref="zhangjia", message="HTTP 202: 来源未返回可核对的导师正文", resolved=False,
        first_seen="2026-11-22", automatic_check=dict(status="error", source_urls={"profile": OLD},
          reason="HTTP 202: 来源未返回可核对的导师正文"))], allow_unicode=True).encode())
    requested = set()

    def fetch(source):
        requested.add(source["url"])
        return {DETAIL: profile().encode(), DIR: CURRENT.encode()}[source["url"]]

    result = mentor_quality.run(tmp_path, units=("uestc/cs",), fetcher=fetch, now=NOW)
    assert result["resolved"] == 1 and requested == {DETAIL, DIR}, result
    current = yaml.safe_load(path.read_bytes())
    assert current["detail_url"] == DETAIL == current["profile_url"]
    assert current["provenance"]["detail_url"]["source"] == DIR
    assert current["provenance"]["research_direction_raw"]["source"] == DETAIL
    assert current["email"] == MAIL

"""Read a school faculty card using the registered name and teacher-platform ID."""

import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString
from requests import RequestException

from crawler.mentor_recovery import DiscoveryBudgetExhausted
from sites.profile_fields import clean_research
from sites.simple_list import iter_roster


_PERSON_PATH = re.compile(r"/(\d{10})(?:\.html?)?")
_NAME = re.compile(r"([\u4e00-\u9fff·]{2,5})(?:\s*[（(]([^()（）]+)[）)])?")
_TITLE = re.compile(r"教授|副教授|助理教授|研究员|副研究员|助理研究员|讲师|高级工程师|工程师")
_DIRECTION = re.compile(r"研究方向\s*[:：]\s*(.*)")
_PAGE_NUMBER = re.compile(r"(a\d+)p")
_MAX_DEPARTMENT_PAGES = 6


def teacher_id(url):
    target = urlsplit(url)
    if (target.scheme in ("http", "https") and target.netloc == "teacher.nwpu.edu.cn"
            and not target.query and not target.fragment):
        match = _PERSON_PATH.fullmatch(target.path)
        return match.group(1) if match else None
    return None


def _faculty_department(cfg, url):
    target = urlsplit(url)
    query = parse_qs(target.query, keep_blank_values=True)
    dept_id = query.get("wbtreeid", [""])[0]
    if (target.scheme != "https" or target.netloc != "jsj.nwpu.edu.cn" or target.fragment
            or target.path != "/snew/szdwlist.jsp" or dept_id not in cfg.get("faculty_departments", {})
            or query.get("urltype") != ["tree.TreeTempUrl"]
            or any(len(values) != 1 for values in query.values())
            or any(key not in ("urltype", "wbtreeid") and
                   not (re.fullmatch(r"a\d+[tpc]", key) and values[0].isdigit())
                   for key, values in query.items())):
        raise ValueError("不是已登记的西工大计算机学院院系师资页")
    return dept_id, query


def faculty_cards(cfg, html, url):
    dept_id, _ = _faculty_department(cfg, url)
    department = cfg["faculty_departments"][dept_id]
    soup = BeautifulSoup(html, "html.parser")
    if not soup.title or soup.title.get_text(strip=True) != f"{department}-计算机学院":
        raise ValueError("西工大院系师资页标题与登记不符")
    rows = []
    for card in soup.select(".leader-box > .leader-content"):
        labels = card.select(":scope > .name")
        if len(labels) != 1 or not (label := _NAME.fullmatch(labels[0].get_text(" ", strip=True))):
            continue
        name, label_title = label.groups()
        links = card.select(":scope > p > a.more[href]")
        link = links[0]["href"].strip() if len(links) == 1 else ""
        teacher = teacher_id(link)
        body = " ".join(child.strip() if isinstance(child, NavigableString) else child.get_text(" ", strip=True)
                        for child in card.children if not isinstance(child, Comment)
                        and getattr(child, "name", None) not in ("p", "script", "style"))
        body = " ".join(body.split())
        match = _DIRECTION.fullmatch(body)
        title = label_title or body
        rows.append(dict(name=name, teacher_id=teacher, teacher_url=link,
                         title=title if _TITLE.fullmatch(title) else None,
                         research_direction_raw=clean_research(match.group(1)) if match else None))
    return rows


def _pagination(cfg, html, home, department):
    soup = BeautifulSoup(html, "html.parser")
    pages, declarations = {}, set()
    anchors = soup.select(".page-yansoft a[href]")
    for anchor in anchors:
        label = anchor.get_text(strip=True)
        if not re.fullmatch(r"[0-9]+", label):
            continue
        url = urljoin(home, anchor["href"])
        dept_id, query = _faculty_department(cfg, url)
        keys = [match[1] for key in query if (match := _PAGE_NUMBER.fullmatch(key))]
        if dept_id != department or len(keys) != 1:
            raise ValueError("西工大院系公开分页边界变化")
        key = keys[0]
        number, total, size = (query.get(key + part, [""])[0] for part in "ptc")
        if number != label or not (total.isdigit() and size.isdigit()):
            raise ValueError("西工大院系公开分页编号不一致")
        index = int(number)
        if index in pages and pages[index] != url:
            raise ValueError("西工大院系公开分页存在冲突地址")
        pages[index] = url
        declarations.add((key, int(total), int(size)))
    if anchors:
        if len(declarations) != 1:
            raise ValueError("西工大院系公开分页总数不一致")
        _, total, _ = next(iter(declarations))
        if not 2 <= total <= _MAX_DEPARTMENT_PAGES or set(pages) != set(range(2, total + 1)):
            raise ValueError("西工大院系公开分页未完整覆盖或超过读取上限")
    return pages.values()


def _relocate(cfg, url, html, reader):
    department, _ = _faculty_department(cfg, url)
    # The school's master roster links the unpaginated entry for each configured department.
    home = urlsplit(url)._replace(query=f"urltype=tree.TreeTempUrl&wbtreeid={department}").geturl()
    home_html = html if home == url else reader(home)[1]
    first = faculty_cards(cfg, home_html, home)
    rows = [(home, row) for row in first]
    for target in _pagination(cfg, home_html, home, department):
        target_html = html if target == url else reader(target)[1]
        rows.extend((target, row) for row in faculty_cards(cfg, target_html, target))
    return rows


def advisor_qualification(html, name, teacher):
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("#vsb_content")
    if (not soup.title or soup.title.get_text(strip=True) != "导师风采-计算机学院"
            or not section or "计算机学院博导硕导链接" not in "".join(section.get_text().split())):
        return None
    confirmed = set()
    for table in section.find_all("table", recursive=False):
        heading = table.find_previous_sibling()
        label = "".join(heading.get_text().split()).rstrip(":：") if heading else ""
        first_cell = table.find("td")
        if (label not in ("博导", "硕导") or not first_cell
                or "".join(first_cell.get_text().split()) != "010计算机学院"):
            continue
        for anchor in table.select("td a[href]"):
            anchor_name = anchor.get_text(strip=True)
            anchor_id = teacher_id(anchor["href"].strip())
            if anchor_name == name and anchor_id == teacher:
                confirmed.add(label)
            elif anchor_name == name or anchor_id == teacher:
                return None
    return "、".join(role for role in ("博导", "硕导") if role in confirmed) or None


def _may_refresh(cfg, original, field, source):
    proof = ((original.get("provenance") or {}).get(field) or {})
    if proof.get("origin") == "manual":
        return False
    if not original.get(field):
        return True
    old_source = proof.get("source")
    if proof.get("origin") != "crawled" or not old_source:
        return False
    if old_source == source:
        return True
    if field != "supervisor":
        try:
            return _faculty_department(cfg, old_source)[0] == _faculty_department(cfg, source)[0]
        except ValueError:
            pass
    return False


def parse_detail(cfg, html, url):
    name = cfg.get("_expected_name")
    original = cfg.get("_original_profile") or {}
    teacher = teacher_id(original.get("profile_url") or "")
    if not (name and original.get("name") == name and original.get("detail_url") == url and teacher):
        raise ValueError("缺少已登记的西工大教师身份")
    reader = cfg.get("_read_source")
    rows = [(url, row) for row in faculty_cards(cfg, html, url) if row["name"] == name or row["teacher_id"] == teacher]
    if not rows and reader:
        rows = [(source, row) for source, row in _relocate(cfg, url, html, reader)
                if row["name"] == name or row["teacher_id"] == teacher]
    if len(rows) != 1 or rows[0][1]["name"] != name or rows[0][1]["teacher_id"] != teacher:
        raise ValueError("西工大院系师资页未确认唯一的姓名和教师身份")
    card_source, card = rows[0]
    result = {"name": name, "_verified_roster_name": name}
    for field in ("title", "research_direction_raw"):
        value = card[field]
        if value and _may_refresh(cfg, original, field, card_source):
            result[field] = value
            if card_source != url:
                result.setdefault("_field_sources", {})[field] = card_source
    if direction := result.get("research_direction_raw"):
        result["research_directions"] = [direction]
    source = cfg.get("advisor_roster_url")
    if source and reader and _may_refresh(cfg, original, "supervisor", source):
        try:
            _, advisor_html = reader(source)
        except (DiscoveryBudgetExhausted, OSError, RequestException, ValueError):
            # Unavailable supplemental evidence does not invalidate the named faculty card.
            return result
        if role := advisor_qualification(advisor_html, name, teacher):
            result["supervisor"] = role
            result.setdefault("_field_sources", {})["supervisor"] = source
    return result

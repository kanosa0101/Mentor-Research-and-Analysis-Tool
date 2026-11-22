"""厦门大学计算机科学与技术系（cs.xmu.edu.cn）。
教师卡片链接混合: faculty.xmu.edu.cn tsites 主页（tsites 解析+邮箱解密）/
informatics.xmu.edu.cn 文章页（wp 解析, 部分为死链→issues 留痕）。
"""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler.mentor_recovery import personal_email
from sites import tsites
from sites.profile_fields import clean_research
from sites.wp import parse_wp_detail, walk_channels


_DEPARTMENT = "厦门大学计算机科学与技术系"
_CONTACT_TITLE = "计算机科学与技术系-厦门大学信息学院"
_NAME = r"[\u4e00-\u9fff·]{2,5}"
_TABLE_HEADERS = ["姓名", "职称", "邮箱"]
_CARD_DIRECTION = re.compile(r"(?:^|\s)(?:研究方向|研究领域|研究内容)\s*[:：]\s*(.+)$")
_FACULTY_PROFILE = re.compile(r"/[^/]+/zh_CN/(?:index\.htm)?$", re.I)
_MAILBOX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DIRECTION_LINK = re.compile(r"/([^/]+)/zh_CN/yjfx/\d+/content/\d+\.htm$", re.I)
_RESEARCH_STATEMENT = re.compile(
    r"(?:研究(?:方向|领域|兴趣)\s*(?:[:：]|为|是|包括|包含|集中在)|Research Interests?\s*[:：])"
    r"\s*([^。！？\n]{2,240})", re.I)
_RESEARCH_FOCUS = re.compile(
    r"(?:主要|长期)从事\s*([^。！？]{2,160}?)(?:\s*相关)?(?:等)?(?:方面|领域|方向)(?:的)?研究")
_AFTER_TOPICS = re.compile(r"[，,]\s*(?:先后|目前担任|欢迎|在相关(?:领域|方向))")
_PROFILE_FEATURE = re.compile(rf"厦门大学计算机系优秀青年教师系列介绍[^-—]*[-—]+({_NAME})博士-{_DEPARTMENT}$")


def iter_roster(cfg):
    return walk_channels(cfg, cfg["list"]["channels"])


def contact_roster(html, url):
    soup = BeautifulSoup(html, "html.parser")
    if not soup.title or soup.title.get_text(strip=True) != _CONTACT_TITLE:
        return {}
    rows = {}
    for table in soup.select("table"):
        header = table.find("tr")
        if header is None or [th.get_text(strip=True) for th in header.find_all("th")] != _TABLE_HEADERS:
            continue
        for row in table.select("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) != 3:
                continue
            name = cells[0].get_text(strip=True)
            if not re.fullmatch(_NAME, name):
                continue
            href = cells[0].find("a", href=True)
            target = urljoin(url, href["href"]) if href else ""
            parts = urlsplit(target)
            profile = target if (parts.scheme == "https" and parts.hostname == "faculty.xmu.edu.cn"
                                 and _FACULTY_PROFILE.fullmatch(parts.path)) else None
            email = cells[2].get_text(strip=True)
            rows.setdefault(name, []).append({
                "email": personal_email(email) if _MAILBOX.fullmatch(email) else None,
                "title": cells[1].get_text(strip=True),
                "profile_url": profile,
            })
    return {name: matches[0] for name, matches in rows.items() if len(matches) == 1}


def faculty_cards(html, url):
    """Current named cards may retain a stale personal link and an explicit direction."""
    soup = BeautifulSoup(html, "html.parser")
    if not soup.title or not soup.title.get_text(strip=True).endswith("-" + _DEPARTMENT):
        return {}
    rows = {}
    for card in soup.select(".sz-con"):
        label = card.select_one(".sz-name")
        anchor = card.find_parent("a", href=True)
        if not label or not anchor:
            continue
        name = label.get_text(strip=True)
        if not re.fullmatch(_NAME, name):
            continue
        description = card.select_one(".sz-info")
        text = description.get_text(" ", strip=True) if description else ""
        match = _CARD_DIRECTION.search(text)
        rows.setdefault(name, []).append({
            "detail_url": urljoin(url, anchor["href"]),
            "research_direction_raw": clean_research(match.group(1)) if match else None,
        })
    return {name: matches[0] for name, matches in rows.items() if len(matches) == 1}


def parse_contact(cfg, original):
    url = cfg.get("contact_roster_url")
    reader = cfg.get("_read_source")
    if not (url and reader):
        return {}
    _, html = reader(url)
    name = original["name"]
    row = contact_roster(html, url).get(name)
    if not row or not row["email"] or cfg.get("_previous_email", row["email"]).casefold() != row["email"].casefold():
        return {}
    return {"_verified_roster_name": name, "email": row["email"],
            "_field_sources": {"email": url}}


def _research_text(value):
    for match in _RESEARCH_STATEMENT.finditer(value[:4000]):
        topics = _AFTER_TOPICS.split(match.group(1), maxsplit=1)[0].strip()
        if re.search(r"@|联系我|邮箱|职称|个人简介|招生|博士生导师|硕士生导师", topics):
            continue
        if direction := clean_research(topics):
            return direction
    if match := _RESEARCH_FOCUS.search(value[:4000]):
        return clean_research(match.group(1))
    return None


def profile_details(html, url):
    """Read explicit topics and the personal page title from the campus templates."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.title.get_text(strip=True) if soup.title else ""
    parts = urlsplit(url)
    if parts.hostname == "faculty.xmu.edu.cn":
        match = re.match(rf"厦门大学平台管理系统\s+({_NAME})--", heading)
        if not match:
            return {}
        handle = parts.path.strip("/").split("/", 1)[0].casefold()
        topics = []
        for link in soup.select('a[href*="/yjfx/"]'):
            target = urlsplit(urljoin(url, link["href"]))
            direction = _DIRECTION_LINK.fullmatch(target.path)
            value = link.get_text(" ", strip=True)
            if (target.hostname == parts.hostname and direction and
                    direction.group(1).casefold() == handle and re.search(r"[\u4e00-\u9fffA-Za-z]", value) and
                    value not in ("暂无内容", "无", "暂无", "更多")):
                if value not in topics:
                    topics.append(value)
        if topics:
            return {"name": match.group(1), "research_direction_raw": "；".join(topics)}
        sections = [h2.parent for h2 in soup.select(".rightconside1 > h2")
                    if h2.get_text(strip=True) == "个人简介"]
    else:
        match = re.match(rf"({_NAME})-(?:{_DEPARTMENT}|厦门大学信息学院)$", heading)
        match = match or _PROFILE_FEATURE.fullmatch(heading)
        if not match:
            return {}
        sections = soup.select(".sz-ty, .v_news_content, #vsb_content, .wp_articlecontent")
    output = {"name": match.group(1)}
    for section in sections:
        paragraphs = [p.get_text(" ", strip=True) for p in section.select("p") if not p.find("p")]
        text = "\n".join(paragraphs) if paragraphs else section.get_text(" ", strip=True)
        if direction := _research_text(text):
            output["research_direction_raw"] = direction
            break
    return output


def parse_detail(cfg, html, url):
    expected = cfg.get("_expected_name")
    if any(channel["url"] == url for channel in cfg.get("list", {}).get("channels", ())):
        if not expected:
            return {}
        card = faculty_cards(html, url).get(expected)
        if not card or not card["research_direction_raw"]:
            raise ValueError("厦大系站名录没有唯一的具名研究方向")
        result = {"name": expected, "_verified_roster_name": expected,
                  "research_direction_raw": card["research_direction_raw"]}
        return _keep_registered_fields(cfg, result)
    verified = profile_details(html, url)
    if expected and verified.get("name") != expected:
        raise ValueError("厦大教师主页姓名与登记不一致或标题未确认")
    if urlsplit(url).hostname == "faculty.xmu.edu.cn":
        if cfg.get("_read_source"):
            # During maintenance, the current named directory supplies auditable contact evidence.
            soup = BeautifulSoup(html, "html.parser")
            for span in soup.select("span[_tsites_encrypt_field]"):
                span.decompose()
            result = tsites.parse_detail(cfg, str(soup), url)
        else:
            result = tsites.parse_detail(cfg, html, url)
    else:
        result = parse_wp_detail(cfg, html, url)
    result.pop("research_directions", None)
    result.pop("research_direction_raw", None)
    result.update(verified)
    return _keep_registered_fields(cfg, result)


def _keep_registered_fields(cfg, result):
    original = cfg.get("_original_profile") or {}
    for field in ("email", "research_direction_raw"):
        if original.get(field) and result.get(field) != original[field]:
            result.pop(field, None)
    title = original.get("title") or ""
    if title.endswith(("（已荣休）", "（已退休）", "(已荣休)", "(已退休)")):
        proof = (original.get("provenance") or {}).get("title") or {}
        # A faculty page can retain the academic title after a documented retirement.
        if proof.get("fetched_at") and re.match(r"https://(?:[a-z0-9-]+\.)*xmu\.edu\.cn/", proof.get("source") or "", re.I):
            result.pop("title", None)
    return result

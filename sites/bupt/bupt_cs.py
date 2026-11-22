from html import unescape
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
from sites.profile_fields import clean_research

# scs.bupt.edu.cn 名录页(单页 jsyl.htm)按研究中心分组, 每人链到 teacher.bupt.edu.cn
# 的 tsites 主页。全站瑞数 412 —— crawl 以 cdp_fallback: true 走真实 Chrome。
# 北邮 tsites 模板与西电/中南不同: 无 _tsites_encrypt_field 密文 span,
# 邮箱明文在 div#gerenxinxi 的标签行里。
LIST_URL = "https://scs.bupt.edu.cn/szjs1/jsyl.htm"

_NAME = re.compile(r"^[\u4e00-\u9fa5·]{2,5}$")
_EMAIL = re.compile(r"电子邮箱\s*[:：]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_LABELS = ("职务", "职称", "所在单位", "办公地点", "学历", "性别")
_PROFILE_TITLE = re.compile(r"^北京邮电大学主页平台管理系统\s+([\u4e00-\u9fa5·]{2,5})--")
_DIRECTION_LINK = re.compile(r"/([^/]+)/(?:zh_CN|en)/yjfx/\d+/content/\d+\.htm$", re.I)
_NUMBERED = re.compile(r"^\s*(?:\[\d+\]|[（(]\d+[）)]|\d+[.、])\s*")
_DIRECTION_SENTENCE = re.compile(
    r"研究(?:方向|领域|兴趣)\s*(?:主要)?\s*(?:[:：]|为|是|包括|包含|集中在)\s*([^。！？]{2,240})")
_FOCUS_SENTENCE = re.compile(
    r"(?:主要|长期)从事\s*((?:(?!从事)[^。！？；，,]){2,160}?)(?:等)?(?:方面|领域|方向)?(?:的)?研究")
_CAREER_CLAUSE = re.compile(
    r"[，,]\s*(?:先后|近年来|近年|近\s*\d+\s*年|目前(?:担任|任职)|曾|以负责人|在相关(?:领域|方向)|欢迎)")
_MIXED_DIRECTION = re.compile(r"教学工作|课程教学|讲授课程|面向客户|为客户开发")
_PLACEHOLDERS = {"暂无内容", "无", "暂无", "更多", "More", "Research Direction", "Research Interests"}
_BIO_HEADINGS = "h2, h3, .CurrencyBit, .index-title, .teacher_mid_midRlanmT, .rightside h4"
_ADMISSIONS_HEADERS = ["招生团队", "导师姓名", "导师类型", "联系方式", "研究方向"]


def _normalize_home(u):
    u = u.strip().replace("http://teacher.bupt.edu.cn", "https://teacher.bupt.edu.cn")
    if u.startswith("//"):
        u = "https:" + u
    return u


def iter_roster(cfg):
    text, meta, _ = fetch.fetch_text("GET", LIST_URL)
    soup = BeautifulSoup(text or "", "html.parser")
    people = {}
    for a in soup.select('a[href*="teacher.bupt.edu.cn"]'):
        nm = a.get_text(strip=True)
        if not _NAME.match(nm):
            continue
        href = _normalize_home(a["href"])
        # 同一人可能同时挂短链(/zhoufeng)和全链(/zhoufeng/zh_CN/index.htm)——
        # 短链 302 到全链, 保留全链形态利于缓存与别名
        cur = people.get(nm)
        if cur is None or (len(href) > len(cur["url"]) and href.startswith(cur["url"])):
            people[nm] = {"name": nm, "url": href, "profile_url": href,
                          "institutes": []}
    return list(people.values()), meta


def profile_name(soup, expected=None):
    if soup.title and (match := _PROFILE_TITLE.match(soup.title.get_text(strip=True))):
        return match.group(1)
    name = soup.select_one("#gerenxinxi h1, p.name, div.name")
    if name and _NAME.fullmatch(name.get_text(strip=True)):
        return name.get_text(strip=True)
    if expected and any(tag.get_text(strip=True) == expected for tag in soup.select(
            "h1, h2, .name strong, .PersonalText strong, .t_photo span")):
        return expected
    return None


def profile_direction(soup, url):
    person = urlsplit(url).path.strip("/").split("/", 1)[0].casefold()
    topics = []
    for link in soup.select('a[href*="/yjfx/"]'):
        target = urlsplit(urljoin(url, link["href"]))
        match = _DIRECTION_LINK.fullmatch(target.path)
        if (target.hostname != "teacher.bupt.edu.cn" or not match or
                match.group(1).casefold() != person):
            continue
        text = _NUMBERED.sub("", unescape(link.get_text(" ", strip=True))).strip(" ；;。")
        if len(text) > 120:
            if heading := re.match(r"^([^：:。]{2,60})[：:]", text):
                text = heading.group(1)
            elif _MIXED_DIRECTION.search(text):
                continue
        if re.search(r"[\u4e00-\u9fffA-Za-z]", text) and text not in _PLACEHOLDERS:
            if text not in topics:
                topics.append(text)
    if topics:
        return "；".join(topics)

    for heading in soup.select(_BIO_HEADINGS):
        if heading.get_text(strip=True) != "个人简介":
            continue
        title = heading.parent if set(heading.parent.get("class", ())) & {"title", "index-title"} else heading
        body = title.find_next_sibling()
        if not body:
            continue
        paragraphs = [p.get_text(" ", strip=True) for p in body.select("p") if not p.find("p")]
        text = "\n".join(paragraphs) if paragraphs else body.get_text(" ", strip=True)
        for sentence in text[:4000].splitlines():
            match = _DIRECTION_SENTENCE.search(sentence) or _FOCUS_SENTENCE.search(sentence)
            if match:
                phrase = _CAREER_CLAUSE.split(match.group(1), maxsplit=1)[0].strip(" “”—；;")
                if phrase and (direction := clean_research(phrase)):
                    return direction
    return None


def profile_key(url):
    parts = urlsplit(url)
    match = re.fullmatch(r"/([^/]+)(?:/(?:zh_CN|en)(?:/index\.htm)?)?/?", parts.path, re.I)
    return match.group(1).casefold() if parts.hostname == "teacher.bupt.edu.cn" and match else None


def admissions_profiles(html, url):
    """Read distinct people from the admissions office's named field table."""
    soup = BeautifulSoup(html, "html.parser")
    if not soup.title or not soup.title.get_text(strip=True).startswith("计算机学院导师联系方式、研究方向-"):
        return {}
    profiles = {}
    for table in soup.select(".v_news_content table"):
        header = table.find("tr")
        if header is None or ["".join(cell.stripped_strings) for cell in
                              header.find_all(["th", "td"], recursive=False)] != _ADMISSIONS_HEADERS:
            continue
        for row in table.select("tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) != 5:
                continue
            anchor = cells[1].find("a", href=True)
            name = "".join(cells[1].get_text().split())
            if not anchor or not _NAME.fullmatch(name):
                continue
            target = profile_key(urljoin(url, anchor["href"]))
            if not target:
                continue
            email = cells[3].get_text(" ", strip=True)
            direction = clean_research(cells[4].get_text(" ", strip=True))
            profiles.setdefault((name, target), []).append({
                "email": normalize_email(email) if _EMAIL.fullmatch("电子邮箱：" + email) else None,
                "research_direction_raw": direction,
            })
    return {key: rows[0] for key, rows in profiles.items() if len(rows) == 1}


def parse_contact(cfg, original):
    source = cfg.get("admissions_profile_url")
    reader = cfg.get("_read_source")
    if not (source and reader):
        return {}
    _, html = reader(source)
    name = original["name"]
    row = admissions_profiles(html, source).get((name, profile_key(original["detail_url"])))
    if not row or not row["email"] or cfg.get("_previous_email", row["email"]).casefold() != row["email"].casefold():
        return {}
    return {"_verified_roster_name": name, "email": row["email"], "_field_sources": {"email": source}}


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    box = soup.select_one("#gerenxinxi") or soup
    expected = cfg.get("_expected_name")
    name = profile_name(soup, expected)
    if expected and name and name != expected:
        raise ValueError("北邮教师主页姓名与登记不一致")
    if name:
        out["name"] = name
        if direction := profile_direction(soup, url):
            out["research_direction_raw"] = direction
        elif (source := cfg.get("admissions_profile_url")) and (reader := cfg.get("_read_source")):
            try:
                _, roster_html = reader(source)
            except (OSError, ValueError):
                pass
            else:
                row = admissions_profiles(roster_html, source).get((name, profile_key(url)))
                if row and row["research_direction_raw"]:
                    out["research_direction_raw"] = row["research_direction_raw"]
                    out["_field_sources"] = {"research_direction_raw": source}
    text = box.get_text("\n", strip=True)
    m = _EMAIL.search(text)
    if m:
        out["email"] = m.group(1)
    for line in text.split("\n"):
        line = line.strip()
        mm = re.match(r"(所在单位|办公地点|职务|职称)\s*[:：]\s*(.+)$", line)
        if not mm:
            continue
        label, val = mm.group(1), mm.group(2).strip()
        if label == "所在单位":
            out.setdefault("institute_from_detail", [val])
        elif label == "办公地点":
            out.setdefault("office_address", val)
        elif label in ("职务", "职称"):
            # 职务多为行政头衔("中心主任"), 只在含职称词时收录
            t = re.search(r"(讲席|特聘|长聘)?(教授|副教授|助理教授|研究员|副研究员|讲师)", val)
            if t:
                out.setdefault("title", t.group(0))
    # jsxx(基本信息)子页有 职称/导师资格 —— 主页只有职务, 子页字段更全
    m = re.search(r'href="(/[^"]+/jsxx/\d+/jsxx/jsxx\.htm)"', html)
    if m:
        sub = urljoin(url, m.group(1))
        try:
            if reader := cfg.get("_read_source"):
                _, sub_html = reader(sub)
            else:
                sub_html, _, _ = fetch.fetch_text("GET", sub)
            sub_txt = re.sub(r"<[^>]+>", "\n", sub_html)
            sub_lines = [l.strip() for l in sub_txt.split("\n") if l.strip()]
            for i, line in enumerate(sub_lines):
                if "title" not in out:
                    mm = re.match(r"职称\s*[:：]\s*(.*)$", line)
                    if mm:
                        t = re.search(r"(讲席|特聘|长聘)?(教授|副教授|助理教授|研究员|副研究员|讲师)",
                                      mm.group(1) + " " + (sub_lines[i + 1] if i + 1 < len(sub_lines) else ""))
                        if t:
                            out["title"] = t.group(0)
                            if reader:
                                out.setdefault("_field_sources", {})["title"] = sub
                if "supervisor" not in out:
                    sup = [s for s in ("博士生导师", "硕士生导师") if s in line]
                    if sup:
                        out["supervisor"] = "博导" if "博士" in sup[0] else "硕导"
                        if reader:
                            out.setdefault("_field_sources", {})["supervisor"] = sub
                if "email" not in out:
                    mm = re.match(r"电子邮箱\s*[:：]\s*(.+)$", line)
                    if mm:
                        e = normalize_email(mm.group(1))
                        if e:
                            out["email"] = e
                            if reader:
                                out.setdefault("_field_sources", {})["email"] = sub
        except Exception:
            pass
    original = cfg.get("_original_profile") or {}
    for field in ("email", "research_direction_raw"):
        if original.get(field) and out.get(field) != original[field]:
            out.pop(field, None)
            if field in out.get("_field_sources", {}):
                out["_field_sources"].pop(field)
    return out

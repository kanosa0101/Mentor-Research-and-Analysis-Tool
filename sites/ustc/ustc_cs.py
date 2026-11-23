import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.mentor_recovery import PAGE_CHROME, IdentityConflict, canonical, homepage_url, personal_email, same_scope
from sites.profile_fields import clean_research
from sites.wp import parse_wp_detail


_HOST = "cs.ustc.edu.cn"
_ARTICLE = re.compile(r"/(?:\d{4}/\d{4}/)?c\d+a\d+/page\.htm")
_NAME = re.compile(r"[\u4e00-\u9fff·]{2,8}")
_RESEARCH = re.compile(r"^(?:主\s*要)?研究(?:方向|领域|兴趣)\s*[:：]\s*(.*)$")
_EMAIL = re.compile(r"^(?:E\s*-?\s*mail|邮箱|电子邮箱|电子邮件)\s*[:：]\s*(.+)$", re.I)
_ADDRESS = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_HOME = re.compile(r"^(?:个人主页|个人网站|学术主页)\s*[:：]")
_SECTION = re.compile(r"^(?:个人简介|个人简历|教育经历|工作经历|获奖情况|科研工作|科研项目|研究项目|"
                      r"(?:主要)?讲授课程|代表性?论著|代表性?论文|论文发表|研究团队|团队成员|学生信息)\s*(?:[:：]|$)")
_HISTORY = re.compile(r"毕业|(?:获得?|取得)(?:[^。]{0,25})?(?:学士|硕士|博士)学位|任教|博士生导师|教育经历|"
                      r"曾获|曾任|现任|主要讲授课程|代表性论著|研究项目|发表(?:[^。]{0,14})?(?:论文|文章)|"
                      r"\d{4}年[\d月日起至获生]")
_BIO_ROLE = re.compile(r"(?:男|女|博士|教授|副教授|讲师|博导|中国科学院院士|中国科学技术大学|现任|"
                       r"\d{4}年|IEEE(?:/AAIA)? Fellow)")


def _official_article(url):
    target = urlsplit(url)
    return (target.scheme in ("http", "https") and target.netloc == _HOST and not target.query
            and not target.fragment and _ARTICLE.fullmatch(target.path))


def _text(node):
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def _name(node):
    return "".join(_text(node).split())


def _faculty_cards(html, url):
    soup = BeautifulSoup(html, "html.parser")
    lists = soup.select("#wp_news_w6 > ul.news_list")
    if len(lists) != 1:
        raise ValueError("中科大计算机学院名单缺少唯一正文师资列表")
    records = []
    for link in lists[0].select("li.news .news_title > a[href]"):
        target = urljoin(url, link["href"])
        name = _name(link)
        if _official_article(target) and _NAME.fullmatch(name):
            records.append({"name": name, "url": target})
    if not records:
        raise ValueError("中科大计算机学院正文未解析出具名师资卡片")
    jumps = soup.select("#wp_paging_w6 a.next[href]")
    next_page = urljoin(url, jumps[0]["href"]) if len(jumps) == 1 and not jumps[0]["href"].startswith("javascript:") else None
    return records, next_page


def iter_roster(cfg):
    people, ambiguous, meta = {}, set(), None
    for channel in cfg["list"]["channels"]:
        page = channel["url"]
        folder = urlsplit(page).path.rsplit("/", 1)[0]
        visited = set()
        while page:
            target = urlsplit(page)
            if (target.netloc != _HOST or target.scheme not in ("http", "https") or target.query or target.fragment
                    or not re.fullmatch(re.escape(folder) + r"/list\d*\.htm", target.path)
                    or page in visited or len(visited) >= 40):
                raise ValueError("中科大计算机学院名册翻页超出本站原栏目")
            visited.add(page)
            html, meta, _ = fetch.fetch_text("GET", page)
            source = page
            records, page = _faculty_cards(html, source)
            for row in records:
                current = people.setdefault(row["name"], dict(row, title=channel["cat"],
                                                             roster_source=source,
                                                             roster_fetched_at=meta["fetched_at"]))
                if canonical(current["url"]) != canonical(row["url"]):
                    ambiguous.add(row["name"])
    return [row for name, row in people.items() if name not in ambiguous], meta


def _person(html, url, expected):
    if not _official_article(url):
        return None
    soup = BeautifulSoup(html, "html.parser")
    heads = soup.select("h1.arti_title")
    contents = soup.select(".wp_articlecontent")
    if len(heads) != 1 or len(contents) != 1:
        return None
    name = _name(heads[0])
    for node in contents[0].select(PAGE_CHROME):
        node.decompose()
    paragraphs = contents[0].select("p")
    lines = [_text(p) for p in paragraphs]
    if not _NAME.fullmatch(name) or not any(lines):
        return None
    if expected and "".join(expected.split()) != name:
        raise IdentityConflict("中科大本人文章明确姓名与原档不符")
    header_end = next((index for index, line in enumerate(lines)
                       if _SECTION.match(line) or _RESEARCH.fullmatch(line) or _signed_bio(line, name)), len(lines))
    addresses = [match[1] for line in lines[:header_end] if (match := _EMAIL.fullmatch(line))]
    email = personal_email(addresses[0]) if len(addresses) == 1 and _ADDRESS.fullmatch(addresses[0]) else None
    return name, paragraphs[:header_end], lines, email


def _signed_bio(line, name):
    match = re.match(re.escape(name) + r"\s*[：:，,、]\s*(.*)", line)
    return bool(match and _BIO_ROLE.match(match[1]))


def _bound_direction(lines, name):
    end = next((index for index, line in enumerate(lines) if _SECTION.match(line) or _signed_bio(line, name)), len(lines))
    matches = [(index, match[1]) for index, line in enumerate(lines[:end]) if (match := _RESEARCH.fullmatch(line))]
    if len(matches) != 1:
        return None, ""
    index, value = matches[0]
    if len(value) > 500 or _HISTORY.search(value) or re.search(r"https?://|\S+@\S+", value):
        return None, ""
    return clean_research(value), next((line for line in lines[index + 1:] if line), "")


def _repairable(original, url, direction, following):
    field = "research_direction_raw"
    old = original.get(field)
    proof = (original.get("provenance") or {}).get(field) or {}
    if not direction or proof.get("origin") == "manual":
        return False
    if not old or old == direction:
        return True
    if proof.get("origin") != "crawled" or canonical(proof.get("source", "")) != canonical(url):
        return False
    separators = r"[\s。；;、，,]"
    topic = re.sub(separators, "", direction)
    prefix = re.match(separators + "*" + (separators + "*").join(map(re.escape, topic)), old)
    if not prefix:
        return False
    trailing = old[prefix.end():].lstrip(" 。；;、，,\n")
    name = "".join(original.get("name", "").split())
    if _signed_bio(trailing, name) and _signed_bio(following, name):
        return True
    if (_signed_bio(following, name) and re.match(r"(?:等)?\s*[，,]\s*(?:研发|研制|发表)", trailing)
            and "".join(old.split()) in "".join(following.split())):
        return True
    return bool(len(trailing) >= 12 and _HISTORY.search(following[:150])
                and re.sub(r"\s", "", following).startswith(re.sub(r"\s", "", trailing)[:20]))


def parse_detail(cfg, html, url):
    original = cfg.get("_original_profile") or {}
    person = _person(html, url, cfg.get("_expected_name") or original.get("name"))
    if not person:
        if _official_article(url):
            raise ValueError("未解析中科大计算机学院本人文章的具名正文")
        return {}
    name, _, lines, email = person
    old_email = personal_email(original.get("email"))
    if old_email and email and old_email.casefold() != email.casefold():
        raise IdentityConflict("中科大本人文章邮箱与原档不符，保留现有记录")
    if not email:
        return {}
    parsed = parse_wp_detail(cfg, html, url)
    out = {"name": original.get("name") or name, "email": old_email or email}
    for field in ("title", "bio_raw", "supervisor", "phone", "photo_url"):
        # An existing value may be rechecked. This adapter does not add or
        # replace unrelated profile fields from a generic biography parser.
        if original.get(field) and original[field] == parsed.get(field):
            out[field] = parsed[field]
    direction, following = _bound_direction(lines, name)
    if _repairable(original, url, direction, following):
        out["research_direction_raw"] = direction
        out["research_directions"] = [direction]
    return out


def parse_contact(cfg, person):
    reader = cfg.get("_read_source")
    url = person["detail_url"]
    if not reader or not _official_article(url):
        return {}
    source_url = canonical(url)
    _, html = reader(source_url)
    subject = _person(html, source_url, person["name"])
    if not subject:
        return {}
    _, paragraphs, _, email = subject
    previous = cfg.get("_previous_email") or person.get("email")
    if not email or previous and previous.casefold() != email.casefold():
        if email and previous:
            raise IdentityConflict("中科大本人文章邮箱与原档不符，保留现有记录")
        return {}
    origin = person.get("provenance") or {}
    result = {}
    if (origin.get("email") or {}).get("origin") != "manual":
        result["email"] = previous or email
    if not person.get("homepage") and (origin.get("homepage") or {}).get("origin") != "manual":
        links = {target for p in paragraphs if _HOME.match(_text(p)) for anchor in p.select("a[href]")
                 if (target := homepage_url(urljoin(url, anchor["href"]))) and same_scope(target, url)
                 and canonical(target) != canonical(url)}
        if len(links) == 1:
            result["homepage"] = next(iter(links))
    return {**result, "_verified_roster_name": person["name"], "_field_sources": dict.fromkeys(result, source_url)} if result else {}

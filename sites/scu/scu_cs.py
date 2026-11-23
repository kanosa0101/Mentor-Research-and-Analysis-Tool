"""四川大学计算机学院教师名录和本人页。"""

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch, mentor_recovery
from sites import tsites
from sites.profile_fields import clean_research


_BASE = "https://faculty.scu.edu.cn"
_PATH = re.compile(r"(/[A-Za-z0-9_-]+/zh_CN)/index\.htm")
_ADDIMG = re.compile(
    r'addimg\(\s*"[^"]*"\s*,\s*"([^"]*/zh_CN/index\.htm)"\s*,\s*"([^"]+)"\s*,\s*"(\d+)"\s*\)'
)
_PAGER = re.compile(r"共\s*(\d+)\s*条\s*(\d+)\s*/\s*(\d+)")
_TITLE = re.compile(r"四川大学主页平台管理系统\s+([^\s]+)--中文主页--首页")
_CARD = "h1, h2, h3, h4, .t_name, .t_name_tit, div.name"
_HEADING = re.compile(r"研究方向(?:\s+Research Focus)?", re.I)
_LAYOUTS = (
    (".teacher_tit", False, "research_det"),
    ("li.direction > h4", False, "sec-item"),
    (".com_tit02", False, "lists"),
    (".home-bx .title h2", True, "ct"),
    ("h4.panel-title", True, "panel-collapse"),
)


def _text(node):
    return node.get_text(" ", strip=True)


def _person_path(url):
    parts = urlsplit(url)
    match = _PATH.fullmatch(parts.path)
    if parts.scheme == "https" and parts.netloc == "faculty.scu.edu.cn" and not (parts.query or parts.fragment) and match:
        return match[1]
    return None


def iter_roster(cfg):
    people = []
    used_paths, used_uids = set(), set()
    template = cfg["list"]["page_url_template"]
    pages = int(cfg["list"]["pages"])
    total = None
    for page in range(1, pages + 1):
        url = template.format(n=page)
        html, meta, _ = fetch.fetch_text("GET", url)
        counts = _PAGER.findall(_text(BeautifulSoup(html, "html.parser")))
        if len(counts) != 1 or tuple(map(int, counts[0][1:])) != (page, pages):
            raise ValueError("川大教师名录页码或总页数与登记不一致")
        count = int(counts[0][0])
        if total is not None and total != count:
            raise ValueError("川大教师名录总数在分页间变化")
        total = count
        for href, name, uid in _ADDIMG.findall(html):
            url_detail = urljoin(_BASE, href)
            if not _person_path(url_detail) or url_detail in used_paths or uid in used_uids:
                raise ValueError("川大教师名录出现重复 UID、重复路径或非登记平台路径")
            people.append({"name": name.strip(), "url": url_detail,
                           "roster_source": url, "roster_fetched_at": meta["fetched_at"]})
            used_paths.add(url_detail)
            used_uids.add(uid)
    if len(people) != total:
        raise ValueError("川大教师名录实际人数与标称总数不一致")
    return people, meta


def _person_page(cfg, html, url):
    prefix = _person_path(url)
    original = cfg.get("_original_profile") or {}
    if not prefix or original.get("detail_url", url) != url:
        raise mentor_recovery.IdentityConflict("川大本人页与精确登记路径不符")
    soup = BeautifulSoup(html, "html.parser")
    title = _TITLE.fullmatch(_text(soup.title)) if soup.title else None
    if not title:
        raise ValueError("未找到川大教师平台本人标题")
    name = title[1]
    expected = cfg.get("_expected_name") or original.get("name")
    if expected and name != expected:
        raise mentor_recovery.IdentityConflict("川大本人标题与登记姓名不符")
    card = re.compile(re.escape(name) + r"(?:\s+(?:正高|副高|中级|初级|其他))?")
    if not any(card.fullmatch(_text(node)) for node in soup.select(_CARD)):
        raise ValueError("未找到与川大教师平台标题一致的本人名片")
    home_paths = set()
    for link in soup.select("a[href]"):
        if _text(link) != "首页":
            continue
        parts = urlsplit(urljoin(url, link["href"]))
        path = re.fullmatch(r"(/[A-Za-z0-9_-]+/zh_CN)/(?:index\.htm|index/\d+/list/index\.htm)", parts.path)
        if parts.scheme == "https" and parts.netloc == "faculty.scu.edu.cn" and not (parts.query or parts.fragment) and path:
            home_paths.add(path[1])
    if home_paths and home_paths != {prefix}:
        raise mentor_recovery.IdentityConflict("川大本人页首页链接与登记路径不符")
    if not home_paths:
        raise ValueError("未找到川大本人页同路径首页链接")
    return name, prefix, soup


def _research_sections(soup):
    for selector, parent, next_class in _LAYOUTS:
        for node in soup.select(selector):
            heading = node.select_one(":scope > .teacher_tit_one") if selector == ".teacher_tit" else None
            if _HEADING.fullmatch(_text(heading or node)):
                following = (node.parent if parent else node).find_next_sibling()
                yield following if following and next_class in following.get("class", ()) else None
    for node in soup.select(".TabbedPanelsTab"):
        if not _HEADING.fullmatch(_text(node)):
            continue
        tabs = node.parent.select(":scope > .TabbedPanelsTab")
        group = node.parent.find_next_sibling()
        panels = group.select(":scope > .TabbedPanelsContent") if group and "TabbedPanelsContentGroup" in group.get("class", ()) else []
        yield panels[tabs.index(node)] if len(panels) == len(tabs) else None


def research_evidence(soup, url, prefix):
    """A single named research widget and its ordered, same-person entries."""
    sections = list(_research_sections(soup))
    if len(sections) != 1 or sections[0] is None:
        return []
    entries = []
    for anchor in sections[0].select("a[href]"):
        target = urlsplit(urljoin(url, anchor["href"]))
        term = _text(anchor)
        if (target.scheme != "https" or target.netloc != "faculty.scu.edu.cn" or target.query
                or not re.fullmatch(re.escape(prefix) + r"/yjfx/\d+/content/\d+\.htm", target.path)
                or target.fragment not in ("", "yjfx") or not term):
            return []
        entries.append({"text": term, "url": target.geturl()})
    return entries


def _same_ordered_terms(old, terms):
    """Recognize the old splitter's standalone square-bracket ordinals."""
    numbered = "、".join(
        f"[{i}]、{term.removeprefix(f'[{i}]').lstrip()}" for i, term in enumerate(terms, 1)
    )
    return old == numbered


def parse_detail(cfg, html, url):
    name, prefix, soup = _person_page(cfg, html, url)
    original = cfg.get("_original_profile") or {}
    provenance = original.get("provenance") or {}
    result = {"name": name}
    entries = research_evidence(soup, url, prefix)
    previous = provenance.get("research_direction_raw") or {}
    if entries and previous.get("origin") != "manual" and previous.get("confidence") != "verified":
        terms = [entry["text"] for entry in entries]
        old = original.get("research_direction_raw")
        value = "、".join(terms)
        if not old and clean_research(value) == value:
            result.update(research_direction_raw=value, research_directions=terms)
        elif (previous.get("origin") == "crawled" and previous.get("source") == url
              and old and clean_research(old) == old and (old == value or _same_ordered_terms(old, terms))):
            result.update(research_direction_raw=old, research_directions=[old])
    # Preserve same-source, unchanged metadata rechecks. Remove the encryption
    # slots before invoking the shared parser so no ancillary request is issued.
    if original:
        for slot in soup.select("span[_tsites_encrypt_field]"):
            slot.decompose()
        legacy = tsites.parse_detail(cfg, str(soup), url)
        for field in ("title", "supervisor", "subjects", "bio_raw", "phone", "office_address"):
            prov = provenance.get(field) or {}
            if (original.get(field) and original[field] == legacy.get(field)
                    and prov.get("origin") == "crawled" and prov.get("confidence") != "verified"
                    and prov.get("source") == url):
                result[field] = original[field]
    return result

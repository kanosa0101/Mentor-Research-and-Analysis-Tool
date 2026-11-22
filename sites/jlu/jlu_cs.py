"""吉林大学计算机学院（ccst.jlu.edu.cn）。
存量维护采用本人页或现行具名名录的明示字段，已核邮箱图片按原件摘要复验。
"""
from hashlib import sha256
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.mentor_recovery import DiscoveryBudgetExhausted, personal_email
from crawler.source_discovery import jlu_contact_png
from sites.profile_fields import clean_research
from sites.simple_list import parse_detail as _simple_parse, iter_roster as _simple_roster

_EMAIL_OK = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_COLLEGE = "吉林大学计算机科学与技术学院"
_PERSON = re.compile(r"https://ccst\.jlu\.edu\.cn/info/\d+/\d+\.htm")
_ROSTER = "https://ccst.jlu.edu.cn/szdw/zpzpjs.htm"
_ROSTER_PAGE = re.compile(r"https://ccst\.jlu\.edu\.cn/szdw/zpzpjs/\d+\.htm")
_DIRECTION = re.compile(r"(?:所|主要|目前的?|当前的?)?(?:研究(?:方向|领域|兴趣)|科研方向)")
_ADDRESS = re.compile(r"(?:电子邮箱|电子邮件|邮\s*箱|E-?mail)", re.I)
_FIELDS = ("email", "research_direction_raw")


def iter_roster(cfg):
    return _simple_roster(cfg)


def _public_address(value):
    if value.count("[at]") == 1:
        value = value.replace("[at]", "@")
    if not _EMAIL_OK.fullmatch(value) and value.count("AT") == 1:
        local, domain = value.split("AT")
        if re.fullmatch(r"[A-Za-z0-9-]+(?:DOT[A-Za-z0-9-]+)+", domain):
            value = local + "@" + domain.replace("DOT", ".")
    return personal_email(value) if _EMAIL_OK.fullmatch(value) else None


def _contact_rows(scope, url):
    addresses, misdirected, images = set(), set(), set()
    for node in scope.select("td, th, p, li"):
        parts = re.split(r"[:：]", node.get_text(" ", strip=True), maxsplit=1)
        if len(parts) != 2 or not _ADDRESS.fullmatch(parts[0].strip()):
            continue
        cell, text = node, parts[1].strip()
        sibling = node.find_next_sibling()
        if not text and sibling and node.name in ("td", "th") and sibling.name == "td":
            cell, text = sibling, sibling.get_text(" ", strip=True)
        if text:
            visible = [_public_address(token.strip()) for token in re.split(r"[;；,，、]", text)]
            if not all(visible):
                continue
            addresses.update(visible)
            for anchor in cell.select('a[href^="mailto:"]'):
                label = _public_address(anchor.get_text(" ", strip=True))
                target = _public_address(anchor["href"].removeprefix("mailto:"))
                if label in visible and target and target.casefold() != label.casefold():
                    misdirected.add(anchor["href"])
        else:
            for image in cell.select("img[src], img[vurl]"):
                for attribute in ("src", "vurl"):
                    if asset := image.get(attribute):
                        target = urljoin(url, asset)
                        if jlu_contact_png(target):
                            images.add(target)
    visible_hrefs = {f"mailto:{value.casefold()}" for value in addresses}
    return addresses, {href for href in misdirected if href.casefold() not in visible_hrefs}, images


def _labelled_fields(nodes):
    observed = {field: set() for field in _FIELDS}
    for node in nodes:
        raw = node.get_text(" ", strip=True)
        parts = re.split(r"[:：]", raw, maxsplit=1)
        label = parts[0].strip()
        value = parts[1].strip() if len(parts) == 2 else ""
        if not value and (_ADDRESS.fullmatch(label) or _DIRECTION.fullmatch(label)):
            sibling = node.find_next_sibling()
            if sibling and (node.name, sibling.name) in (("td", "td"), ("th", "td"), ("p", "p")):
                value = sibling.get_text(" ", strip=True)
                if node.name == "p" and _DIRECTION.fullmatch(label) and value.startswith("[1]"):
                    parts = [value]
                    for index, following in enumerate(sibling.find_next_siblings(), 2):
                        if following.name != "p":
                            break
                        topic = following.get_text(" ", strip=True)
                        if not topic.startswith(f"[{index}]"):
                            break
                        parts.append(topic)
                    value = " ".join(parts)
        if _ADDRESS.fullmatch(label):
            if address := _public_address(value):
                observed["email"].add(address)
        elif _DIRECTION.fullmatch(label) and value:
            # An empty section can be followed by the next labelled field.
            if re.match(r"^(?:介绍|个人|科研项目|论文|教育|联系方式|招生|邮\s*箱|Email|发表论文|获奖|项目)(?:经历|成果|信息)?\s*[:：]", value, re.I):
                continue
            if direction := clean_research(value):
                observed["research_direction_raw"].add(direction)
    return observed


def _named_roster_fields(read, name, url):
    found = {field: {} for field in _FIELDS}
    first = BeautifulSoup(read(_ROSTER)[1], "html.parser")
    pages = sorted({target for a in first.select("a[href]") if _ROSTER_PAGE.fullmatch(target := urljoin(_ROSTER, a["href"]))})
    if len(pages) > 10:
        raise ValueError("吉大师资目录分页超出预期")
    for source in [_ROSTER, *pages]:
        soup = first if source == _ROSTER else BeautifulSoup(read(source)[1], "html.parser")
        if not soup.title or soup.title.get_text(strip=True) != "准聘长聘教师-" + _COLLEGE:
            raise ValueError("吉大师资目录标题变化，未采用目录字段")
        for card in soup.select(".text.fr"):
            anchor = card.select_one("a.name[href]")
            if not anchor or anchor.get_text(strip=True) != name or urljoin(source, anchor["href"]) != url:
                continue
            for field, values in _labelled_fields(card.select("p.info")).items():
                for value in values:
                    found[field].setdefault(value, source)
    return {field: next(iter(values.items())) for field, values in found.items() if len(values) == 1}


def _person_scope(cfg, html, url):
    original = cfg["_original_profile"]
    name = original["name"]
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    expected = cfg.get("_expected_name") or name
    if (not _PERSON.fullmatch(url) or expected != name or
            "".join(title.split()) != "".join(f"{name}-{_COLLEGE}".split())):
        raise ValueError("吉大本人页姓名未与当前档案一致")
    return soup.select_one(".v_news_content, #vsb_content, .wp_articlecontent")


def _registered_fields(cfg, html, url):
    original = cfg["_original_profile"]
    name = original["name"]
    scope = _person_scope(cfg, html, url)
    direct = _labelled_fields(scope.select("td, th, p, li")) if scope else {}
    provenance = original.get("provenance") or {}
    fields = [field for field in _FIELDS if (provenance.get(field) or {}).get("origin") != "manual"]
    if cfg.get("contact_hook_only") and "email" in fields:
        fields.remove("email")
    picked = {field: next(iter(values)) for field, values in direct.items()
              if field in fields and len(values) == 1}
    missing = [field for field in fields if not direct.get(field)]
    sources = {}
    if missing and cfg.get("profile_field_roster") == _ROSTER and cfg.get("_read_source"):
        try:
            roster = _named_roster_fields(cfg["_read_source"], name, url)
        except (DiscoveryBudgetExhausted, OSError, ValueError):
            roster = {}
        for field in missing:
            if field in roster:
                picked[field], sources[field] = roster[field]
    return dict(picked, name=name, **({"_field_sources": sources} if sources else {}))


def parse_contact(cfg, person):
    read = cfg.get("_read_source")
    url, name = person["detail_url"], person["name"]
    previous = (person.get("provenance") or {}).get("email") or {}
    if not cfg.get("contact_hook_only") or not read or previous.get("origin") == "manual" or not _PERSON.fullmatch(url):
        return {}
    _, html = read(url)
    scope = _person_scope(dict(cfg, _original_profile=person), html, url)
    if not scope:
        return {}
    explicit_name = _simple_parse(cfg, html, url).get("name")
    if explicit_name and "".join(explicit_name.split()) != "".join(name.split()):
        raise ValueError("吉大本人正文姓名未与当前档案一致")
    visible, wrong_links, images = _contact_rows(scope, url)
    result = {"name": name, "_verified_roster_name": name, "_field_sources": {"email": url},
              "_contact_locator": {"email": {"article_url": url, "named_person": name}}}
    locator = result["_contact_locator"]["email"]
    if len(visible) == 1:
        result["email"] = next(iter(visible))
        return result
    if visible:
        old = person.get("email") or cfg.get("_previous_email")
        old_href = f"mailto:{old}"
        if (old and old_href in wrong_links and previous.get("origin") == "crawled"
                and previous.get("source") == url):
            result["_rejected_email"] = old
            locator.update(visible_addresses=sorted(visible), rejected_mailto=old_href)
            return result
        return {}
    if images:
        if len(images) != 1:
            return {}
        source, = images
        raw, _ = read(source)
        approved = (cfg.get("reviewed_email_images") or {}).get(url) or {}
        if (approved.get("name") == name and approved.get("url") == source
                and raw.startswith(b"\x89PNG\r\n\x1a\n") and sha256(raw).hexdigest() == approved.get("sha256")
                and (address := _public_address(approved.get("text", "")))):
            result["email"] = address
            result["_field_sources"]["email"] = source
            locator.update(image_sha256=approved["sha256"], image_transcription=approved["text"])
            return result
        return {}
    if cfg.get("profile_field_roster") == _ROSTER:
        if field := _named_roster_fields(read, name, url).get("email"):
            result["email"], result["_field_sources"]["email"] = field
            locator["directory_url"] = field[1]
            return result
    return {}


def parse_detail(cfg, html, url):
    out = _simple_parse(cfg, html, url)
    out.pop("email", None)
    if cfg.get("_original_profile"):
        name = cfg["_original_profile"]["name"]
        if out.get("name") and "".join(out["name"].split()) != "".join(name.split()):
            raise ValueError("吉大本人正文姓名未与当前档案一致")
        for field in _FIELDS:
            out.pop(field, None)
        out.update(_registered_fields(cfg, html, url))
    if not out.get("supervisor"):
        # 基本信息表的结构化标注: "是否博导：是/否"——只取"是", "否"绝不入库
        from crawler.supervisor_util import extract_supervisor
        soup = BeautifulSoup(html, "html.parser")
        sup = extract_supervisor(soup.get_text("\n", strip=True))
        if sup:
            out["supervisor"] = sup
    return out

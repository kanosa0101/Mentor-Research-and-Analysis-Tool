import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler.mentor_recovery import canonical, homepage_url, personal_email
from sites.profile_fields import clean_research
from sites.ucas import cas_lists


_PERSON_PATH = re.compile(r"/sourcedb/cn/jssrck/20\d{4}/t20\d{6}_\d+\.html")
_LITERAL = re.compile(r'\bvar\s+(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"')
_DIRECTION_BINDING = re.compile(
    r"\bvar\s+textContent\s*=\s*yjfx\.replace\([^\n]+\)\s*;?\s*"
    r"""\$\(\s*['"]#yj['"]\s*\)\.html\(\s*textContent\s*\)"""
)
_DIRECTION_LABEL = re.compile(
    r"(?:主要)?研究(?:方向|领域|兴趣)(?:主要)?(?:为|是|包括|包含|涵盖|集中在|聚焦于|[：:])\s*[：:]?\s*(.+)"
)
_DIRECTION_END = re.compile(
    r"(?:^|[，,；;。])\s*[（(]?\s*(?:研究组主页|课题组主页|团队主页|个人主页|联系方式|邮箱|"
    r"代表(?:性)?论文|主要论著|科研项目|讲授课程|招生(?:要求|方向|对象|信息))\s*[：:]",
)
_CV_TITLE = r"(?:研究员|副研究员|助理研究员|教授|副教授|博士生导师|硕士生导师|博导|硕导)"
_ADMISSION_SUBJECT = re.compile(r"-?\s*(?:导师类别\s*[：:]?\s*)?(?:计算机系统结构|计算机应用技术|计算机软件与理论)")
_ONE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+\s*(?:@|＠|[（(]\s*(?:@|＠|at)\s*[)）])\s*[A-Za-z0-9.\-]+")
_SHARED_ADDRESSES = {"ictoffice@ict.ac.cn", "ict@ict.ac.cn", "yjs@ict.ac.cn"}


def iter_roster(cfg):
    return cas_lists.walk_and_collect(cfg, cfg["list"]["urls"])


def _text(value):
    return " ".join((value or "").split())


def _label(card, key, label):
    found = card.select(f"p.p-people-content > b#{key}")
    if len(found) == 1 and _text(found[0].get_text()).rstrip("：:") == label:
        return found[0].find_next_sibling("span")
    return None


def _person_page(html, url, expected):
    target = urlsplit(url)
    if (target.scheme not in ("http", "https") or target.netloc not in ("www.ict.ac.cn", "ict.cas.cn", "www.ict.cas.cn")
            or target.query or target.fragment or not _PERSON_PATH.fullmatch(target.path)):
        return None
    doc = BeautifulSoup(html, "html.parser")
    cards = doc.select(".main .swwls_ryxl dd.swwls_imgtextlist_dd")
    scripts = [tag.get_text() for tag in doc.select("script:not([src])") if re.search(r"\bvar\s+xm\s*=", tag.get_text())]
    if len(cards) != 1 or len(scripts) != 1:
        return None
    values = {}
    for key, value in _LITERAL.findall(scripts[0]):
        if key in values:
            raise ValueError("计算所本人页存在重复字段定义")
        try:
            values[key] = json.loads('"' + value + '"')
        except ValueError:
            continue
    name = _text(values.get("xm"))
    heading = cards[0].select_one("h5")
    display = _text(heading.get_text(" ", strip=True)) if heading else ""
    if (not re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", name) or not display or display.split()[0] != name
            or not doc.title or _text(doc.title.get_text()) != name + "--中国科学院计算技术研究所"
            or expected and expected != name):
        raise ValueError("计算所本人页姓名与已登记身份不符")
    return doc, cards[0], values, scripts[0], name


def _topics(value):
    if not value:
        return None
    value = _DIRECTION_END.split(value, maxsplit=1)[0]
    if not value or re.search(r"https?://|www\.|[A-Za-z0-9._%+-]+@", value):
        return None
    direction = clean_research(value)
    return None if not direction or direction in {"—", "--", "暂无", "暂无内容", "待补充", "未填写", "undefined"} else direction


def _cv(doc):
    labels = doc.select(".main .tem01-people-content > h3#jl")
    if len(labels) == 1 and re.sub(r"\s+", "", labels[0].get_text()).rstrip("：:") == "简历":
        return labels[0].find_next_sibling("div")
    return None


def _cv_direction(cv, name):
    first = cv.find("p") if cv else None
    paragraph = _text(first.get_text(" ", strip=True)) if first else ""
    if not paragraph.startswith(name):
        return None
    directions = []
    sentences = re.split(r"[。！？]", paragraph)
    own_intro = re.fullmatch(re.escape(name) + r"(?:[，,\s]+" + _CV_TITLE + r")*[，,\s]*", sentences[0])
    for index, sentence in enumerate(sentences):
        match = _DIRECTION_LABEL.search(sentence)
        if not match:
            continue
        subject = sentence[:match.start()].strip(" ，,")
        # A bare direction in the next sentence inherits only a clean self-introduction.
        if subject in (name, "本人") or not subject and index == 1 and own_intro:
            if value := _topics(match[1]):
                directions.append(value)
    return directions[0] if len(directions) == 1 else None


def _registered_value(original, field, value):
    return bool(value and ((original.get("provenance") or {}).get(field) or {}).get("origin") != "manual"
                and original.get(field) in (None, "", value))


def _email(card, values):
    node = _label(card, "dzyj", "联系方式")
    rendered = _text(node.get_text(" ", strip=True)) if node else ""
    if rendered != _text(values.get("dzyj")) or not _ONE_EMAIL.fullmatch(rendered):
        return None
    email = personal_email(rendered)
    return email if email and email.casefold() not in _SHARED_ADDRESSES else None


def _homepage(card, values, url):
    node = _label(card, "grwy", "个人网页")
    links = node.select("a[href]") if node else []
    target = homepage_url(links[0]["href"].strip()) if len(links) == 1 else None
    if not target or target != (values.get("grwy") or "").strip():
        return None
    parts = urlsplit(target)
    if canonical(url) == canonical(target) or _PERSON_PATH.fullmatch(parts.path):
        return None
    return target


def _historical_category(original, url, rendered, dedicated):
    field = "research_direction_raw"
    old = original.get(field)
    provenance = (original.get("provenance") or {}).get(field) or {}
    if not dedicated or not old or old == dedicated or not _ADMISSION_SUBJECT.fullmatch(old):
        return False
    if provenance.get("origin") != "crawled" or provenance.get("source") != url:
        return False
    # The previous adapter stored the remainder of the mentor-category cell as
    # a direction. Require its exact retained value before correcting that field.
    remainder = re.sub(r"博士生导师|硕士生导师|博导|硕导", "", rendered)
    return clean_research(remainder) == old


def parse_detail(cfg, html, url):
    original = cfg.get("_original_profile") or {}
    profile = _person_page(html, url, cfg.get("_expected_name") or original.get("name"))
    if profile is None:
        return {}
    doc, card, values, script, name = profile
    out = {"name": name, "institute_from_detail": []}
    category = _label(card, "qtbz", "导师类别")
    category = _text(category.get_text(" ", strip=True)) if category else ""
    supervisor = "、".join(role for role in ("博导", "硕导") if role in category and category == _text(values.get("qtbz")))
    direction_slot = _label(card, "yjfx", "研究方向")
    dedicated = (_topics(_text(BeautifulSoup(values["yjfx"], "html.parser").get_text(" ", strip=True)))
                 if values.get("yjfx") and direction_slot and direction_slot.get("id") == "yj"
                 and _DIRECTION_BINDING.search(script) else None)
    cv = _cv(doc)
    direction = dedicated or _cv_direction(cv, name)
    stated = {
        "title": _text(values.get("zc")),
        "supervisor": supervisor,
        "bio_raw": cv.get_text("\n", strip=True) if cv else None,
        "email": _email(card, values),
    }
    for field, value in stated.items():
        if _registered_value(original, field, value):
            out[field] = value
    if (_registered_value(original, "research_direction_raw", direction)
            or category == _text(values.get("qtbz")) and _historical_category(original, url, category, dedicated)):
        out["research_direction_raw"] = direction
        out["research_directions"] = [direction]
    photo = doc.select_one(".main .swwls_ryxl img#photo[src]")
    if photo and photo["src"] and _registered_value(original, "photo_url", urljoin(url, photo["src"])):
        out["photo_url"] = urljoin(url, photo["src"])
    return out


def parse_contact(cfg, person):
    """Return declared contacts to the field task for independent verification."""
    provenance = person.get("provenance") or {}
    managed_email = (provenance.get("email") or {}).get("origin") != "manual"
    missing_homepage = not person.get("homepage") and (provenance.get("homepage") or {}).get("origin") != "manual"
    reader = cfg.get("_read_source")
    url = person["detail_url"]
    if not reader or not (managed_email or missing_homepage):
        return {}
    _, html = reader(url)
    profile = _person_page(html, url, person["name"])
    if profile is None:
        return {}
    _, card, values, _, name = profile
    contacts = {}
    email = _email(card, values) if managed_email else None
    previous = cfg.get("_previous_email") or person.get("email")
    if email and (not previous or previous.casefold() == email.casefold()):
        contacts["email"] = previous or email
    if missing_homepage and (page := _homepage(card, values, url)):
        contacts["homepage"] = page
    if not contacts:
        return {}
    return {**contacts, "_verified_roster_name": name, "_field_sources": dict.fromkeys(contacts, url)}

import re
from functools import lru_cache
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.mentor_recovery import IdentityConflict, directory_link_name, personal_email
from sites.profile_fields import clean_research, qualification

# 电子科大计算机(网络空间安全)学院: www.scse.uestc.edu.cn 网防(202 质询页,
# requests 视为成功——fetch 的 202+短响应特征降级 CDP)。师资列表 js_sz.jsp
# GET 筛选(FirstLetter=A..Z, fromWenCountNo=99 每页全量), 卡片 img alt=姓名 +
# span.name 第二个=职称; 详情 /info/1081/N.htm 学院文章页(瑞数? CDP 可过),
# 标签行 姓名/专业技术职务/系别/邮箱 + 【个人背景】【研究方向】段。
_BASE = "https://www.scse.uestc.edu.cn/js_sz.jsp"
_QUERY = ("urltype=tree.TreeTempUrl&wbtreeid=1081"
          "&Department=&JobTitle=&JobTitle2=&fromWenCountNo=99&FirstLetter={}")
_CARD = re.compile(
    r'href="(/info/1081/\d+\.htm)">\s*<div class="fls-pic"><img alt="([^"]+)"'
    r'[^>]*>.*?<span class="name">([^<]*)</span>\s*(?:<span class="name">([^<]*)</span>)?',
    re.S)
_TITLE = re.compile(r"(讲席|特聘|长聘)?(教授|副教授|助理教授|研究员|副研究员|讲师|工程师|实验师)")
_GRADUATE_DIRECTORY = "https://yjsjy.uestc.edu.cn/gmis/jcsjgl/dsfc/index/"
_GRADUATE_DETAIL = re.compile(r"https://yjsjy\.uestc\.edu\.cn/gmis/jcsjgl/dsfc/dsgrjj/(\d+)\?yxsh=08")
_GRADUATE_COLLEGE = "计算机科学与工程学院（网络空间安全学院）"
_DIRECTION = re.compile(
    r"^(?:目前|现阶段|当前)?(?:主要)?研究(?:方向|领域|兴趣)(?:主要)?\s*"
    r"(?:包括但不限于|集中(?:在|于)|聚焦(?:在|于)|为|是|包括|涵盖|处于|[：:])\s*[：:]?\s*(.+)"
)
_RESEARCH_WORK = re.compile(r"^(?:目前|长期|主要)从事\s*(.+?(?:研究工作|研究))(?:$|[，,；;])")
_OTHER_CONTEXT = re.compile(r"以下(?:介绍|为)|导师为|我的导师|师从|学生的|合作者|合作导师|课题组的|团队(?:的|整体|介绍)")
_CONTINUATION = re.compile(r"[，,；;]\s*(?=先后|已经|已发表|迄今|发表|获得|讲授|任教|主持|承担|参与|欢迎|"
                           r"招生|指导学生|代表作|任职|担任|论文|入选|"
                           r"近(?:\d+年|年)(?:已|曾|共|发表)|在[^。]{1,45}(?:期刊|会议)[^。]{0,12}发表)")
_NON_TOPIC = re.compile(r"https?://|\S+@\S+|招生专业|招生方向|负责项目|教学任务|任教|主讲课程|导师的研究")


def _graduate_title(html):
    return " ".join(html.get_text(" ", strip=True).split()) if html else ""


@lru_cache(maxsize=2)
def _graduate_roster(html):
    doc = BeautifulSoup(html, "html.parser")
    headers = doc.find_all("td", id="08", class_="yx_class")
    if len(headers) != 1 or _graduate_title(headers[0]) != "08 " + _GRADUATE_COLLEGE:
        raise ValueError("研招名录缺少可核对的计算机学院08栏目")
    entries = {}
    for link in headers[0].find_parent("table").select('a[href*="/dsgrjj/"]'):
        url = urljoin(_GRADUATE_DIRECTORY, link["href"])
        if label := directory_link_name(link, _GRADUATE_DIRECTORY):
            entries.setdefault(label, set()).add(url)
    if not entries:
        raise ValueError("研招名录计算机学院08栏目没有具名本人直链")
    return entries


def _unique_label(doc, label):
    nodes = doc.find_all(id=label)
    return nodes[0] if len(nodes) == 1 else None


def _graduate_identity(html, url, expected):
    match = _GRADUATE_DETAIL.fullmatch(url)
    if not match:
        return None
    doc = BeautifulSoup(html, "html.parser")
    name = _graduate_title(_unique_label(doc, "Labeldsxm"))
    college = _graduate_title(_unique_label(doc, "Labelxymc"))
    code = _graduate_title(_unique_label(doc, "Labeldsdm"))
    if (_graduate_title(doc.title) != "导师个人信息 - 电子科大研招网"
            or not re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", name) or not college or not code):
        raise ValueError("研招正文缺少唯一姓名、导师代码或学院")
    if college != _GRADUATE_COLLEGE or code != match[1] or expected and name != expected:
        raise IdentityConflict("研招本人页姓名、导师代码或学院与登记不符")
    local = _unique_label(doc, "Labelemail")
    cell = local.parent if local and local.parent.name == "td" else None
    heading = cell.find_previous_sibling("td") if cell else None
    printed = cell.get_text("", strip=True) if heading and _graduate_title(heading) == "电子邮件：" else ""
    email = personal_email(printed) if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", printed) else None
    return doc, name, email


def _graduate_topics(text, name):
    direct, work = set(), set()
    own = re.compile(r"^" + re.escape(name) + r"(?:博士|教授|副教授|老师)?[，,\s]*")
    following_bio = re.compile(r"\s+" + re.escape(name) + r"(?:博士|教授|副教授|老师)[，, ]")
    segments = re.split(r"[。！？]", text)
    previous = ""
    for offset, segment in enumerate(segments):
        segment = segment.strip()
        subject = own.match(segment)
        intro = segment[subject.end():] if subject else segment.removeprefix("本人").lstrip("，, ")
        if not subject and _OTHER_CONTEXT.search(previous):
            previous = segment
            continue
        previous = segment
        match = _DIRECTION.match(intro)
        destination = direct if match else work
        match = match or _RESEARCH_WORK.match(intro)
        if match:
            value = _CONTINUATION.split(match[1], maxsplit=1)[0].strip()
            value = following_bio.split(value, maxsplit=1)[0]
            if destination is direct and re.match(r"1、", value):
                # A numbered direction list may span several sentences.
                items = [value.removeprefix("1、").strip()]
                for later in segments[offset + 1:]:
                    item = re.match(r"\s*(\d+)、\s*(.+)", later)
                    if item:
                        if int(item[1]) != len(items) + 1:
                            break
                        items.append(_CONTINUATION.split(item[2], maxsplit=1)[0])
                    elif re.search(r"招生|论文|联系方式|教育经历|获奖|科研项目", later):
                        break
                if len(items) < 2:
                    continue
                value = "；".join(items)
            if 2 <= len(value) <= 500 and not _NON_TOPIC.search(value):
                direction = clean_research(value)
                if direction:
                    destination.add(direction)
    return direct or work


def _keep(original, field, value):
    provenance = (original.get("provenance") or {}).get(field) or {}
    return value and original.get(field) in (None, "", value) and provenance.get("origin") != "manual"


def _graduate_role(section, name):
    opening = re.split(r"[。；;]", section, maxsplit=1)[0]
    if re.search(r"晋升|获批|以前|过去|历史|\d{4}\s*年", opening) and not re.search(r"至今|现任", opening):
        return None
    return qualification(section, name)


def _parse_graduate(cfg, html, url):
    original = cfg.get("_original_profile") or {}
    doc, name, email = _graduate_identity(html, url, cfg.get("_expected_name") or original.get("name"))
    old_email = personal_email(original.get("email"))
    if email and old_email and email.casefold() != old_email.casefold():
        raise IdentityConflict("研招本人页邮箱与原记录不一致，保留矛盾待核对")
    if original.get("detail_url") and original["detail_url"] != url:
        reader = cfg.get("_read_source")
        if not (reader and email and old_email):
            raise ValueError("缺少原登记本人邮箱或08研招名录的独立身份依据")
        _, parent = reader(_GRADUATE_DIRECTORY)
        if _graduate_roster(parent).get(name) != {url}:
            raise ValueError("08研招名录缺少唯一实名直链，保留原登记")

    out = {"name": name}
    if email:
        out["email"] = email  # Also supplies the existing recovery identity gate.
    sections = [_graduate_title(_unique_label(doc, key)) for key in ("Labelgrjj", "Labelxsjl")]
    # Give an explicit direction in the personal introduction priority over
    # academic history, while declining conflicting claims in either section.
    for section in sections:
        topics = _graduate_topics(section, name)
        if topics:
            if len(topics) == 1:
                direction = next(iter(topics))
                if _keep(original, "research_direction_raw", direction):
                    out["research_direction_raw"] = direction
                    out["research_directions"] = [direction]
            break
    roles = {value for section in sections if (value := _graduate_role(section, name))}
    if len(roles) == 1:
        role = next(iter(roles))
        if _keep(original, "supervisor", role):
            out["supervisor"] = role
    title = _graduate_title(_unique_label(doc, "Labelzc"))
    if original.get("title") == title and _keep(original, "title", title):
        out["title"] = title
    return out


def iter_roster(cfg):
    if _GRADUATE_DIRECTORY in cfg.get("list", {}).get("urls", ()):
        raise ValueError("电子科大研招08导师名录仅用于核验既有资料，不能作为完整院系师资名单导入")
    people = {}
    meta = None
    for L in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        url = f"{_BASE}?{_QUERY.format(L)}"
        try:
            text, meta, _ = fetch.fetch_text("GET", url)
        except Exception:
            continue
        for href, nm, t1, t2 in _CARD.findall(text or ""):
            nm = nm.strip()
            if not nm or not re.match(r"^[\u4e00-\u9fa5·A-Za-z\s·]{2,30}$", nm):
                continue
            full = "https://www.scse.uestc.edu.cn" + href
            rec = people.setdefault(nm, {"name": nm, "url": full, "profile_url": full,
                                         "institutes": []})
            # 卡片第二个 span.name 是职称(第一个与姓名重复)
            for cand in (t2, t1):
                if cand and _TITLE.fullmatch(cand.strip()) and "list_title" not in rec:
                    rec["list_title"] = cand.strip()
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    if _GRADUATE_DETAIL.fullmatch(url):
        return _parse_graduate(cfg, html, url)
    if not re.fullmatch(r"https://www\.scse\.uestc\.edu\.cn/info/1081/\d+\.htm", url):
        return {}
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    txt = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    for line in lines:
        m = re.match(r"姓名\s*[:：]\s*([\u4e00-\u9fa5·A-Za-z\s]{2,30})$", line)
        if m and "name" not in out:
            out["name"] = m.group(1).strip()
        m = re.match(r"专业技术职务\s*[:：]\s*(.+)$", line)
        if m:
            t = _TITLE.search(m.group(1))
            if t:
                out["title"] = t.group(0)
        m = re.match(r"系别\s*[:：]\s*(.+)$", line)
        if m:
            out.setdefault("institutes", [m.group(1).strip()])
        m = re.match(r"邮\s*箱\s*[:：]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})$", line)
        if m and "email" not in out:
            out["email"] = m.group(1)
    # 【研究方向】段
    m = re.search(r"【研究方向】\s*\n(.+?)\n\s*【", txt, re.S)
    if m:
        rd = re.sub(r"\s+", " ", m.group(1)).strip()
        if rd:
            out["research_direction_raw"] = rd[:500]
    # 【个人背景】→ bio；本人自述"…教授，博导"可提导师资格
    m = re.search(r"【个人背景】\s*\n(.+?)\n\s*【", txt, re.S)
    if m:
        bio = re.sub(r"[ \t\r]+", " ", m.group(1)).strip()
        if len(bio) > 20:
            out["bio_raw"] = bio[:2000]
            if "email" not in out:
                e = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", bio)
                if e:
                    out["email"] = e.group(0)
    if "supervisor" not in out:
        seg = txt[:len(txt) // 3]
        sup = [s for s in ("博士生导师", "硕士生导师") if s in seg]
        if sup:
            out["supervisor"] = "、".join("博导" if "博士" in s else "硕导" for s in sup)
    if _GRADUATE_DIRECTORY in cfg.get("list", {}).get("urls", ()):
        original = cfg.get("_original_profile") or {}
        expected = cfg.get("_expected_name") or original.get("name")
        if not out.get("name"):
            raise ValueError("旧学院文章缺少一致的本人姓名，保留原记录")
        if expected and out["name"] != expected:
            raise IdentityConflict("旧学院文章明确姓名与原档不符，保留原记录")
        role = _graduate_role(out.get("bio_raw") or "", out["name"])
        out.pop("supervisor", None)
        if role:
            out["supervisor"] = role
        out = {key: value for key, value in out.items()
               if key == "name" or _keep(original, key, value)}
        if "research_direction_raw" in out:
            out["research_directions"] = [out["research_direction_raw"]]
    return out


def parse_contact(cfg, person):
    reader = cfg.get("_read_source")
    url = person["detail_url"]
    email_origin = (person.get("provenance", {}).get("email") or {}).get("origin")
    if not reader or not _GRADUATE_DETAIL.fullmatch(url) or email_origin == "manual":
        return {}
    _, html = reader(url)
    _, name, email = _graduate_identity(html, url, person["name"])
    previous = cfg.get("_previous_email") or person.get("email")
    if not email:
        return {}
    if previous and previous.casefold() != email.casefold():
        raise IdentityConflict("研招本人页邮箱与原记录不一致，保留矛盾待核对")
    return {"email": previous or email, "_verified_roster_name": name, "_field_sources": {"email": url}}

"""吉林大学计算机学院（ccst.jlu.edu.cn）。
存量维护只采用本人页或现行具名名录的明确方向与公开邮箱。
早期详情页存在图片邮箱，原始采集入口仍支持旧 OCR 解析。
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.mentor_recovery import DiscoveryBudgetExhausted, personal_email
from sites.profile_fields import clean_research
from sites.simple_list import parse_detail as _simple_parse, iter_roster as _simple_roster

_EMAIL_IMG = re.compile(
    r"(?:电子邮箱|Email|邮箱)\s*[：:]?\s*</td>\s*<td[^>]*>\s*<img\s+([^>]+)>", re.I)
# vsb CMS 的 img 真实路径常在 vurl 属性(src 可能是丢目录的相对名)
_VURL = re.compile(r'vurl="([^"]+)"', re.I)
_SRC = re.compile(r'src="([^"]+)"', re.I)
_EMAIL_OK = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_LOCAL_OK = re.compile(r"^[A-Za-z0-9._%+-]{2,30}$")
_OCR = None
_COLLEGE = "吉林大学计算机科学与技术学院"
_PERSON = re.compile(r"https://ccst\.jlu\.edu\.cn/info/\d+/\d+\.htm")
_ROSTER = "https://ccst.jlu.edu.cn/szdw/zpzpjs.htm"
_ROSTER_PAGE = re.compile(r"https://ccst\.jlu\.edu\.cn/szdw/zpzpjs/\d+\.htm")
_DIRECTION = re.compile(r"(?:所|主要|目前的?|当前的?)?(?:研究(?:方向|领域|兴趣)|科研方向)")
_ADDRESS = re.compile(r"(?:电子邮箱|电子邮件|邮\s*箱|E-?mail)", re.I)
_FIELDS = ("email", "research_direction_raw")


def iter_roster(cfg):
    return _simple_roster(cfg)


def _repair_email(boxes):
    joined = " ".join(t for _, t, _ in boxes)
    # 混淆写法还原: "xxx at yyy" / "xxx [AT] yyy" → "@"; 必须在去空格前做
    joined = re.sub(r"(?i)(?<=\s)\[?\(?at\)?\]?(?=\s|$)", "@", joined)
    joined = re.sub(r"\s+", "", joined)
    if not joined:
        return None
    local = rest = None
    if "@" in joined:
        local, _, rest = joined.partition("@")
    else:
        # '@' 漏检: 从尾部剥已知域名(mail.)jlu[.edu[.cn]]
        m = re.search(r"(mail\.?)?jlu\.?(?:edu\.?cn)?$", joined, re.I)
        if m and m.start() >= 2:
            local = joined[:m.start()]
    if not (local and _LOCAL_OK.fullmatch(local)):
        return None
    # OCR 混淆: 行首大写 I 实为 l(lxf 误读 Ixf)
    if re.fullmatch(r"I[a-z0-9]+", local):
        local = "l" + local[1:]
    # OCR 常把域名拆碎/漏字("jlu.edu" + "cn"→"jlueducn" 乃至 "eedu.ccn"),
    # 一律去点后按已知模式匹配重组, 不信碎片整串
    nodots = re.sub(r"[^a-z0-9]", "", (rest or "").lower())
    if nodots.startswith("mailjlu") or nodots.startswith("mail"):
        return local + "@mail.jlu.edu.cn"
    if nodots.startswith("jlu") or nodots in ("", "educn", "edu", "cn"):
        return local + "@jlu.edu.cn"
    # 常见公共邮箱域(OCR 常见 "163.ccom" 形近错字)
    pm = re.fullmatch(r"(163|126|qq|sohu|sina|gmail|hotmail|yeah|aliyun|139|foxmail)cc?om", nodots)
    if pm:
        return local + "@" + pm.group(1) + ".com"
    if nodots == "yeahnet":
        return local + "@yeah.net"
    if _EMAIL_OK.fullmatch(joined):
        parts = (rest or "").lower().split(".")
        if len(parts) >= 2 and all(p for p in parts):
            return joined.lower()
    return None


def _ocr_email_image(img_url, page_url):
    global _OCR
    try:
        raw, _, _ = fetch.fetch("GET", img_url)
    except Exception:
        return None
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or min(img.shape[:2]) < 5:
        return None
    big = cv2.resize(img, None, fx=6, fy=6, interpolation=cv2.INTER_LANCZOS4)
    big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    # det 模型对细长低对比单行图常丢前段, 直接调识别模型整行读
    try:
        res, _ = _OCR.text_recognizer(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR))
    except Exception:
        return None
    boxes = [[None, t, c] for t, c in (res or [])]
    return _repair_email(boxes or [])


def _public_address(value):
    if not _EMAIL_OK.fullmatch(value) and value.count("AT") == 1:
        local, domain = value.split("AT")
        if re.fullmatch(r"[A-Za-z0-9-]+(?:DOT[A-Za-z0-9-]+)+", domain):
            value = local + "@" + domain.replace("DOT", ".")
    return personal_email(value) if _EMAIL_OK.fullmatch(value) else None


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


def _registered_fields(cfg, html, url):
    original = cfg["_original_profile"]
    name = original["name"]
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    expected = cfg.get("_expected_name") or name
    if (not _PERSON.fullmatch(url) or expected != name or
            "".join(title.split()) != "".join(f"{name}-{_COLLEGE}".split())):
        raise ValueError("吉大本人页姓名未与当前档案一致")
    scope = soup.select_one(".v_news_content, #vsb_content, .wp_articlecontent")
    direct = _labelled_fields(scope.select("td, th, p, li")) if scope else {}
    provenance = original.get("provenance") or {}
    fields = [field for field in _FIELDS if (provenance.get(field) or {}).get("origin") != "manual"]
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


def parse_detail(cfg, html, url):
    out = _simple_parse(cfg, html, url)
    if cfg.get("_original_profile"):
        name = cfg["_original_profile"]["name"]
        if out.get("name") and "".join(out["name"].split()) != "".join(name.split()):
            raise ValueError("吉大本人正文姓名未与当前档案一致")
        for field in _FIELDS:
            out.pop(field, None)
        out.update(_registered_fields(cfg, html, url))
    elif not out.get("email"):
        m = _EMAIL_IMG.search(html)
        if m:
            # vurl 有两种形态: /__local/…png 原图 或 /_vsl/… 缩略图(OCR 失败), 依次回退
            cands = []
            for rx in (_VURL, _SRC):
                sm = rx.search(m.group(1))
                if sm:
                    cands.append(sm.group(1))
            for src in cands:
                if src.startswith("__local"):
                    src = "/" + src
                if not src.startswith("http"):
                    src = urljoin(url, src)
                e = _ocr_email_image(src, url)
                if e:
                    out["email"] = e
                    break
    if not out.get("supervisor"):
        # 基本信息表的结构化标注: "是否博导：是/否"——只取"是", "否"绝不入库
        from crawler.supervisor_util import extract_supervisor
        soup = BeautifulSoup(html, "html.parser")
        sup = extract_supervisor(soup.get_text("\n", strip=True))
        if sup:
            out["supervisor"] = sup
    return out

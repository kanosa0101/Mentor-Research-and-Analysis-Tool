import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch
from sites.wp import parse_wp_detail


def iter_roster(cfg):
    people = {}
    meta = None
    for lu in cfg["list"]["urls"]:
        text, meta, _ = fetch.fetch_text("GET", lu)
        for rec in _collect(cfg, lu, text):
            people.setdefault(rec["name"], rec)
    return list(people.values()), meta


def _collect(cfg, page_url, text):
    pattern = re.compile(cfg["list"]["person_href"])
    soup = BeautifulSoup(text, "html.parser")
    out = {}
    # 语言切换链接("中文"/"English")可能指向教师页同名路径, 会被误当人名
    # (ruc/ai 出过 "中文" 脏记录, 与文继荣同 URL)
    _NONAME = {"中文", "English", "english", "EN", "en"}
    # 卡片布局同一详情 URL 有姓名/职称/研究方向多个锚点(sdu js.htm:
    # 于东晓+教授+分布式计算…三个 <a> 同 href), 职称词不能当人名
    _TITLE_WORDS = {"教授", "副教授", "研究员", "副研究员", "助理教授",
                    "助理研究员", "讲师", "助教", "工程师", "高级工程师",
                    "博导", "硕导"}
    for a in soup.select("a[href]"):
        nm = re.sub(r"\s+", "", a.get("title") or a.get_text(strip=True) or "")
        nm = re.sub(r"[（(][^)）]*[)）]", "", nm)
        if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", nm):
            continue
        if nm in _NONAME or nm in _TITLE_WORDS:
            continue
        href = urljoin(page_url, a["href"])
        if not pattern.search(href):
            continue
        rec = {"name": nm, "url": href, "profile_url": href, "institutes": []}
        sup = [s for s in ("博导", "硕导") if s in (a.get("title") or "")]
        if sup:
            rec["supervisor"] = "、".join(sup)
        # 同 URL 多锚点择优: 2-4 字规范人名 > 5 字边缘形态(实验室/方向名)
        prev = out.get(href)
        q = 2 if re.match(r"^[\u4e00-\u9fa5·]{2,4}$", nm) else 1
        if prev is None or q > prev["_q"]:
            rec["_q"] = q
            out[href] = rec
    for rec in out.values():
        rec.pop("_q", None)
    return list(out.values())


def parse_detail(cfg, html, url):
    return parse_wp_detail(cfg, html, url)

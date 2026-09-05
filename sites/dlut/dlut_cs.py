"""大连理工大学（faculty.dlut.edu.cn tsites 教师系统）。
单位列表 xylb.jsp → 各学院教师列表 xyjslb.jsp?...id=<单位id>（服务端卡片:
h3 姓名 / 单位 / 职称, 链到 /<id>/zh_CN/index.htm 主页）。详情委托 tsites 钩子。
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.title_util import normalize_title
from sites import tsites

_BASE = "http://faculty.dlut.edu.cn"


def iter_roster(cfg):
    people = {}
    meta = None
    for unit_id in cfg["list"]["unit_ids"]:
        u = (f"{_BASE}/xyjslb.jsp?urltype=tsites.CollegeTeacherList"
             f"&wbtreeid=1003&st=0&id={unit_id}&lang=zh_CN")
        html, meta, _ = fetch.fetch_text("GET", u)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href*='/zh_CN/index.htm']"):
            href = str(a.get("href") or "")
            name_el = a.select_one("h3")
            if name_el is None or href in people:
                continue
            nm = name_el.get_text(strip=True)
            if not re.match(r"^[\u4e00-\u9fa5·]{2,4}$", nm):
                continue
            rec = {"name": nm, "url": href, "profile_url": href, "institutes": []}
            for p in a.select("p"):
                txt = p.get_text(" ", strip=True)
                if txt.startswith("职称") and "title" not in rec:
                    v = txt.split("：", 1)[-1].strip()
                    t, _ = normalize_title(v)
                    if t:
                        rec["title"] = t
            people[href] = rec
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    return tsites.parse_detail(cfg, html, url)

"""复旦大学计算与智能创新学院（cs.fudan.edu.cn）。
教师名录走 sudy WP generalQuery POST 接口（siteId=577, 189 人）:
title(姓名)/email/exField1(职称+博导)/exField4(研究方向)/exField5(faculty 主页)/
exField6(职称)/exField8(博导硕导)/exField9(级别)。cnUrl 详情页解析简介。
"""
import json
import re

import requests

from bs4 import BeautifulSoup

from sites.wp import parse_wp_detail

_API = "https://cs.fudan.edu.cn/_wp3services/generalQuery?queryObj=teacherHome"
_FIELDS = ["title", "email", "phone", "cnUrl", "headerPic"] \
    + [f"exField{i}" for i in range(1, 11)]


def _query():
    s = requests.Session()
    s.trust_env = False
    s.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"
    r = s.post(_API, data={
        "siteId": 577,
        "conditions": json.dumps([
            {"field": "published", "value": "1", "judge": "="},
            {"field": "language", "value": "1", "judge": "="}], ensure_ascii=False),
        "returnInfos": json.dumps([{"field": f, "name": f} for f in _FIELDS],
                                  ensure_ascii=False),
        "pageIndex": 1, "rows": 999,
        "orders": json.dumps([{"field": "siteSort", "type": "asc"}]),
        "articleType": 1, "level": 1,
    }, headers={"X-Requested-With": "XMLHttpRequest",
                "Referer": "https://cs.fudan.edu.cn/53161/list.htm"}, timeout=30)
    r.raise_for_status()
    return json.loads(r.text).get("data") or []


def iter_roster(cfg):
    people = {}
    meta = None
    for r in _query():
        nm = (r.get("title") or "").strip()
        u = (r.get("cnUrl") or "").strip()
        if not nm or not u:
            continue
        # exField5 是"个人主页"文章页——实测为空壳(无正文, meta 仅"点击进入个人主页")，
        # 只存链接不换 detail_url(ai.fudan cnUrl 仍是身份锚点)
        hp = (r.get("exField5") or "").strip()
        if hp and "fudan" in hp:
            hp = hp if hp.startswith("http") else "https://cs.fudan.edu.cn" + hp
        rec = {"name": nm, "url": u, "profile_url": u, "institutes": []}
        if hp:
            rec["homepage"] = hp
        if r.get("email"):
            rec["email"] = r["email"]
        if r.get("phone"):
            rec["phone"] = r["phone"]
        if r.get("headerPic"):
            rec["photo_url"] = ("https://cs.fudan.edu.cn" + r["headerPic"]
                                if r["headerPic"].startswith("/") else r["headerPic"])
        if r.get("exField1"):
            rec["title"] = r["exField1"]  # "教授、博导" → normalize 拆出导师资格
        elif r.get("exField6"):
            rec["title"] = r["exField6"]
        if r.get("exField8"):
            v = r["exField8"]
            sup = [x for x in ("博导", "硕导") if x[0] in v]
            if sup and "supervisor" not in rec:
                rec["supervisor"] = "、".join(sup)
        if r.get("exField4"):
            rec["research_direction_raw"] = r["exField4"][:300]
        if r.get("exField5") and "fudan" in r["exField5"]:
            rec["homepage"] = r["exField5"]
        people[u] = rec
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    if "/page.htm" not in url:
        return {}  # ai.fudan 等列表页无可解析字段
    return parse_wp_detail(cfg, html, url)

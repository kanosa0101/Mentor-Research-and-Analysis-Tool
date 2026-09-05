"""上海科技大学信息科学与技术学院（sist.shanghaitech.edu.cn）。
师资列表走 sudy WP 的 generalQuery POST 接口（exField8=分类, rows=999 一次拉全）,
返回字段: title(姓名)/email/phone/cnUrl(个人主页)/headerPic/exField1(职称+博导)/
exField4(研究方向)/exField5(研究中心)。详情页 main.htm 解析个人简介。
"""
import json
import re

import requests

from bs4 import BeautifulSoup

from crawler import fetch

_API = "https://sist.shanghaitech.edu.cn/_wp3services/generalQuery?queryObj=teacherHome"
_CATS = ["常任教授", "特聘教授", "研究人员"]
_FIELDS = ["title", "graduateSchool", "degree", "phone", "email", "cnUrl", "headerPic"] \
    + [f"exField{i}" for i in range(1, 11)]


def _query(cat):
    s = requests.Session()
    s.trust_env = False
    s.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"
    r = s.post(_API, data={
        "siteId": 43,
        "conditions": json.dumps([
            {"field": "published", "value": "1", "judge": "="},
            {"field": "language", "value": "1", "judge": "="},
            {"field": "exField8", "value": cat, "judge": "="}], ensure_ascii=False),
        "returnInfos": json.dumps([{"field": f, "name": f} for f in _FIELDS],
                                  ensure_ascii=False),
        "pageIndex": 1, "rows": 999,
        "orders": json.dumps([{"field": "siteSort", "type": "asc"}]),
        "articleType": 1, "level": 1,
    }, headers={"X-Requested-With": "XMLHttpRequest",
                "Referer": "https://sist.shanghaitech.edu.cn/szdwx/list.htm"}, timeout=30)
    r.raise_for_status()
    return json.loads(r.text).get("data") or []


def iter_roster(cfg):
    people = {}
    meta = None
    for cat in _CATS:
        for r in _query(cat):
            u = (r.get("cnUrl") or "").strip()
            nm = (r.get("title") or "").strip()
            if not u or not nm:
                continue
            if u in people:
                continue
            rec = {"name": nm, "url": u, "profile_url": u, "institutes": []}
            if r.get("email"):
                rec["email"] = r["email"]
            if r.get("phone"):
                rec["phone"] = r["phone"]
            if r.get("headerPic"):
                rec["photo_url"] = "https://sist.shanghaitech.edu.cn" + r["headerPic"] \
                    if r["headerPic"].startswith("/") else r["headerPic"]
            if r.get("exField1"):
                rec["title"] = r["exField1"]
            if r.get("exField4"):
                rec["research_direction_raw"] = r["exField4"][:300]
            if r.get("exField5"):
                rec["institutes"] = [r["exField5"]]
            people[u] = rec
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    out = {}
    m = re.search(r"个人简介\s*\n(.{30,}?)(?:\n(?:研究方向|教育经历|教育背景|工作经历|科研项目|代表性)|$)",
                  text, re.S)
    if m:
        out["bio_raw"] = m.group(1).strip()[:5000]
    m = re.search(r"主要研究方向[为是]([^。]{4,150})。", text)
    if m and "research_direction_raw" not in out:
        out["research_direction_raw"] = m.group(1).strip()[:200]
    if not out.get("email"):
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        if m:
            out["email"] = m.group(0)
    return out

"""南方科技大学计算机科学与工程系（cse.sustech.edu.cn）。
全职教师列表服务端渲染(.teacherlist 卡片: 姓名/职位/邮箱/_AT_混淆/办公地点),
?page=N 分页; 详情页 /faculty/NNNN.html(部分教师卡片直接链外部个人主页)。
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch

_BASE = "https://cse.sustech.edu.cn"


def iter_roster(cfg):
    people = {}
    meta = None
    for page in range(1, 12):
        url = f"{_BASE}/faculty/full-time-faculty/?page={page}"
        html, meta, _ = fetch.fetch_text("GET", url)
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.select(".teacherlist ul li a[href]")
        if not cards and page > 1:
            break
        for a in cards:
            href = str(a.get("href") or "")
            if not href:
                continue
            u = href if href.startswith("http") else _BASE + href
            name_el = a.select_one("h3.t-name")
            if name_el is None or u in people:
                continue
            nm = name_el.get_text(strip=True)
            rec = {"name": nm, "url": u, "profile_url": u, "institutes": []}
            zhiwei = a.select_one(".t-zhiwei")
            if zhiwei:
                for p in zhiwei.find_all("p"):
                    txt = p.get_text(" ", strip=True)
                    if "职位" in txt:
                        rec["title"] = txt.split("职位", 1)[-1].strip()
                    elif "邮箱" in txt:
                        rec["email"] = txt.split("邮箱", 1)[-1].strip().replace("_AT_", "@")
                    elif "办公地点" in txt:
                        rec["office_address"] = txt.split("办公地点", 1)[-1].strip()
            people[u] = rec
        if len(cards) < 5:  # 末页
            break
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    out = {}
    text = soup.get_text("\n", strip=True)
    # 内部详情页: 个人简介/研究方向栏目
    m = re.search(r"个人简介\n(.{30,}?)(?:\n(?:研究方向|教育背景|教育经历|招生|代表性)|$)", text, re.S)
    if m:
        out["bio_raw"] = m.group(1).strip()[:5000]
    m = re.search(r"研究方向\n([^\n]{2,200})", text)
    if m:
        out["research_direction_raw"] = m.group(1).strip()[:200]
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if m:
        out["email"] = m.group(0)
    m = re.search(r"(讲席|特聘|长聘|准聘|兼职|客座)?(研究助理教授|研究副教授|教授|副教授|"
                  r"助理教授|研究员|副研究员|助理研究员|讲师)", text[:400])
    if m:
        out["title"] = m.group(0)
    if not out.get("supervisor"):
        # 简介英文头衔旁常注中文导师资格("Associate Professor (研究员，博士生导师)"),
        # 全页紧模式提取——南科大页面已验证无导航误配(dry-run +2)
        from crawler.supervisor_util import extract_supervisor
        sup = extract_supervisor(text)
        if sup:
            out["supervisor"] = sup
    return out

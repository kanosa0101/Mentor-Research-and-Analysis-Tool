"""中国科学院信息工程研究所（iie.cas.cn）。
原名单源为 iie.cas.cn 导师介绍文章（无详情页）; 信工所教师在国科大网安学院
scs.ucas.ac.cn 的研究生导师页有完整名单(283人), 名字链到 people.ucas.ac.cn/~id
统一个人主页（电子邮件/研究领域/单位/通信地址/教育背景, 服务端渲染）。
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch

_SCS = "https://scs.ucas.ac.cn/index.php/zh-cn/szdw/graduateteacher"


def iter_roster(cfg):
    html, meta, _ = fetch.fetch_text("GET", _SCS)
    soup = BeautifulSoup(html, "html.parser")
    people = {}
    for a in soup.select("a[href*='people.ucas.ac.cn/~']"):
        nm = re.sub(r"\s+", "", a.get_text(strip=True))
        href = str(a.get("href") or "")
        if not re.match(r"^[\u4e00-\u9fa5·]{2,4}$", nm) or href in people:
            continue
        people[href] = {"name": nm, "url": href, "profile_url": href,
                        "institutes": []}
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    out = {}
    m = re.search(r"电子邮件[：:]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
    if m:
        out["email"] = m.group(1)
    m = re.search(r"研究领域\n([^\n]{2,200})", text)
    if m:
        out["research_directions"] = [x.strip() for x in re.split(r"[;；]", m.group(1))
                                      if x.strip()][:20]
    m = re.search(r"通信地址[：:]\s*([^\n]{4,60})", text)
    if m:
        out["office_address"] = m.group(1).strip()
    m = re.search(r"\n(研究员|副研究员|助理研究员|教授|副教授|讲师|工程师|高级工程师)\n", text)
    if m:
        out["title"] = m.group(1)
    m = re.search(r"基本信息\n[^\n]+\n[^\n]+\n([^\n]*(?:中国科学院|研究所|大学)[^\n]*)", text)
    if m:
        out["institute_from_detail"] = [m.group(1).strip()[:40]]
        for inst in re.split(r"[与和、]", m.group(1)):
            if inst.strip():
                out["institute_from_detail"] = [inst.strip()]
                break
    return out

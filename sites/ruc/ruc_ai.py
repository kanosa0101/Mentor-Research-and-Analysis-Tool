"""中国人民大学高瓴人工智能学院。
名单来自 simple_list 式抓取(教师系统 /academicfaculty/szdwn/<py>/index.htm),
详情页是自研教师系统: 姓名后紧跟职称, 正文含简介/教育经历/工作经历。
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch
from sites.simple_list import iter_roster  # 名单逻辑一致, 复用

_TITLE_RE = re.compile(
    r"(讲席|特聘|长聘|准聘|兼职|客座|荣誉)?"
    r"(教授|副教授|助理教授|研究员|副研究员|助理研究员|讲师|助教)")


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    out = {}
    head = text[:300]
    m = _TITLE_RE.search(head)
    if m:
        out["title"] = m.group(0)
    m = re.search(r"研究方向[为是]([^。]{4,150})。", text)
    if m:
        out["research_direction_raw"] = m.group(1).strip()[:200]
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if m:
        out["email"] = m.group(0)
    # 简介: 姓名/职称行之后到 教育经历 之间的大段
    m = re.search(r"\n(助理教授|讲师|副教授|教授|研究员)\n(.{50,}?)(?:\n教育经历\n|\n工作经历\n)", text, re.S)
    if m:
        out["bio_raw"] = m.group(2).strip()[:5000]
    return out

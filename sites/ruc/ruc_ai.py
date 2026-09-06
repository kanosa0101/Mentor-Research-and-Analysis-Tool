"""中国人民大学高瓴人工智能学院。
名单来自 simple_list 式抓取(教师系统 /academicfaculty/szdwn/<py>/index.htm),
详情页是自研教师系统: 姓名后紧跟职称, 正文含简介/教育经历/工作经历。
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
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
    if "email" not in out:
        # 联系栏 "邮箱：dou(@)ruc.edu.cn" / "邮箱：yi.zeng (@)ruc.edu.cn"——
        # (@) 混淆正则吃不到, 交给 normalize_email 还原(已支持括号 @)
        m = re.search(r"(?:(?:电子)?邮箱|E\s*-?\s*[Mm]ail)[：:]\s*([^\n]{2,80})", text)
        if m:
            e = normalize_email(m.group(1))
            if e:
                out["email"] = e
    # 简介: 姓名/职称行之后到 教育经历 之间的大段
    m = re.search(r"\n(助理教授|讲师|副教授|教授|研究员)\n(.{50,}?)(?:\n教育经历\n|\n工作经历\n)", text, re.S)
    if m:
        out["bio_raw"] = m.group(2).strip()[:5000]
    if not out.get("supervisor"):
        # bio_raw 段落常截不到联系栏自述("吴玉章讲席教授，博导。"), 全页紧模式
        # 提取——人大 AI 页面已验证无导航误配(dry-run +9)
        from crawler.supervisor_util import extract_supervisor
        sup = extract_supervisor(text)
        if sup:
            out["supervisor"] = sup
    return out

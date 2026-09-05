"""华东师范大学计算机学院。
- 教师名录 jzgml/list.htm: .team ul li 服务端内嵌全部教师(姓名/个人主页/
  职称/办公室/电话/邮箱 + data-name 分类), 直接解析, 无需交互
- 个人主页 faculty.ecnu.edu.cn/.../main.psp: 教育背景/工作经历/个人简介
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch


def iter_roster(cfg):
    people = {}
    meta = None
    for lu in cfg["list"]["urls"]:
        html, meta, _ = fetch.fetch_text("GET", lu)
        soup = BeautifulSoup(html, "html.parser")
        for li in soup.select(".team ul li"):
            a = li.select_one("a[title]") or li.select_one("a[href]")
            if a is None:
                continue
            nm_raw = a.get("title") or a.get_text(strip=True) or ""
            nm = re.sub(r"\s+", "", re.sub(r"[（(][^）)]*[)）]", "", nm_raw))  # 去掉"（兼）"
            href = str(a.get("href") or "")
            # 有个人主页的链 faculty.ecnu.edu.cn, 没有的链 /_redirect 文章页
            if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", nm) \
                    or not (href.startswith("http") or href.startswith("/_redirect")):
                continue
            if href.startswith("/"):
                href = "https://cs.ecnu.edu.cn" + href
            if href in people:
                continue
            rec = {"name": nm, "url": href, "profile_url": href, "institutes": []}
            intro = li.select_one(".intro")
            if intro:
                txt = intro.get_text(" ", strip=True)
            for line in re.split(r"[$\n]", txt):
                line = line.strip()
                low = line.lower()
                if low.startswith("职称"):
                    rec["title"] = line.split("：", 1)[-1].strip() or None
                elif low.startswith(("邮箱", "email")):
                    rec["email"] = line.split("：", 1)[-1].strip() or None
                elif line.startswith("办公室"):
                    rec["office_address"] = line.split("：", 1)[-1].strip() or None
                elif low.startswith(("办公电话", "电话")):
                    rec["phone"] = line.split("：", 1)[-1].strip() or None
            cat = li.get("data-name")
            if cat and "title" not in rec:
                rec["title"] = cat  # 分类名(教授/副教授/专职科研人员)兜底
            people[href] = rec
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    out = {}
    text = soup.get_text("\n", strip=True)
    # 简介: 个人简介标题后的整段
    m = re.search(r"个人简介\n(.{30,}?)(?:\n(教学|科研|获奖|代表性|学生|实验室)|$)", text, re.S)
    if m:
        out["bio_raw"] = m.group(1).strip()[:5000]
    # 研究方向: 常在简介首段"主要研究方向为…"
    m = re.search(r"主要研究方向[为是]([^。]{4,120})。", text)
    if m:
        out["research_direction_raw"] = m.group(1).strip()[:200]
    if "email" not in out:
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        if m:
            out["email"] = m.group(0)
    return out

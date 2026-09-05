import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from crawler import fetch
from sites.wp import parse_wp_detail

# www2.scut.edu.cn/cs/22284/list.htm 师资单页全量(~96人)。锚点 title 属性被官网
# 滥用: 有的是姓名、有的是"院长"、有的是"姓名：X；联系电话：…"字段串——通用
# parse_person_anchors 的 title 优先策略会漏。这里 text/title 双候选取姓名,
# 字段串形态从 "姓名：" 解析。详情页 c22284aNNN/page.htm 标准 WP, 委托 parse_wp_detail。
_NAME = re.compile(r"^[\u4e00-\u9fa5·]{2,5}$")
# 锚文字可能是职务("院长/副院长/系主任"), 不是人名
_ROLE = re.compile(r"院长|主任|书记|教授|副教授|讲师|研究员|处长|馆长")


def _name_of(a):
    text = re.sub(r"\s+", "", a.get_text(strip=True))
    title = re.sub(r"\s+", "", a.get("title") or "")
    for cand in (text, title):
        if _NAME.match(cand) and not _ROLE.search(cand):
            return cand
    for cand in (title, text):
        m = re.match(r"^姓\s*名\s*[:：]\s*([\u4e00-\u9fa5·]{2,5})", cand)
        if m:
            return m.group(1)
    return None


def iter_roster(cfg):
    people = {}
    meta = None
    for ch in cfg["list"]["channels"]:
        for n in range(1, 30):
            page_url = ch["url"] if n == 1 else re.sub(r"list\.htm$", f"list{n}.htm", ch["url"])
            try:
                text, meta, _ = fetch.fetch_text("GET", page_url)
            except Exception:
                break
            soup = BeautifulSoup(text or "", "html.parser")
            fresh = 0
            for a in soup.select("a[href]"):
                if not re.search(r"c2228[456]a\d+/page\.htm", a.get("href", "")):
                    continue
                nm = _name_of(a)
                if not nm or nm in people:
                    continue
                href = urljoin(page_url, a["href"])
                rec = {"name": nm, "url": href, "profile_url": href,
                       "institutes": []}
                # 栏目名即职称(教授/副教授/讲师), 详情页再精化
                if ch.get("cat"):
                    rec["list_title"] = ch["cat"]
                people[nm] = rec
                fresh += 1
            if fresh == 0:
                break
    return list(people.values()), meta


_BREADCRUMB_TITLE = re.compile(
    r"师资队伍\s*>\s*(讲席教授|特聘教授|副教授|教授|讲师|助理教授|研究员|副研究员)")


def parse_detail(cfg, html, url):
    out = parse_wp_detail(cfg, html, url)
    # 正文只有介绍图片的页面无职称字段, 面包屑"师资队伍 > 教授"是官网自分类
    if "title" not in out:
        m = _BREADCRUMB_TITLE.search(html)
        if m:
            out["title"] = m.group(1)
    return out

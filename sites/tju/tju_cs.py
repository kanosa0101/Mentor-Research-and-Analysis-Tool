import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from crawler import fetch
from sites.wp import parse_wp_detail

# cs.tju.edu.cn/faculty/jzgml 是 VSB 三级跳转(jzgml.htm → azc.htm → azc/zgj.htm)，
# 落地后真实列表在 azc/<职称组>/<N>.htm 翻页。链接文字直接带
# "冯伟教授邮箱：wfeng@tju.edu.cn"——姓名/职称/邮箱名录级就齐，详情页(cic.tju 域)再富化。
_TITLE_RE = re.compile(
    r"^(?P<name>[\u4e00-\u9fa5·]{2,5}?)"
    r"(?P<til>教授|副教授|研究员|副研究员|助理教授|讲师|高级实验师|高级工程师|实验师|工程师)?"
    r"(?:\s*邮箱\s*[:：]\s*(?P<email>[\w.+-]+@[\w.-]+\.\w+))?"
    r"(?:研究领域[:：].*)?$")
_SUP_RE = re.compile(r"导师类型\s*[:：]\s*([^\n<]{0,20})")
_SUP_MAP = {"博": "博导", "硕": "硕导"}


def iter_roster(cfg):
    people = {}
    meta = None
    for ch in cfg["list"]["channels"]:
        # azc 栏目翻页 zgj.htm → zgj/1.htm..N.htm（落地页是跳转壳）；
        # yjsdsml 等单页名录 /1.htm 不存在时回退原始 URL
        base = re.sub(r"\.htm$", "", ch["url"].rstrip("/"))
        for n in range(1, 30):
            page_url = f"{base}/{n}.htm"
            try:
                text, meta, _ = fetch.fetch_text("GET", page_url)
            except Exception:
                if n == 1:
                    try:
                        text, meta, _ = fetch.fetch_text("GET", ch["url"])
                    except Exception:
                        break
                else:
                    break
            fresh = _collect(page_url, text, people)
            if fresh == 0:
                break
    return list(people.values()), meta


def _collect(page_url, text, people):
    soup = BeautifulSoup(text, "html.parser")
    fresh = 0
    for a in soup.select("a[href*='/info/']"):
        raw = re.sub(r"\s+", "", a.get_text(strip=True))
        m = _TITLE_RE.match(raw)
        if not m:
            continue
        name = m.group("name")
        if name not in people:
            href = urljoin(page_url, a["href"])
            rec = {"name": name, "url": href, "profile_url": href,
                   "institutes": []}
            if m.group("til"):
                rec["title"] = m.group("til")
            if m.group("email"):
                rec["email"] = m.group("email")
            people[name] = rec
            fresh += 1
    return fresh


def parse_detail(cfg, html, url):
    out = parse_wp_detail(cfg, html, url)
    if not out.get("supervisor"):
        m = _SUP_RE.search(html)
        if m:
            sup = [v for k, v in _SUP_MAP.items() if k in m.group(1)]
            if sup:
                out["supervisor"] = "、".join(sup)
    return out

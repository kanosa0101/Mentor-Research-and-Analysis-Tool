import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from crawler import fetch
from crawler.email_util import normalize_email
from sites.wp import parse_wp_detail

# cs.bit.edu.cn 名录(bssds 博导/sssds 硕导)列表是 JS 注入, 需渲染; 条目是
# 32位哈希 .htm 链接。详情页字段卡片在 div.summary(逐行"职称：/E-mail："),
# 简介在 .article, 都不是标准 vsb_content——parse_wp_detail 返回空, 本钩子自理。
_HASH_HREF = re.compile(r"[0-9a-f]{32}\.htm$")
_LINE_LABEL = re.compile(
    r"^(职\s*称|电\s*话|联系电话|E\s*-\s*mail|电子邮件|邮箱|通信地址|办公地址|个人主页)\s*[:：]\s*(.*)$", re.I)
_SUP_RE = re.compile(r"(博导|博士生导师|硕导|硕士生导师)")


def iter_roster(cfg):
    people = {}
    meta = None
    for ch in cfg["list"]["channels"]:
        text, meta, _ = fetch.fetch_rendered(ch["url"], wait_ms=6000, scroll=True)
        soup = BeautifulSoup(text or "", "html.parser")
        for a in soup.select("a[href]"):
            if not _HASH_HREF.fullmatch(a["href"].rsplit("/", 1)[-1]):
                continue
            name = re.sub(r"\s+", "", a.get_text(strip=True))
            if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name) or name in people:
                continue
            href = urljoin(ch["url"], a["href"])
            people[name] = {
                "name": name, "url": href, "profile_url": href,
                "institutes": [], "supervisor": ch["cat"],
            }
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    sm = soup.select_one(".summary")
    if sm is not None:
        for line in sm.get_text("\n", strip=True).split("\n"):
            m = _LINE_LABEL.match(line.strip())
            if not m:
                continue
            label, v = m.group(1), m.group(2).strip()
            if "称" in label:
                out.setdefault("title", v)
            elif "mail" in label.lower() or "邮箱" in label:
                e = normalize_email(v)
                if e:
                    out.setdefault("email", e)
            elif "电话" in label:
                out.setdefault("phone", v)
            elif "地址" in label:
                out.setdefault("office_address", v)
    art = soup.select_one(".article")
    if art is not None and len(art.get_text(strip=True)) > 60:
        out.setdefault("bio_raw", art.get_text("\n", strip=True))
        m = _SUP_RE.search(art.get_text()[:120])
        if m:
            sup = sorted({("博导" if "博" in s else "硕导") for s in m.groups() if s})
            if sup:
                out.setdefault("supervisor", "、".join(sup))
    return out

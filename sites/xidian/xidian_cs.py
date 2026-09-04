import re

from bs4 import BeautifulSoup

from crawler import fetch
from sites.wp import parse_wp_detail


def iter_roster(cfg):
    people = {}
    meta = None
    for lu in cfg["list"]["urls"]:
        text, meta, _ = fetch.fetch_text("GET", lu)
        soup = BeautifulSoup(text, "html.parser")
        pattern = re.compile(cfg["list"]["person_href"])
        for a in soup.select("a[href]"):
            nm = re.sub(r"\s+", "", str(a.get("title") or a.get_text(strip=True) or ""))
            if not re.match(r"^[\u4e00-\u9fa5·]{2,4}$", nm):
                continue
            href = str(a.get("href") or "")
            if href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http"):
                continue
            if not pattern.search(href):
                continue
            people.setdefault(nm, {"name": nm, "url": href, "profile_url": href,
                                   "institutes": []})
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
    out = {}
    head = "\n".join(lines[:40])
    sup = [s for s in ("博士生导师", "硕士生导师") if s in head]
    if sup:
        out["supervisor"] = "、".join(["博导" if "博士" in s else "硕导" for s in sup])
    m = re.search(r"(讲席|特聘|长聘教轨|长聘|副)?(教授|研究员|副教授|副研究员|助理教授|讲师)", head)
    if m:
        out["title"] = m.group(0)
    for i, l in enumerate(lines):
        if l.startswith("所在单位"):
            v = l.split("：", 1)[-1].strip()
            if v and "：" in l:
                out["institute_from_detail"] = [v]
        if l.startswith("研究方向") and i + 1 < len(lines):
            out["research_direction_raw"] = lines[i + 1][:200]
    out["bio_raw"] = "\n".join(lines[:80]) or None
    return out

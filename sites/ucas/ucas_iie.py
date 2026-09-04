import re

from bs4 import BeautifulSoup

from crawler import fetch


def iter_roster(cfg):
    text, meta, _ = fetch.fetch_text("GET", cfg["list"]["url"])
    soup = BeautifulSoup(text, "html.parser")
    box = soup.select_one(".v_news_content") or soup.select_one(".TRS_UEDITOR") \
        or soup.select_one("#vsb_content")
    if box is None:
        raise ValueError("article content not found")
    people = {}
    section = None
    for p in box.select("p"):
        line = p.get_text(strip=True)
        if not line:
            continue
        clean = re.sub(r"[\s\d.、]+$", "", line)
        if clean.endswith(("研究室", "实验室", "研究中心", "研究部")) and "：" not in clean:
            section = clean
            continue
        m = re.match(r"(博士生导师|硕士生导师|博导|硕导)[:：]\s*(.*)", line)
        if not m:
            continue
        role = "博导" if "博" in m.group(1) else "硕导"
        names = [n.strip() for n in re.split(r"[、，,;；/\s]+", m.group(2)) if n.strip()]
        for name in names:
            if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name):
                continue
            rec = people.setdefault(name, {
                "name": name,
                "url": cfg["list"]["url"],
                "profile_url": cfg["list"]["url"],
                "institutes": [],
            })
            if section and section not in rec["institutes"]:
                rec["institutes"].append(section)
            if role not in (rec.get("supervisor") or ""):
                rec["supervisor"] = "、".join([role] if not rec.get("supervisor")
                                              else [rec["supervisor"], role])
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    return {}

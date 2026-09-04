import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch
from sites.wp import parse_wp_detail


def iter_roster(cfg):
    people = {}
    meta = None
    for lu in cfg["list"]["urls"]:
        text, meta, _ = fetch.fetch_text("GET", lu)
        for rec in _collect(cfg, lu, text):
            people.setdefault(rec["name"], rec)
    return list(people.values()), meta


def _collect(cfg, page_url, text):
    pattern = re.compile(cfg["list"]["person_href"])
    soup = BeautifulSoup(text, "html.parser")
    out = {}
    for a in soup.select("a[href]"):
        nm = re.sub(r"\s+", "", a.get("title") or a.get_text(strip=True) or "")
        nm = re.sub(r"[（(][^)）]*[)）]", "", nm)
        if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", nm):
            continue
        href = urljoin(page_url, a["href"])
        if not pattern.search(href):
            continue
        if re.search(r"(index|main|list)\.htm", href):
            continue
        rec = {"name": nm, "url": href, "profile_url": href, "institutes": []}
        sup = [s for s in ("博导", "硕导") if s in (a.get("title") or "")]
        if sup:
            rec["supervisor"] = "、".join(sup)
        out.setdefault((nm, href), rec)
    return list(out.values())


def parse_detail(cfg, html, url):
    return parse_wp_detail(cfg, html, url)

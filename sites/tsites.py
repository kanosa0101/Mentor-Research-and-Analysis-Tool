import re

from bs4 import BeautifulSoup

from crawler import fetch


def iter_roster(cfg):
    people = {}
    meta = None
    urls = list(cfg["list"].get("urls") or [])
    tpl = cfg["list"].get("page_url_template")
    if tpl:
        urls += [tpl.format(n=n) for n in range(1, cfg["list"].get("pages", 1) + 1)]
    pattern = re.compile(cfg["list"]["person_href"])
    for lu in urls:
        html, meta, _ = fetch.fetch_rendered(
            lu, wait_ms=cfg["list"].get("wait_ms", 3000),
            scroll=cfg["list"].get("scroll", True))
        soup = BeautifulSoup(html, "html.parser")
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
            key = (nm, re.sub(r"\d+", "N", href))
            if key not in people:
                people[key] = {"name": nm, "url": href, "profile_url": href,
                               "institutes": []}
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    return {}

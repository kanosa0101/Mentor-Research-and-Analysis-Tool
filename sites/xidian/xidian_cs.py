import re

from bs4 import BeautifulSoup

from crawler import fetch
from sites import tsites


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
    # 西电教师主页与中南同为 tsites 系统，字段解析（含邮箱解密）直接复用 tsites 钩子
    return tsites.parse_detail(cfg, html, url)

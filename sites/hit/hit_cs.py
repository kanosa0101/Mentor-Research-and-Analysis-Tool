import re

from bs4 import BeautifulSoup

from crawler import fetch


def iter_roster(cfg):
    url = cfg["list"]["url"]
    html, meta, _ = fetch.fetch_rendered(url)
    soup = BeautifulSoup(html, "html.parser")
    people = {}
    for tbody in soup.select("tbody"):
        lines = [l.strip().replace("\xa0", "").replace("\t", "")
                 for l in tbody.get_text("\n", strip=True).split("\n")]
        lines = [l for l in lines if l]
        if not lines:
            continue
        section = None
        if re.search(r"(研究中心|研究所|实验室|实验中心|中心|系|学院)$", lines[0]):
            section = lines[0]
        if not section:
            continue
        for l in lines[1:]:
            name = re.sub(r"\d+$", "", l)
            if not re.match(r"^[\u4e00-\u9fa5·]{2,4}$", name):
                continue
            rec = {"name": name, "url": url, "profile_url": url,
                   "institutes": [section]}
            key = (name, url)
            if key in people:
                if section not in people[key]["institutes"]:
                    people[key]["institutes"].append(section)
            else:
                people[key] = rec
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    return {}

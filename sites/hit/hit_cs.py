import re

from bs4 import BeautifulSoup

from crawler import fetch

# 博导/硕导名单页(Word 导出表格, 姓名链 homepage 内网穿透地址——外网不可达,
# 详情无源; 但名单本身能给 roster 级补 supervisor)。渲染需 CDP。
_SUP_PAGES = [("博导", "https://cs.hit.edu.cn/22195/list.htm"),
              ("硕导", "https://cs.hit.edu.cn/22196/list.htm")]


def _supervisor_map():
    sup = {}
    for kind, u in _SUP_PAGES:
        try:
            html, _, _ = fetch.fetch_cdp(u, wait_ms=4000, scroll=True)
        except Exception:
            continue
        for nm in re.findall(
                r'<a href="[^"]*(?:ivpn|homepage)[^"]*"[^>]*>'
                r'(?:<span[^>]*>)?([\u4e00-\u9fa5·]{2,4})', html):
            sup.setdefault(nm, [])
            if kind not in sup[nm]:
                sup[nm].append(kind)
    return sup


def iter_roster(cfg):
    url = cfg["list"]["url"]
    html, meta, _ = fetch.fetch_cdp(url, wait_ms=4000, scroll=True)
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
    sup = _supervisor_map()
    for rec in people.values():
        kinds = sup.get(rec["name"])
        if kinds:
            rec["supervisor"] = "、".join(kinds)
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    return {}

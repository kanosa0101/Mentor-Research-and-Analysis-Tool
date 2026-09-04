import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch

UCAS_PEOPLE = "people.ucas.ac.cn"


def iter_roster(cfg):
    people = {}
    text, meta, _ = fetch.fetch_text("GET", cfg["list"]["url"])
    seen = {cfg["list"]["url"]}
    queue = [cfg["list"]["url"]]
    while queue:
        u = queue.pop(0)
        r_text, _, _ = fetch.fetch_text("GET", u)
        for rec in _parse_tables(u, r_text, cfg):
            key = (rec["name"], rec.get("email") or "")
            if key in people:
                _merge(people[key], rec)
            else:
                people[key] = rec
        soup = BeautifulSoup(r_text, "html.parser")
        for a in soup.select("a[href]"):
            href = urljoin(u, a["href"])
            if re.search(r"index(_\d+)?\.html$", href) and href not in seen \
                    and href.startswith(cfg["list"]["url"]):
                seen.add(href)
                queue.append(href)
    return list(people.values()), meta


def _parse_tables(page_url, text, cfg):
    soup = BeautifulSoup(text, "html.parser")
    out = []
    for table in soup.select("table"):
        for tr in table.select("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.select("td")]
            if len(cells) < 5:
                continue
            name, cat, subject, direction, email = (c.strip() for c in cells[:5])
            if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name):
                continue
            a = tr.select_one("a[href]")
            detail = cfg["list"]["url"]
            if a:
                href = urljoin(page_url, a["href"])
                if UCAS_PEOPLE in href:
                    detail = href
            out.append({
                "name": name,
                "url": detail,
                "profile_url": detail if UCAS_PEOPLE in detail else cfg["base_url"] + "/yjsjy/dsxx/",
                "supervisor": cat or None,
                "subjects": subject or None,
                "research_direction_raw": direction or None,
                "email": email or None,
            })
    return out


def _merge(old, new):
    for k in ("supervisor", "subjects", "research_direction_raw", "email"):
        v = new.get(k)
        if v and v not in (old.get(k) or ""):
            old[k] = "、".join(x for x in [old.get(k), v] if x)
    if UCAS_PEOPLE in new["url"]:
        old["url"] = new["url"]
        old["profile_url"] = new["profile_url"]


def parse_detail(cfg, html, url):
    from crawler.email_util import normalize_email

    if UCAS_PEOPLE not in url:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    if body is None:
        return {}
    lines = [l.strip() for l in body.get_text("\n", strip=True).split("\n") if l.strip()]
    out = {}
    for idx, l in enumerate(lines[:15]):
        if m := re.match(r"电子邮件[:：]\s*(.*)", l):
            e = normalize_email(m.group(1))
            if not e and idx + 1 < len(lines):
                e = normalize_email(m.group(1) + " " + lines[idx + 1])
            if e:
                out["email"] = e
    sup = []
    for l in lines[:10]:
        if "博导" in l or "博士生导师" in l:
            sup.append("博导")
        if "硕导" in l or "硕士生导师" in l:
            sup.append("硕导")
    if sup:
        out["supervisor"] = "、".join(dict.fromkeys(sup))
    rd = []
    mode = None
    for l in lines:
        if l in ("招生专业", "招生方向"):
            mode = l
            continue
        if l in ("教育背景", "工作经历", "专利与奖励", "出版信息", "科研活动", "指导学生"):
            mode = None
            continue
        if mode and l:
            rd.append(l)
    if rd:
        out["research_directions"] = rd
    out["bio_raw"] = "\n".join(lines) or None
    out["institute_from_detail"] = []
    return out

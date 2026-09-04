import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
from sites.wp import parse_wp_detail

CARD_LABELS = ("职称", "研究所", "研究领域", "办公电话", "电子邮件")


def iter_roster(cfg):
    people = {}
    meta = None
    queue = []
    queued = set()
    for lu in cfg["list"]["urls"]:
        text, meta, _ = fetch.fetch_text("GET", lu)
        for u in _channel_all_pages(lu, text, queued):
            queue.append(u)
    while queue:
        u = queue.pop(0)
        try:
            text, meta, _ = fetch.fetch_text("GET", u)
        except Exception:
            continue
        for u2 in _channel_all_pages(u, text, queued):
            queue.append(u2)
        for rec in _parse_cards(u, text):
            if rec["name"] not in people:
                people[rec["name"]] = rec
    return list(people.values()), meta


def _channel_all_pages(page_url, text, queued):
    found = []
    if "ALL" not in page_url:
        for m in re.finditer(r'href="([^"]*amz/ALL\.htm)"', text):
            u = urljoin(page_url, m.group(1))
            if u not in queued:
                queued.add(u)
                found.append(u)
        return found
    for m in re.finditer(r'href="([^"]+)"', text):
        h = m.group(1)
        if re.match(r"^(?:[\w-]+/)?\d+\.htm$", h) or re.search(r"/ALL/\d+\.htm$", h):
            u = urljoin(page_url, h)
            if u not in queued:
                queued.add(u)
                found.append(u)
    return found


def _parse_cards(page_url, text):
    soup = BeautifulSoup(text, "html.parser")
    out = []
    for a in soup.select("a.a[href*='info/']"):
        txt = a.get_text(" ", strip=True)
        name = re.split(r"职称", txt)[0].strip()
        name = re.sub(r"\s+", "", name)
        if not re.match(r"^[\u4e00-\u9fa5·A-Za-z\s]{2,25}$", name):
            continue
        href = urljoin(page_url, a["href"])
        rec = {"name": name, "url": href, "profile_url": href, "institutes": []}
        segs = re.split(r"(职称|研究所|研究领域|办公电话|电子邮件)[：:]", txt)
        fields = {}
        for i in range(1, len(segs) - 1, 2):
            fields[segs[i]] = segs[i + 1].strip()
        if "研究所" in fields:
            rec["institutes"] = [fields["研究所"]]
        if "研究领域" in fields:
            rec["research_direction_raw"] = fields["研究领域"]
        if "办公电话" in fields:
            rec["phone"] = fields["办公电话"]
        if "电子邮件" in fields:
            rec["email"] = fields["电子邮件"]
        tm = fields.get("职称")
        if tm:
            rec["title"] = tm
            sup = [s for s in ("博导", "硕导") if s in tm]
            if sup:
                rec["supervisor"] = "、".join(sup)
        em = rec.get("email")
        if em:
            e = normalize_email(em)
            if not e and " " in em:
                parts = em.split()
                if len(parts) == 2 and "." in parts[1]:
                    e = normalize_email(parts[0] + "@" + parts[1])
            if e:
                rec["email"] = e
            else:
                rec.pop("email", None)
        out.append(rec)
    return out


def parse_detail(cfg, html, url):
    return parse_wp_detail(cfg, html, url)

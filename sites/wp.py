import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch

PERSON_PAGE = re.compile(r"/c\d+a\d+/page\.htm$")


def iter_roster(cfg):
    return walk_channels(cfg, cfg["list"]["channels"])


def walk_channels(cfg, channels):
    people = {}
    meta = None
    for ch in channels:
        url, cat = ch["url"], ch.get("cat")
        n = 0
        while n < 40:
            page_url = url if n == 0 else re.sub(r"list\.htm$", f"list{n+1}.htm", url)
            try:
                text, meta, _ = fetch.fetch_text("GET", page_url)
            except Exception:
                break
            if n > 0 and "没有找到" in text and len(text) < 3000:
                break
            for rec in parse_person_anchors(cfg, page_url, text):
                if cat:
                    rec["title"] = cat
                key = rec["name"]
                if key not in people:
                    people[key] = rec
            n += 1
            if not _has_next(text, page_url, n + 1):
                break
    return list(people.values()), meta


def _has_next(text, page_url, next_n):
    return f"list{next_n}.htm" in text


def parse_person_anchors(cfg, page_url, text):
    pattern = re.compile(cfg["list"].get("person_href") or r"/c\d+a\d+/page\.htm$")
    soup = BeautifulSoup(text, "html.parser")
    out = {}
    for a in soup.select("a[href]"):
        href = urljoin(page_url, a["href"])
        if not pattern.search(href):
            continue
        raw = re.sub(r"\s+", "", a.get("title") or a.get_text(strip=True) or "")
        name = re.sub(r"[（(][^)）]*[)）]", "", raw)
        if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name):
            continue
        rec = {"name": name, "url": href, "profile_url": href, "institutes": []}
        sup = [s for s in ("博导", "硕导") if s in raw]
        if sup:
            rec["supervisor"] = "、".join(sup)
        out.setdefault((name, href), rec)
    return list(out.values())


def parse_detail(cfg, html, url):
    return parse_wp_detail(cfg, html, url)


def parse_wp_detail(cfg, html, url):
    from crawler.email_util import normalize_email

    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one(".v_news_content") or soup.select_one("#vsb_content") \
        or soup.select_one(".wp_articlecontent")
    if box is None:
        return {}
    lines = [l.strip() for l in box.get_text("\n", strip=True).split("\n") if l.strip()]
    out = {}
    LABEL = r"(姓\s*名|职\s*称|电\s*话|邮\s*箱|电子邮件|E-?Mail|个人主页|主\s*页|领域|研究方向|联系邮箱)"
    label_re = re.compile(
        LABEL + r"\s*[:：]\s*([^\n，。；]{0,120})(?=\s*" + LABEL + r"\s*[:：]|$)", re.I)

    def handle(label, value, rest=()):
        k = re.sub(r"\s+", "", label).lower()
        v = value.strip()
        nxt = rest[0] if rest else ""
        if not v and not nxt:
            return
        if "姓" in k:
            out.setdefault("name", v or nxt)
        elif "职" in k and "称" in k:
            # 内联标签会把词拆碎成多行（"职称：/副/教授、博士生导师"）, 逐行拼回
            t = v
            for extra in rest:
                if re.search(r"教授|研究员|讲师|助教|工程师|实验师|馆员|院士", t):
                    break
                if re.match(LABEL, extra):
                    break
                t += extra
            out.setdefault("title", t)
            sup = [s for s in ("博导", "硕导") if s in t]
            if sup:
                out.setdefault("supervisor", "、".join(sup))
        elif "话" in k:
            out.setdefault("phone", v or nxt)
        elif "主页" in k:
            src = v or nxt
            a = re.search(r"https?://[^\s，。；]+", src) \
                or re.search(r"[\w.-]+\.(?:edu\.cn|com|cn|org|net)[^\s，。；]*", src)
            if a:
                h = a.group(0)
                out.setdefault("homepage", h if h.startswith("http") else "https://" + h)
        elif "领域" in k or "方向" in k:
            out.setdefault("research_direction_raw", v or nxt)
        else:
            e = normalize_email(v)
            if not e:
                e = normalize_email(v + " " + " ".join(rest))
            if not e:
                for tok in re.split(r"\s+", v):
                    e = normalize_email(tok)
                    if e:
                        break
            if e:
                out.setdefault("email", e)

    for i, line in enumerate(lines):
        for m in label_re.finditer(line):
            handle(m.group(1), m.group(2), lines[i + 1:i + 4])

    if "email" not in out:
        for a in box.select('a[href^="mailto:"]'):
            from crawler.email_util import normalize_email
            e = normalize_email(a["href"][7:])
            if e:
                out["email"] = e
                break
    if "email" not in out:
        flat = box.get_text("", strip=True)
        for m in re.finditer(r"[@＃]|[(（{\[]\s*at\s*[)）\]}]", flat, re.I):
            lo, hi = max(0, m.start() - 30), min(len(flat), m.start() + 41)
            e = normalize_email(flat[lo:hi])
            if e:
                out["email"] = e
                break
    out["bio_raw"] = "\n".join(lines) or None
    if "title" not in out and out.get("bio_raw"):
        head = " ".join(lines[:2])
        m = re.search(r"(长聘教轨|讲席|特聘|副)?(助理教授|副教授|教授|研究员|讲师)", head)
        if m:
            out["title"] = m.group(0)
            sup = [s for s in ("博导", "硕导") if s in head]
            if sup:
                out.setdefault("supervisor", "、".join(sup))
    return out

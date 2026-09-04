import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch


def walk_and_collect(cfg, list_urls):
    people = {}
    meta = None
    for list_url in list_urls:
        text, meta, _ = fetch.fetch_text("GET", list_url)
        for page_url, page_text in _walk_pagination(list_url, text):
            for rec in _parse_items(cfg, page_url, page_text):
                key = rec["name"]
                if key not in people or _url_date(rec["url"]) > _url_date(people[key]["url"]):
                    people[key] = rec
    return list(people.values()), meta


def _url_date(url):
    m = re.search(r"t20(\d{6})[_\d]*\.html", url)
    return m.group(1) if m else ""


def _walk_pagination(first_url, first_text):
    out = [(first_url, first_text)]
    seen = {first_url}
    n = 1
    while n <= 30:
        nxt = re.sub(r"index(?:_\d+)?\.html$", f"index_{n}.html", first_url)
        if nxt == first_url:
            nxt = first_url.rstrip("/") + f"/index_{n}.html"
        if nxt in seen:
            break
        try:
            text, _, _ = fetch.fetch_text("GET", nxt)
        except Exception:
            break
        seen.add(nxt)
        out.append((nxt, text))
        n += 1
    return out


def _parse_items(cfg, page_url, text):
    pattern = re.compile(cfg["list"]["person_href"])
    found = {}

    def add(name, href):
        rec = _try_add(name, href)
        return rec

    def _try_add(name, href):
        if not name or not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name.strip()):
            return None
        href = urljoin(page_url, href)
        if not pattern.search(href):
            return None
        return found.setdefault((name.strip(), href), {
            "name": name.strip(), "url": href, "profile_url": href, "institutes": []})

    soup = BeautifulSoup(text, "html.parser")
    for a in soup.select("a[href]"):
        rec = _try_add(a.get("title") or a.get_text(strip=True), a["href"])
        if rec is not None and not rec.get("photo_url"):
            holder = a.find_parent("li") or a
            img = holder.select_one("img[src]") if holder is not None else None
            if img is not None and img.get("src"):
                rec["photo_url"] = urljoin(page_url, img["src"])
    for tag in re.findall(r"<a\b[^>]*>", text):
        h = re.search(r'href="([^"]+)"', tag)
        t = re.search(r'title="([^"]+)"', tag)
        if h and t:
            _try_add(t.group(1), h.group(1))
    return list(found.values())


def parse_generic_detail(cfg, html, url):
    
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one(".gunius-detail") or soup.select_one(".v_news_content") \
        or soup.select_one("#vsb_content")
    if box is None:
        return {}
    raw_lines = [l.strip() for l in box.get_text("\n", strip=True).split("\n") if l.strip()]
    lines = [l.replace("\u3000", "").replace(" ", "") for l in raw_lines]
    out = {}
    insts = []

    def value_after(prefix, i):
        if lines[i].startswith(prefix) and len(lines[i]) > len(prefix):
            rest = lines[i][len(prefix):]
            if rest.startswith(":"):
                rest = rest[1:].strip()
            if rest:
                return rest
            if i + 1 < len(lines):
                return lines[i + 1]
        if lines[i] == prefix.rstrip(":") and i + 1 < len(lines):
            return lines[i + 1]
        return None

    for i, l in enumerate(lines):
        for prefix, key, is_inst in (("职称:", "title", False), ("电子邮件:", "email", False),
                                     ("部门/实验室:", None, True),
                                     ("主页:", "homepage", False),
                                     ("个人主页:", "homepage", False)):
            if l.startswith(prefix) or l == prefix.rstrip(":"):
                v = value_after(prefix, i)
                if v:
                    if is_inst:
                        insts.append(v)
                    elif key == "email":
                        from crawler.email_util import normalize_email
                        e = normalize_email(v)
                        if not e and i + 1 < len(lines):
                            e = normalize_email(v + " " + lines[i + 1])
                        if e:
                            out[key] = e
                    elif key == "homepage":
                        m = re.search(r"https?://[^\s，。；]+", v)
                        if m:
                            out[key] = m.group(0)
                    else:
                        out[key] = v
    if insts:
        out["institute_from_detail"] = insts
    out["bio_raw"] = "\n".join(raw_lines) or None
    return out

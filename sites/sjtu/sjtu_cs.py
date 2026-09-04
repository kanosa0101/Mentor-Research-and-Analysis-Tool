import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch

DETAIL_RE = re.compile(r"/jiaoshiml/[A-Za-z0-9\-]+\.html$")


def iter_roster(cfg):
    lst = cfg["list"]
    text, meta, _ = fetch.fetch_text(lst["method"], lst["url"], lst["params"])
    d = _extract_json(text)
    soup = BeautifulSoup(d["content"], "html.parser")
    found = {}
    for item in soup.select(".rc-item"):
        head = item.select_one(".name")
        inst = head.get_text(strip=True) if head else ""
        for a in item.select('a[href]'):
            href = urljoin(cfg["base_url"], a["href"])
            if not DETAIL_RE.search(href):
                continue
            name = a.get_text(strip=True)
            if not name:
                continue
            rec = found.setdefault(href, {"name": name, "url": href, "institutes": [],
                                          "profile_url": href})
            if inst and inst not in rec["institutes"]:
                rec["institutes"].append(inst)
    return list(found.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    info = soup.select_one(".js-info")
    if info is None:
        raise ValueError("js-info block not found")
    name_el = info.select_one(".name")
    title_el = info.select_one(".zw")
    out = {"name": name_el.get_text(strip=True) if name_el else None,
           "title": title_el.get_text(strip=True) if title_el else None}
    img = info.select_one(".imgk img")
    if img and img.get("src"):
        out["photo_url"] = urljoin(cfg["base_url"], img["src"])
    known = {"email": [], "institutes": [], "homepage": None, "unknown": []}
    for p in info.select(".dt p"):
        label, _, value = p.get_text(" ", strip=True).partition("：")
        value = value.strip()
        if not value:
            continue
        if label == "邮箱":
            known["email"].append(value)
        elif label == "所在研究所":
            known["institutes"].append(value)
        elif "主页" in label:
            a = p.select_one("a[href]")
            known["homepage"] = a["href"] if a else value
        elif label == "电话":
            known.setdefault("phone", []).append(value)
        elif label in ("地址", "办公地址"):
            known.setdefault("office_address", []).append(value)
        else:
            known["unknown"].append(f"{label}：{value}")
    out["email"] = "；".join(known["email"]) if known["email"] else None
    out["institute_from_detail"] = known["institutes"]
    out["homepage"] = known["homepage"]
    if known.get("phone"):
        out["phone"] = "；".join(known["phone"])
    if known.get("office_address"):
        out["office_address"] = "；".join(known["office_address"])
    out["unknown_fields"] = known["unknown"]
    extra = soup.select_one(".js-dt")
    if extra is not None:
        bio = extra.get_text("\n", strip=True)
        if bio:
            out["bio_raw"] = bio
    return out


def _extract_json(text):
    import json

    start = text.find("{")
    if start < 0:
        raise ValueError("no json in response")
    return json.loads(text[start:])

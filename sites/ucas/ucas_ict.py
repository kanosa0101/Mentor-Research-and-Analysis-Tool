import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler.email_util import normalize_email

from sites.ucas import cas_lists


def iter_roster(cfg):
    return cas_lists.walk_and_collect(cfg, cfg["list"]["urls"])


def parse_detail(cfg, html, url):
    vals = {}
    for m in re.finditer(r'var\s+(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"', html):
        k, v = m.group(1), m.group(2)
        try:
            vals[k] = json.loads('"' + v + '"')
        except Exception:
            vals[k] = v
    if not vals:
        return {}
    out = {}
    if vals.get("xm"):
        out["name"] = vals["xm"].strip()
    if vals.get("zc"):
        out["title"] = vals["zc"].strip()
    if vals.get("dzyj"):
        e = normalize_email(vals["dzyj"])
        if e:
            out["email"] = e
    q = vals.get("qtbz") or ""
    sup = [s for s in ("博导", "硕导") if s in q]
    if sup:
        out["supervisor"] = "、".join(sup)
    direction = re.sub(r"博士生导师|硕士生导师|博导|硕导", "", q).strip()
    if direction:
        out["research_directions"] = [direction]
    jl = vals.get("jl") or ""
    if jl:
        jtxt = BeautifulSoup(jl, "html.parser").get_text("\n", strip=True)
        if jtxt:
            out["bio_raw"] = jtxt
    pp = re.search(r'var\s+photoPath\s*=\s*"([^"]*)"', html)
    if pp and pp.group(1):
        out["photo_url"] = urljoin(url, pp.group(1))
    out["institute_from_detail"] = []
    return out

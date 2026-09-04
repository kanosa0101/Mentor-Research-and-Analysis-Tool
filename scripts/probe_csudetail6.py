"""抽查无邮箱/无职称的中南页面：密文 span 有没有、职称区有没有。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from bs4 import BeautifulSoup

from crawler import fetch

fetch.set_direct(True)
ROOT = Path(__file__).resolve().parent.parent

no_email, no_title = [], []
for f in sorted((ROOT / "data" / "professors" / "csu" / "cs").glob("*.yaml")):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    if not d.get("email"):
        no_email.append((d["slug"], d["detail_url"]))
    if not d.get("title"):
        no_title.append((d["slug"], d["detail_url"]))

print("no-email:", len(no_email), "no-title:", len(no_title))
for slug, url in no_email[:6]:
    html, m, _ = fetch.fetch_text("GET", url)
    soup = BeautifulSoup(html, "html.parser")
    spans = soup.select("span[_tsites_encrypt_field]")
    labels = []
    for s in spans:
        p = s.find_parent(["li", "p", "div"])
        labels.append(p.get_text(" ", strip=True)[:20] if p else "?")
    print(f"  [{slug}] spans={len(spans)} labels={labels}")

print("--- no title ---")
for slug, url in no_title[:6]:
    html, m, _ = fetch.fetch_text("GET", url)
    head = re.search(r"职称[：:]\s*([一-龥]{2,8})", html)
    soup = BeautifulSoup(html, "html.parser")
    hdr = soup.find(string=re.compile("所在单位"))
    block = hdr.parent.get_text("|", strip=True)[:120] if hdr else "NO header"
    print(f"  [{slug}] 职称: {head.group(1) if head else None} | header: {block}")

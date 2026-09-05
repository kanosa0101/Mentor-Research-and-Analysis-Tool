"""看无邮箱页面里邮箱的具体形态(上下文), 为修复解析器定位。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from crawler import fetch

fetch.set_direct(False)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

CASES = [
    ("bnu/ai", "bailu"), ("bnu/ai", "bierongfang"), ("bnu/ai", "cuizhen"),
    ("tongji/cs", "caoxiaofeng"), ("tongji/cs", "cengguosun"),
    ("ustc/cs", "caixiaohui"), ("ustc/cs", "huabei"),
]
ROOT = Path(__file__).resolve().parent.parent
for key, slug in CASES:
    school, dept = key.split("/")
    d = yaml.safe_load((ROOT / "data" / "professors" / school / dept / f"{slug}.yaml")
                       .read_text(encoding="utf-8"))
    html, meta, _ = fetch.fetch_text("GET", d["detail_url"])
    print("=" * 20, key, slug)
    for m in list(EMAIL_RE.finditer(html))[:2]:
        i = m.start()
        ctx = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "|", html[max(0, i - 150):i + 60]))
        print("  ", ctx[-160:])

"""北师大 AI 学院导师列表页探查：requests 能看到什么、数据在哪。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import fetch

fetch.set_direct(True)

URLS = [
    "https://ai.bnu.edu.cn/zszl/yjszs/pyds/bssds/index.htm",
    "https://ai.bnu.edu.cn/zszl/yjszs/pyds/sssds/index.htm",
]
for url in URLS:
    print("=" * 30, url)
    try:
        html, meta, hit = fetch.fetch_text("GET", url, refresh=True)
    except Exception as e:
        print("FETCH FAIL:", repr(e)[:100])
        continue
    print(f"len={len(html)}")
    # info 链接
    links = re.findall(r'href="([^"]*info/\d+[^"]*)"[^>]*>([^<]{1,30})', html)
    print("info links:", len(links), links[:5])
    # ajax 痕迹
    for kw in ["ajax", "xhr", "XMLHttpRequest", "fetch(", "loadData", "json"]:
        n = html.lower().count(kw.lower())
        if n:
            print(f"  kw[{kw}] x{n}")
    # 页面文本量
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    print("text len:", len(soup.get_text(strip=True)))

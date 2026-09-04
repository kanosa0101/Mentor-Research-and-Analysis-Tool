"""探查中南 faculty.csu.edu.cn 详情页结构：requests 直连能否拿到内容、关键字段长什么样。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from crawler import fetch

fetch.set_direct(True)

URLS = [
    "https://faculty.csu.edu.cn/anying/zh_CN/index.htm",
    "https://faculty.csu.edu.cn/chenxianlai/zh_CN/index.htm",
]

for url in URLS:
    print("=" * 80)
    print(url)
    try:
        html, meta, hit = fetch.fetch_text("GET", url, refresh=True)
    except Exception as e:
        print("FETCH FAILED:", repr(e))
        continue
    print(f"len={len(html)} status={meta['status']}")
    soup = BeautifulSoup(html, "html.parser")
    # 页面上常见的字段容器：先看整体有哪些标志性 class/id
    text_len = len(soup.get_text(strip=True))
    print("visible text len:", text_len)
    for sel in ["div.name", "div.tit", "h1", "h2", "div.info", "div.intro",
                "div.cont", "div.per_info", "ul.per_list"]:
        found = soup.select(sel)
        if found:
            print(f"-- {sel} x{len(found)}:")
            for f in found[:3]:
                print("   ", f.get_text(" ", strip=True)[:120])
    # 邮箱/职称关键词上下文
    body = str(soup)
    for kw in ["邮箱", "职称", "学位", "研究方向", "Email", "@"]:
        i = body.find(kw)
        if i >= 0:
            frag = BeautifulSoup(body[max(0, i - 200):i + 200], "html.parser").get_text(" ", strip=True)
            print(f"kw[{kw}]:", frag[:150])

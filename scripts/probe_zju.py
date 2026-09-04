"""浙大 CS 站渲染探查：首页/师资页 XHR 与最终 DOM。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import fetch

# 浙大 www.cs.zju.edu.cn https 经代理 SSL 失败, http 可用; 页面数据走 XHR
URL = "http://www.cs.zju.edu.cn/"

browser = fetch._get_browser()  # 未 set_direct => 走代理
page = browser.new_page()
captured = []


def on_response(resp):
    ct = resp.headers.get("content-type", "")
    if "json" in ct or ("html" in ct and resp.url != URL):
        try:
            body = resp.text()[:400]
        except Exception:
            body = ""
        captured.append((resp.url, ct, body))


page.on("response", on_response)
try:
    page.goto(URL, timeout=40000, wait_until="networkidle")
except Exception as e:
    print("goto:", repr(e)[:80])
page.wait_for_timeout(4000)
html = page.content()
Path(__file__).parent.joinpath("_zju_home.html").write_text(html, encoding="utf-8")
print("rendered len:", len(html))
links = re.findall(r'href="([^"]+)"[^>]*>([^<]{2,20})', html)
hits = [l for l in links if any(k in l[1] for k in ("师资", "教师", "队伍", "人才", "导师"))]
print("faculty-ish links:", len(hits))
for h in hits[:10]:
    print("  ", h)
print("\n== XHR ==")
for u, ct, b in captured[:15]:
    print(u[:110], "|", ct[:20])
    print("   ", b[:150].replace("\n", " "))
page.close()

"""北师大 AI 学院列表页渲染 + XHR 监听，定位数据接口。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import fetch

fetch.set_direct(True)
URL = "https://ai.bnu.edu.cn/zszl/yjszs/pyds/bssds/index.htm"

browser = fetch._get_browser()
page = browser.new_page()
captured = []


def on_response(resp):
    ct = resp.headers.get("content-type", "")
    if "json" in ct or resp.url.endswith((".json", ".aspx", ".ashx", ".jsp")) \
            or "api" in resp.url or "list" in resp.url:
        try:
            body = resp.text()
        except Exception:
            body = "<binary>"
        captured.append({"url": resp.url, "ct": ct, "body": body[:800]})


page.on("response", on_response)
try:
    page.goto(URL, timeout=40000, wait_until="networkidle")
except Exception as e:
    print("goto:", repr(e)[:80])
page.wait_for_timeout(4000)
html = page.content()
Path(__file__).parent.joinpath("_bnu_rendered.html").write_text(html, encoding="utf-8")
print(f"rendered len={len(html)}")

import re
links = re.findall(r'href="([^"]*info/\d+[^"]*)"[^>]*>([^<]{1,30})', html)
print("info links:", len(links), links[:5])

print("\n== captured XHR ==")
for c in captured:
    print(c["url"], "|", c["ct"])
    b = c["body"][:300].replace("\n", " ")
    print("   ", b)
page.close()

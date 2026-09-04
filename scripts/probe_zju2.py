"""浙大 CS 教师名录页渲染 + XHR 监听。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import fetch

URL = "http://www.cs.zju.edu.cn/jsml/list.htm"

browser = fetch._get_browser()
page = browser.new_page()
captured = []


def on_response(resp):
    ct = resp.headers.get("content-type", "")
    if "json" in ct or ("html" in ct and resp.url != URL) or "jsp" in resp.url:
        try:
            body = resp.text()[:500]
        except Exception:
            body = ""
        captured.append((resp.url, ct, body))


page.on("response", on_response)
try:
    page.goto(URL, timeout=40000, wait_until="networkidle")
except Exception as e:
    print("goto:", repr(e)[:80])
page.wait_for_timeout(5000)
html = page.content()
Path(__file__).parent.joinpath("_zju_jsml.html").write_text(html, encoding="utf-8")
print("rendered len:", len(html))
links = re.findall(r'href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
items = [(h, re.sub(r"<[^>]+>|\s", "", x)[:16]) for h, x in links
         if re.search(r"/info/\d+|jsml/\d+\.htm|/[a-z]+/zh_CN", h)]
print("teacher items:", len(items), items[:8])
print("\n== XHR ==")
for u, ct, b in captured[:12]:
    print(u[:110], "|", ct[:24])
    print("   ", b[:200].replace("\n", " "))
page.close()

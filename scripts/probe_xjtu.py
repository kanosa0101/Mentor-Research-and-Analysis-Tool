"""西交 gr.xjtu.edu.cn 教师列表：渲染 + XHR 监听。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import fetch

fetch.set_direct(True)
URL = ("https://gr.xjtu.edu.cn/units_teacherlist.jsp?id=1025&lang=zh_CN&st=0"
       "&urltype=tsites.CollegeTeacherList&wbtreeid=1021")

browser = fetch._get_browser()
page = browser.new_page()
captured = []


def on_response(resp):
    ct = resp.headers.get("content-type", "")
    if "json" in ct or ("html" not in ct and "css" not in ct and "javascript" not in ct
                        and "image" not in ct and "font" not in ct):
        try:
            body = resp.text()[:600]
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
Path(__file__).parent.joinpath("_xjtu_list.html").write_text(html, encoding="utf-8")
print("rendered len:", len(html))
links = re.findall(r'href="([^"]+)"[^>]*>([^<]{2,15})</a>', html)
person = [l for l in links if "teacherlist" not in l[0]
          and re.search(r"zh_CN|index\.htm|/home", l[0])]
print("person links:", len(person), person[:6])
print("\n== XHRs ==")
for u, ct, b in captured[:15]:
    print(u[:110], "|", ct[:30])
    if b and "css" not in ct:
        print("   ", b[:200].replace("\n", " "))
page.close()

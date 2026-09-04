"""测试 tsites 加密字段服务端解密接口。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from crawler import fetch

fetch.set_direct(True)
url = "https://faculty.csu.edu.cn/anying/zh_CN/index.htm"
html, meta, hit = fetch.fetch_text("GET", url)
soup = BeautifulSoup(html, "html.parser")
mode = re.search(r"_tsites_com_view_mode_type_=(\d+)", html).group(1)
print("view_mode_type:", mode)

for span in soup.select("span[_tsites_encrypt_field]"):
    sid = span.get("id")
    content = span.get_text(strip=True)
    # 找到这个字段的标签（前面 li/p 的文本）
    label = ""
    p = span.find_parent(["li", "p"])
    if p:
        label = p.get_text(" ", strip=True)[:40]
    api = (f"https://faculty.csu.edu.cn/system/resource/tsites/tsitesencrypt.jsp"
           f"?id={sid}&content={content}&mode={mode}")
    try:
        raw, m2, _ = fetch.fetch_text("GET", api, refresh=True)
        print(f"\nid={sid}\nlabel~{label}\n  -> {raw[:200]}")
    except Exception as e:
        print(f"\nid={sid} FAILED: {e!r}")

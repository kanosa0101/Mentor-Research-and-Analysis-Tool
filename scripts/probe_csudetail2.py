"""看中南详情页字段区的具体 HTML 结构 + 邮箱混淆 JS 是否可逆。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from crawler import fetch

fetch.set_direct(True)
url = "https://faculty.csu.edu.cn/anying/zh_CN/index.htm"
html, meta, hit = fetch.fetch_text("GET", url)  # 用缓存

# 1. 找邮箱混淆相关的 JS 函数
print("== JS functions mentioning email/hex ==")
for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S):
    s = m.group(1)
    if "邮箱" in s or "email" in s.lower() or "tsites" in s.lower():
        print(s[:1500])
        print("---")

# 2. 字段区结构：职称/导师资格/所在单位所在容器的层级
soup = BeautifulSoup(html, "html.parser")
print("\n== 职称 context ==")
node = soup.find(string=re.compile("职称"))
if node:
    p = node.parent
    for _ in range(4):
        if p is None:
            break
        print(f"<{p.name} class={p.get('class')} id={p.get('id')}>")
        print(str(p)[:600])
        print("~~~")
        p = p.parent

# 3. 个人简介区
print("\n== 个人简介 section ==")
h2 = soup.find("h2", string=re.compile("个人简介"))
if h2:
    print("h2 parent:", h2.parent.name, h2.parent.get("class"))
    nxt = h2.parent.find_next_sibling()
    if nxt:
        print(str(nxt)[:800])

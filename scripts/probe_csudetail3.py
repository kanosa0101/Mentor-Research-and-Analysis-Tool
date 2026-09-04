"""把两个中南详情页缓存导出到临时文件 + 定位邮箱 hex 上下文 + 字段块结构。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup

from crawler import fetch

fetch.set_direct(True)
for tag, url in [("anying", "https://faculty.csu.edu.cn/anying/zh_CN/index.htm"),
                 ("chenxianlai", "https://faculty.csu.edu.cn/chenxianlai/zh_CN/index.htm")]:
    html, meta, hit = fetch.fetch_text("GET", url)
    out = Path(__file__).resolve().parent.parent / "cache" / f"csu_{tag}.html"
    out.write_text(html, encoding="utf-8")
    print(tag, "->", out, len(html))
    # 邮箱 hex 上下文
    m = re.search(r'.{300}521ef4c0|521ef4c0.{300}', html, re.S)
    if tag == "anying":
        i = html.find("521ef4c0")
        print("== hex context ==")
        print(html[i - 400:i + 200])
    # 字段区:找包含"所在单位"的容器
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(string=re.compile("所在单位"))
    if node:
        p = node.parent
        for lvl in range(4):
            if p is None:
                break
            print(f"[{tag}] L{lvl} <{p.name} class={p.get('class')}>")
            p = p.parent
        # 打印最小包含块的文本
        print(f"[{tag}] field block text:")
        print(p.get_text("|", strip=True)[:500] if p else node.parent.get_text("|", strip=True)[:500])

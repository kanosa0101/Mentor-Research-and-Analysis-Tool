"""用缓存 HTML 验证 tsites.parse_detail 输出。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "tsites", Path(__file__).resolve().parent.parent / "sites" / "tsites.py")
tsites = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tsites)

from crawler import fetch
fetch.set_direct(True)

URLS = {
    "anying": "https://faculty.csu.edu.cn/anying/zh_CN/index.htm",
    "chenxianlai": "https://faculty.csu.edu.cn/chenxianlai/zh_CN/index.htm",
}
for tag, url in URLS.items():
    html, meta, hit = fetch.fetch_text("GET", url)  # 缓存
    d = tsites.parse_detail({}, html, url)
    print("=" * 30, tag)
    for k, v in d.items():
        s = str(v)
        print(f"  {k}: {s[:120]}")

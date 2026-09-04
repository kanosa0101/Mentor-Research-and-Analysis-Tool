import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import fetch

fetch.set_direct(True)

html, meta, hit = fetch.fetch_rendered(
    "https://cse.csu.edu.cn/szdw/jsml.htm", wait_ms=3000, scroll=True)
print("csu bytes:", len(html))
names = re.findall(r'href="([^"]+)"[^>]*>\s*([\u4e00-\u9fa5·]{2,4})\s*<', html)
fac = [(n, h) for h, n in names if "faculty.csu" in h or "/info/" in h]
print("csu person anchors:", len(fac), fac[:4])

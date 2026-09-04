import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup
from crawler import fetch

fetch.set_direct(True)

ok = {}
for sid, u in (("nankai", "https://cc.nankai.edu.cn/jswyjy/list.htm"),
               ("hust", "http://cs.hust.edu.cn/szdw/jsml/axmpyszmlb.htm")):
    for attempt in range(3):
        try:
            html, meta, hit = fetch.fetch_rendered(u, wait_ms=3000, scroll=True)
            soup = BeautifulSoup(html, "html.parser")
            names = [l.strip() for l in soup.get_text("\n", strip=True).split("\n")
                     if re.match(r"^[\u4e00-\u9fa5·]{2,4}$", l.strip())]
            links = [a for a in soup.select("a[href*='info'], a[href*='_redirect'], a[href*='page.htm']")]
            print(f"{sid}: {len(html)}B visible-CJK={len(names)} person-links={len(links)}")
            ok[sid] = len(names)
            break
        except Exception as e:
            print(f"{sid} attempt {attempt+1} ERR {type(e).__name__}")

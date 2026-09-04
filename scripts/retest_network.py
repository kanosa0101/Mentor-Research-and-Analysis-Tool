import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from playwright.sync_api import sync_playwright

SITES = {
    "bupt": "https://www.scse.bupt.edu.cn/",
    "xidian": "https://computer.xidian.edu.cn/",
    "sustech": "https://cs.sustech.edu.cn/",
    "shanghaitech": "https://cs.sist.shanghaitech.edu.cn/",
    "xjtu": "https://cs.xjtu.edu.cn/",
    "scut": "https://www.scut.edu.cn/cs/",
    "ruc": "http://cs.ruc.edu.cn/",
    "uestc": "https://www.scse.uestc.edu.cn/",
    "csu": "http://sca.csu.edu.cn/",
}
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"

results = {}
for sid, url in SITES.items():
    try:
        r = S.get(url, timeout=12)
        ok = r.status_code == 200 and len(r.text) > 5000
        results[sid] = f"requests {r.status_code} len={len(r.text)}" + ("  <-- OK" if ok else "")
    except Exception as e:
        results[sid] = f"requests ERR {type(e).__name__}"

failed = [sid for sid in SITES if "OK" not in results[sid]]
pw = {}
if failed:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        for sid in failed:
            try:
                pg = b.new_page()
                pg.goto(SITES[sid], timeout=25000, wait_until="domcontentloaded")
                pg.wait_for_timeout(2000)
                html = pg.content()
                pw[sid] = f"render {len(html)}B 教授x{html.count('教授')}"
                pg.close()
            except Exception as e:
                pw[sid] = f"render ERR {type(e).__name__}"
        b.close()

for sid in SITES:
    line = f"{sid:<13} {results[sid]}"
    if sid in pw:
        line += f"  | playwright: {pw[sid]}"
    print(line)

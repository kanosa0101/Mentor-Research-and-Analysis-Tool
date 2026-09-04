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
    "hnu": "http://cs.hnu.edu.cn/",
    "cqu": "http://www.cse.cqu.edu.cn/",
    "scu_": "https://cs.scu.edu.cn/",
    "bnu": "https://cs.bnu.edu.cn/",
    "nankai": "https://cc.nankai.edu.cn/",
    "hust": "http://cs.hust.edu.cn/",
}
NO_PROXY = {"http": None, "https": None}
S = requests.Session()
S.trust_env = False
S.proxies = NO_PROXY
S.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"

ok, fail = [], []
for sid, url in SITES.items():
    try:
        r = S.get(url, timeout=15)
        size = len(r.text)
        tag = "OK" if r.status_code == 200 and size > 5000 else f"HTTP{r.status_code} len={size}"
        (ok if "OK" in tag else fail).append(sid)
        print(f"{sid:<14} {tag}")
    except Exception as e:
        fail.append(sid)
        print(f"{sid:<14} DIRECT ERR {type(e).__name__}")

print("\nplaywright direct 模式复测失败校 ...")
if fail:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, proxy={"server": "direct://"})
        for sid in fail:
            try:
                pg = b.new_page()
                pg.goto(SITES[sid], timeout=25000, wait_until="domcontentloaded")
                pg.wait_for_timeout(2500)
                html = pg.content()
                print(f"{sid:<14} RENDER {len(html)}B 教授x{html.count('教授')}")
                pg.close()
            except Exception as e:
                print(f"{sid:<14} RENDER ERR {type(e).__name__}")
        b.close()
print("\n直连可用:", ok or "无")
print("仍不可达:", fail or "无")

"""复测未接入学校连通性(2026-09-05, 域名已按 HANDOVER 纠错后的正确域名)。直连与代理各一遍。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

SITES = {
    "hust":   "http://cs.hust.edu.cn/",
    "bupt":   "https://scs.bupt.edu.cn/",
    "cqu":    "http://www.cse.cqu.edu.cn/",
    "hnu":    "http://cs.hnu.edu.cn/",
    "nankai": "https://cc.nankai.edu.cn/",
    "uestc":  "https://www.scse.uestc.edu.cn/",
    "scut":   "https://www.scut.edu.cn/cs/",
    "bit":    "https://cs.bit.edu.cn/",
    "tju":    "https://cs.tju.edu.cn/",
    "buaa":   "http://scse.buaa.edu.cn/",
    "ruc_cs": "http://info.ruc.edu.cn/",
    "nudt":   "http://www.nudt.edu.cn/",
}
PROXY = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


def probe(label, proxies, trust_env):
    s = requests.Session()
    s.trust_env = trust_env
    s.headers.update(UA)
    print(f"--- {label} ---")
    for sid, url in SITES.items():
        try:
            r = s.get(url, timeout=12, proxies=proxies, allow_redirects=True)
            size = len(r.text)
            tag = "OK" if r.status_code == 200 and size > 3000 else f"HTTP{r.status_code} len={size}"
            print(f"{sid:<8} {tag}")
        except Exception as e:
            print(f"{sid:<8} ERR {type(e).__name__}")


probe("直连", {"http": None, "https": None}, False)
probe("代理", PROXY, True)

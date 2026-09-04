import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent) if False else ".")

import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"
SITES = {
    "hnu": "http://cs.hnu.edu.cn/",
    "cqu": "http://www.cse.cqu.edu.cn/",
    "scu": "https://cs.scu.edu.cn/",
    "bnu": "https://cs.bnu.edu.cn/",
    "nankai": "https://cc.nankai.edu.cn/",
    "zju": "http://www.cs.zju.edu.cn/main.htm",
    "fudan": "https://ai.fudan.edu.cn/53161/list.htm",
    "bit": "https://cs.bit.edu.cn/szdw/jsml2/index.htm",
    "xmu": "https://cs.xmu.edu.cn/",
    "dlut": "https://ss.dlut.edu.cn/",
}
for sid, url in SITES.items():
    try:
        r = S.get(url, timeout=15)
        print(f"{sid:<8} {r.status_code} len={len(r.text)}")
    except Exception as e:
        print(f"{sid:<8} ERR {type(e).__name__}: {repr(e)[:70]}")

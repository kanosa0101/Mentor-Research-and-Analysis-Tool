import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from bs4 import BeautifulSoup

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"
KEYS = ("师资", "教师", "队伍", "导师", "人员", "faculty", "teacher")

SITES = {
    # 未探测的 T2b
    "jlu": "https://ccst.jlu.edu.cn/",
    "dlut": "https://ss.dlut.edu.cn/",
    "neu": "http://www.cse.neu.edu.cn/",
    "hnu": "http://cs.hnu.edu.cn/",
    "cqu": "http://www.cse.cqu.edu.cn/",
    "scu": "https://cs.scu.edu.cn/",
    "bnu": "https://cs.bnu.edu.cn/",
    # 可达但未完成的 T2
    "hust": "http://cs.hust.edu.cn/szdw/jsml/axmpyszmlb.htm",
    "seu": "https://cse.seu.edu.cn/dsxx/list.htm",
    "nankai": "https://cc.nankai.edu.cn/",
    "tju": "http://cs.tju.edu.cn/faculty/jzgml.htm",
    "xmu": "https://cs.xmu.edu.cn/",
    "nwpu": "https://jsj.nwpu.edu.cn/snew/szdw/szmd.htm",
    "ecnu": "https://cs.ecnu.edu.cn/jzgml/list.htm",
    "bit": "https://cs.bit.edu.cn/szdw/jsml2/index.htm",
}

for sid, url in SITES.items():
    try:
        r = S.get(url, timeout=15)
        r.encoding = r.apparent_encoding or "utf-8"
        t = r.text
        soup = BeautifulSoup(t, "html.parser")
        # 人名锚点（2-4 汉字 + 非导航 href）
        persons = {}
        for a in soup.select("a[href]"):
            nm = re.sub(r"\s+", "", str(a.get("title") or a.get_text(strip=True) or ""))
            if not re.match(r"^[\u4e00-\u9fa5·]{2,4}$", nm):
                continue
            href = urljoin(r.url, str(a.get("href") or ""))
            if not href.startswith("http"):
                continue
            if re.search(r"(index|main|list)\.htm", href):
                continue
            shape = re.sub(r"\d+", "N", href)
            persons.setdefault(shape, [0, nm, href])
            persons[shape][0] += 1
        top = sorted(persons.items(), key=lambda x: -x[1][0])[:2]
        fac_links = []
        for a in soup.select("a[href]"):
            t2 = a.get_text(strip=True)
            h = urljoin(r.url, str(a.get("href") or ""))
            if not h.startswith("http"):
                continue
            if t2 and len(t2) < 12 and any(k in t2 or k in h.lower() for k in KEYS):
                if h not in [x[2] for x in fac_links]:
                    fac_links.append(f"{t2[:8]}->{h[:80]}")
        n_persons = 0
        for shape, v in persons.items():
            if isinstance(v[0], int):
                n_persons += v[0]
            else:
                print(f"    ANOMALY {shape[:60]}: {repr(v)[:120]}")
        js = "wp_articlecontent" in t
        status = "OK" if r.status_code == 200 and len(t) > 4000 else f"HTTP{r.status_code} len={len(t)}"
        print(f"### {sid} [{status}] persons={n_persons} js={js}")
        for shape, (n, nm, h) in top:
            if n >= 3:
                print(f"    shape x{n}: {nm} {h[:85]}")
        for f in fac_links[:2]:
            print(f"    fac: {f}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"### {sid} ERR {type(e).__name__}: {repr(e)[:70]}")
    time.sleep(0.3)

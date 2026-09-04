import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from bs4 import BeautifulSoup

S = requests.Session()
S.trust_env = False
S.proxies = {"http": None, "https": None}
S.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"


def dump_anchors(sid, url, kw=None):
    r = S.get(url, timeout=25)
    r.encoding = r.apparent_encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    print(f"### {sid} len={len(r.text)}")
    n = 0
    for a in soup.select("a[href]"):
        raw = str(a)
        href = a.get("href") or ""
        # 找含教师特征的锚点：href 带教师系统域名/teacher/index
        if kw and not re.search(kw, href):
            continue
        txt = re.sub(r"\s+", " ", a.get_text(" ", strip=True))[:40]
        title = a.get("title") or ""
        print(f"    title={str(title)[:14]!r} text={txt!r} href={href[:100]}")
        n += 1
        if n >= 6:
            break
    if n == 0:
        # 没匹配 kw 的：打印含 教授/讲师 的锚
        for a in soup.select("a[href]"):
            t = a.get_text(" ", strip=True)
            if re.search(r"教授|讲师|研究员", t) and len(t) < 30:
                print(f"    ALT: {t[:30]!r} -> {a.get('href')[:90]}")
                n += 1
                if n >= 5:
                    break


dump_anchors("scu_p1", "https://faculty.scu.edu.cn/xyjs.jsp?id=1035&lang=zh_CN&st=0&urltype=tsites.CollegeTeacherList&wbtreeid=1012",
             kw=r"tsites|teacher|j parody")
dump_anchors("csu_jsml", "https://cse.csu.edu.cn/szdw/jsml.htm")
dump_anchors("bnu_bssds", "https://ai.bnu.edu.cn/zszl/yjszs/pyds/bssds/index.htm")
dump_anchors("xjtu_gr", "https://gr.xjtu.edu.cn/units_teacherlist.jsp?id=1025&lang=zh_CN&st=0&urltype=tsites.CollegeTeacherList&wbtreeid=1021")

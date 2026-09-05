"""抽查各院系"无字段"记录的原始页面, 判断是官网真没有还是解析漏了。
对每个院系的低覆盖字段, 取无值记录的详情页(优先缓存), 搜邮箱/职称痕迹。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from crawler import fetch

fetch.set_direct(False)  # 走代理(大部分站点缓存已存在, 不发新请求)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+\s*[@＃]\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
                      r"|[A-Za-z0-9._%+-]+\s*(?:AT|at)\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

TARGETS = ["bnu/ai", "jlu/cs", "neu/cs", "tongji/cs", "xjtu/cs", "hit/cs", "ustc/cs"]

ROOT = Path(__file__).resolve().parent.parent
for dept_key in TARGETS:
    school, dept = dept_key.split("/")
    noemail = []
    for f in sorted((ROOT / "data" / "professors" / school / dept).glob("*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not d.get("email"):
            noemail.append(d)
    print(f"=== {dept_key} 无邮箱 {len(noemail)} 条")
    for d in noemail[:4]:
        url = d.get("detail_url", "")
        try:
            html, meta, _ = fetch.fetch_text("GET", url)
        except Exception as e:
            print(f"  [{d['slug']}] fetch FAIL {repr(e)[:50]}")
            continue
        hits = list(dict.fromkeys(EMAIL_RE.findall(html)))[:2]
        print(f"  [{d['slug']}] len={len(html)} email痕迹: {hits if hits else '无'}")

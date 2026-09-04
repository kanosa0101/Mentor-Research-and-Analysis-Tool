"""盘点全库职称值的脏形态：单字、带括号、带尾巴、空格等。"""
import re
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

ROOT = Path(__file__).resolve().parent.parent
counter = Counter()
weird = []
for f in sorted((ROOT / "data" / "professors").glob("*/*/*.yaml")):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    t = d.get("title")
    if not t:
        continue
    t = str(t)
    counter[t] += 1
    if len(t) <= 2 or len(t) > 8 or any(c in t for c in "（(、/，, ；;　") or not re.match(
            r"^[\u4e00-\u9fa5·]+$", t):
        weird.append((t, d["school"], f.stem))

import re
print("== 职称值分布（top 40）==")
for t, n in counter.most_common(40):
    print(f"  {t!r} x{n}")
print(f"\n== 可疑形态 {len(weird)} 条 ==")
for t, s, slug in weird[:30]:
    print(f"  {t!r}  ({s}/{slug})")

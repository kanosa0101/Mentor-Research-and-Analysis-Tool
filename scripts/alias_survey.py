"""盘点全库 aliases 里可疑的垃圾值（inde/index 之类 URL 残渣）。"""
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import store

ROOT = Path(__file__).resolve().parent.parent
import yaml

counter = Counter()
examples = {}
for f in sorted((ROOT / "data" / "professors").glob("*/*/*.yaml")):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    for al in d.get("aliases") or []:
        counter[al] += 1
        examples.setdefault(al, str(f.relative_to(ROOT)))

print("top aliases:")
for al, n in counter.most_common(15):
    print(f"  {al!r} x{n}   e.g. {examples[al]}")
suspicious = {a: n for a, n in counter.items()
              if len(a) <= 6 and not any('\u4e00' <= c <= '\u9fff' for c in a)
              and a.lower() in ("inde", "index", "list", "main", "default", "info")}
print("\nsuspicious:", suspicious)

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from collections import defaultdict

FIELDS = ("title", "email", "institutes", "supervisor", "homepage",
          "photo_url", "bio_raw", "research_direction_raw")

rows = []
for f in sorted(Path("data/professors").glob("*/*/*.yaml")):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    for k in FIELDS:
        v = d.get(k)
        if isinstance(v, list):
            v = v or None
        if k == "institutes":
            v = bool(v)
        if k == "bio_raw":
            v = bool(v) and len(v) > 30
        rows.append((f"{d['school']}/{d['dept']}", k, bool(v)))

agg = defaultdict(lambda: defaultdict(int))
total = defaultdict(int)
for dept, k, has in rows:
    agg[dept][k] += has
    total[dept] += 0
counts = {}
for f in sorted(Path("data/professors").glob("*/*/*.yaml")):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    counts[f"{d['school']}/{d['dept']}"] = counts.get(f"{d['school']}/{d['dept']}", 0) + 1

print(f"{'dept':<18}{'n':>5}  " + "  ".join(f"{k[:10]:>10}" for k in FIELDS))
for dept in sorted(agg):
    print(f"{dept:<18}{counts[dept]:>5}  " +
          "  ".join(f"{agg[dept][k]:>4}({agg[dept][k]*100//counts[dept]:>3}%)" for k in FIELDS))

issues = 0
for f in sorted(Path("data/issues").glob("*.yaml")):
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or []
    open_i = [i for i in data if not i.get("resolved")]
    if open_i:
        print(f"issues {f.stem}: {len(open_i)}")
        issues += len(open_i)
print("total open issues:", issues)

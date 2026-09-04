import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

stats = collections.defaultdict(lambda: {"n": 0, "email": 0, "title": 0, "sup": 0,
                                         "bio": 0, "facets": 0, "hooks": ""})
hook_by_dept = {}
for f in sorted(Path("sites").glob("*/*.yaml")):
    cfg = yaml.safe_load(f.read_text(encoding="utf-8"))
    hook_by_dept[f"{cfg['school']}/{cfg['dept']}"] = cfg["hook"]

for f in Path("data/professors").glob("*/*/*.yaml"):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    k = f"{d['school']}/{d['dept']}"
    s = stats[k]
    s["n"] += 1
    s["email"] += 1 if d.get("email") else 0
    s["title"] += 1 if d.get("title") else 0
    s["sup"] += 1 if d.get("supervisor") else 0
    s["bio"] += 1 if d.get("bio_raw") else 0
    s["facets"] += 1 if d.get("facets") else 0

total = 0
for k in sorted(stats):
    s = stats[k]
    total += s["n"]
    print(f"| {k} | {hook_by_dept.get(k, '?')} | {s['n']} | {s['title']} | {s['email']} | {s['sup']} | {s['bio']} | {s['facets']} |")
print("TOTAL", total)
sup = sum(s["sup"] for s in stats.values())
fac = sum(s["facets"] for s in stats.values())
print("sup total:", sup, "| facet total:", fac)

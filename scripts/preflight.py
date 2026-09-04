import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from crawler.model import Professor

ROOT = Path(__file__).resolve().parent.parent
problems = []

print("== 1. YAML + schema 校验 ==")
records = {}
for f in sorted((ROOT / "data" / "professors").glob("*/*/*.yaml")):
    try:
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        p = Professor.model_validate(d)
    except Exception as e:
        problems.append(f"schema: {f}: {repr(e)[:80]}")
        continue
    key = f"{p.school}/{p.dept}/{p.slug}"
    if key in records:
        problems.append(f"dup slug: {key}")
    records[key] = p
print(f"records: {len(records)}")

print("== 2. 字段卫生 ==")
for key, p in records.items():
    if not (p.name or "").strip():
        problems.append(f"empty name: {key}")
    if p.email and ("@" not in p.email or re.search(r"[\u4e00-\u9fa5]", p.email)):
        problems.append(f"bad email: {key} {p.email!r}")
    if p.status not in ("roster", "enriched", "verified"):
        problems.append(f"bad status: {key} {p.status}")
    for fld, prov in p.provenance.items():
        if not prov.source or not prov.fetched_at:
            problems.append(f"provenance incomplete: {key}.{fld}")

print("== 3. issues / changes ==")
for f in sorted((ROOT / "data" / "issues").glob("*.yaml")):
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or []
    open_i = [i for i in data if not i.get("resolved")]
    if open_i:
        problems.append(f"open issues: {f.name} x{len(open_i)}")
for f in sorted((ROOT / "data" / "changes").glob("*.jsonl")):
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
        try:
            json.loads(line)
        except Exception:
            problems.append(f"bad change line: {f.name}:{i+1}")
print("ok")

print("== 4. 站点一致性 ==")
idx = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
m = re.search(r"const DATA = (\[.*?\]);\n", idx, re.S)
payload = json.loads(m.group(1).replace("<\\/", "</"))
print(f"payload rows: {len(payload)} (data {len(records)})")
if len(payload) != len(records):
    problems.append(f"payload {len(payload)} != data {len(records)}")
for p in payload:
    if not (ROOT / "site" / "p" / f"{p['page']}.html").exists():
        problems.append(f"missing detail page: {p['page']}")
pages = list((ROOT / "site" / "p").glob("*.html"))
if len(pages) != len(payload):
    problems.append(f"detail files {len(pages)} != payload {len(payload)}")

print("== 5. 仓库卫生 ==")
junk = []
for pat in ("scripts/probe_*.py", "scripts/debug_*.py", "scripts/check_*.py",
            "cache/*.html", "**/__pycache__", "*.pyc"):
    junk += [str(x) for x in ROOT.glob(pat)]
gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
for need in ("cache/", "__pycache__/", "*.pyc"):
    if need not in gitignore:
        problems.append(f".gitignore missing: {need}")
ignored = any(line.strip() in ("cache/", "cache") for line in gitignore.splitlines())
print(f"junk candidates: {len(junk)} | gitignore cache: {ignored}")

print("== 6. schools.yaml ==")
schools = yaml.safe_load((ROOT / "data" / "schools.yaml").read_text(encoding="utf-8"))["schools"]
used_schools = {k.split("/")[0] for k in records}
for s in schools:
    if s["id"] not in used_schools and s.get("include"):
        print(f"  configured but empty: {s['id']} ({s['name']})")
for sid in used_schools:
    if sid not in {s["id"] for s in schools}:
        problems.append(f"school not in schools.yaml: {sid}")

print("\n== PROBLEMS ==")
if problems:
    for p in problems:
        print(" -", p)
else:
    print("NONE")
print(f"total: {len(problems)}")

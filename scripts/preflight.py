import json
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from crawler.ai_util import validate_ai_block
from crawler.model import Professor
from crawler.outreach_util import validate_outreach
from crawler.contact_util import upgrade
from crawler.discovery_util import validate as validate_discovery

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=ROOT, help='校验独立测试数据根')
ROOT = parser.parse_args().root
def load_yaml(path):
    return yaml.load(path.read_text(encoding='utf-8'), Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))

problems = []

print("== 1. YAML + schema 校验 ==")
records = {}
for f in sorted((ROOT / "data" / "professors").glob("*/*/*.yaml")):
    try:
        d = load_yaml(f)
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
    data = load_yaml(f) or []
    # reviewed=True 表示人工复验过(如官网详情页确认 404、外部主页被墙),
    # 属如实记录而非待处理异常; 未复验的 open issue 才是问题
    open_i = [i for i in data if not i.get("resolved") and not i.get("reviewed")]
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
try:
    data_file = ROOT / 'site' / 'data.js'
    if 'const DATA = window.MENTOR_DATA;' in idx:
        raw = data_file.read_text(encoding='utf-8')
        m = re.search(r'window.MENTOR_DATA = (\[.*\]);', raw, re.S)
    else:
        m = re.search(r"const DATA = (\[.*?\]);\n", idx, re.S)
    payload = json.loads(m.group(1).replace("<\\/", "</"))
except (OSError, AttributeError, ValueError) as e:
    problems.append(f'payload invalid: {e}')
    payload = []
print(f"payload rows: {len(payload)} (data {len(records)})")
if len(payload) != len(records):
    problems.append(f"payload {len(payload)} != data {len(records)}")
expected_ids = {k.replace('/', '-', 2) for k in records}
actual_ids = {p.get('page') for p in payload}
if actual_ids != expected_ids or len(actual_ids) != len(payload):
    problems.append('payload IDs differ from professor records')
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
for need in ("cache/", "__pycache__/", "*.pyc", "data/outreach.yaml", "data/letters/"):
    if need not in gitignore:
        problems.append(f".gitignore missing: {need}")
ignored = any(line.strip() in ("cache/", "cache") for line in gitignore.splitlines())
print(f"junk candidates: {len(junk)} | gitignore cache: {ignored}")

print("== 6. schools.yaml ==")
schools = load_yaml(ROOT / 'data' / 'schools.yaml')["schools"]
used_schools = {k.split("/")[0] for k in records}
for s in schools:
    if s["id"] not in used_schools and s.get("include"):
        print(f"  configured but empty: {s['id']} ({s['name']})")
for sid in used_schools:
    if sid not in {s["id"] for s in schools}:
        problems.append(f"school not in schools.yaml: {sid}")

print("== 7. outreach.yaml（套磁跟进, 私人数据）==")
of = ROOT / "data" / "outreach.yaml"
if of.exists():
    odata = load_yaml(of) or {}
    try:
        validate_outreach(odata, expected_ids)
    except ValueError as e:
        problems.append(f'outreach: {e}')
        odata = {}
    valid_status = {"interested", "emailed", "replied", "meeting", "archived"}
    for pid, e in odata.items():
        parts = str(pid).split("-", 2)
        if len(parts) != 3 or not all(parts):
            problems.append(f"outreach bad id: {pid}")
            continue
        if f"{parts[0]}/{parts[1]}/{parts[2]}" not in records:
            problems.append(f"outreach unknown professor: {pid}")
        e = e or {}
        if e.get("status") not in valid_status:
            problems.append(f"outreach bad status: {pid} {e.get('status')!r}")
        for h in e.get("history") or []:
            if not (isinstance(h, dict) and h.get("date") and h.get("action")):
                problems.append(f"outreach bad history entry: {pid}")
    print(f"entries: {len(odata)}")
else:
    print("none (data/outreach.yaml 不存在)")

print("== 8. AI 块（evidence 必须可回溯到库内材料）==")
n_ai = 0
for key, p in records.items():
    if not p.ai:
        continue
    n_ai += 1
    mats = {"title": p.title, "supervisor": p.supervisor,
            "institutes": "、".join(p.institutes or []),
            "research_direction_raw": p.research_direction_raw, "bio_raw": p.bio_raw}
    if not validate_ai_block(p.ai.model_dump(mode="json"), mats):
        problems.append(f"ai block invalid (元数据缺失或证据不可回溯): {key}")
print(f"ai blocks: {n_ai}")

print("== 9. 私人申请工作流 ==")
wf = ROOT / 'data' / 'workflow.yaml'
if 'data/workflow.yaml' not in gitignore:
    problems.append('.gitignore missing: data/workflow.yaml')
if wf.exists():
    try:
        workflow = load_yaml(wf)
        upgrade(workflow, expected_ids)
        print('valid private workflow')
    except (ValueError, OSError, yaml.YAMLError) as e:
        problems.append(f'workflow invalid: {e}')
else:
    print('none (尚未创建私人申请记录)')

print('== 10. 私人筛选与招生核验 ==')
df = ROOT / 'data' / 'discovery.yaml'
if 'data/discovery.yaml' not in gitignore:
    problems.append('.gitignore missing: data/discovery.yaml')
if df.exists():
    try:
        validate_discovery(load_yaml(df), expected_ids)
        print('valid private discovery')
    except (ValueError, OSError, yaml.YAMLError) as e:
        problems.append(f'discovery invalid: {e}')
else:
    print('none (尚未保存私人筛选与核验)')

print("\n== PROBLEMS ==")
if problems:
    for p in problems:
        print(" -", p)
else:
    print("NONE")
print(f"total: {len(problems)}")
sys.exit(1 if problems else 0)

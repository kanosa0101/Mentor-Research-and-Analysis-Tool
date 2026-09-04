"""存量职称规范化一次性扫描：normalize_title 应用到全库，
变更记入 changes JSONL 可审计, provenance origin 置 computed（保留原 source）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from crawler import store
from crawler.model import Provenance, Professor
from crawler.title_util import normalize_title

ROOT = Path(__file__).resolve().parent.parent
changed = sup_added = 0
for f in sorted((ROOT / "data" / "professors").glob("*/*/*.yaml")):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    if not d or not d.get("title"):
        continue
    prof = Professor.model_validate(d)
    prov = prof.provenance.get("title")
    if prov is not None and prov.origin == "manual":
        continue
    new_title, sup_bits = normalize_title(prof.title)
    dirty = False
    if new_title != prof.title:
        store.append_changes(prof.school, prof.dept,
                             [{"slug": prof.slug, "field": "title",
                               "old": prof.title, "new": new_title}])
        prof.title = new_title
        if prov is not None:
            prov.origin = "computed"
        changed += 1
        dirty = True
    if sup_bits and not prof.supervisor:
        prof.supervisor = sup_bits
        prov_sup = Provenance(
            source=(prov.source if prov else prof.detail_url),
            fetched_at=(prov.fetched_at if prov else store.TODAY))
        prof.provenance.setdefault("supervisor", prov_sup)
        sup_added += 1
        dirty = True
    if dirty:
        store.save_professor(prof)
print(f"titles normalized: {changed}, supervisor filled from title: {sup_added}")

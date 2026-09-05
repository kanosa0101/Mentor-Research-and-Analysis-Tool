"""ECNU 旧 _redirect 记录并入新 faculty.ecnu.edu.cn 记录:
同名即同一人, 新记录缺的字段从旧记录补, 旧记录删除并销账(issue 注明并入去向)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import store
from crawler.model import Provenance

school, dept = "ecnu", "cs"
profs = store.load_all(school, dept)
issues = store.load_issues(school, dept)
by_name = {}
for p in profs.values():
    by_name.setdefault(p.name, []).append(p)

merged = 0
for i in issues:
    if i.kind != "missing_in_list" or i.resolved:
        continue
    old = profs.get(i.ref)
    if old is None:
        continue
    cands = [p for p in by_name.get(old.name, []) if p.slug != old.slug]
    if not cands:
        continue
    new = cands[0]
    for fld in ("title", "email", "phone", "office_address", "bio_raw",
                "homepage", "photo_url", "research_direction_raw"):
        if not getattr(new, fld, None) and getattr(old, fld, None):
            setattr(new, fld, getattr(old, fld))
            new.provenance.setdefault(fld, old.provenance.get(fld) or
                                      Provenance(source=old.detail_url,
                                                 fetched_at=store.TODAY))
    for al in old.aliases:
        if al not in new.aliases:
            new.aliases.append(al)
    store.save_professor(new)
    i.resolved = True
    i.message = f"{i.message} | 已并入 {new.slug}({new.detail_url}), 旧 _redirect 记录移除"
    f = store.professors_dir(school, dept) / f"{old.slug}.yaml"
    f.unlink()
    merged += 1
store.save_issues(school, dept, issues)
print(f"merged {merged} old records into new-URL records")

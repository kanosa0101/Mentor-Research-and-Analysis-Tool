"""清理存量垃圾别名（URL 通用文件名截碎产物），单遍扫描，只回写有改动的文件。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from crawler.model import Professor
from crawler import store

GARBAGE = {"pag", "lis", "inde", "te", "index", "list", "page", "teacher"}

ROOT = Path(__file__).resolve().parent.parent
removed = 0
for f in sorted((ROOT / "data" / "professors").glob("*/*/*.yaml")):
    d = yaml.safe_load(f.read_text(encoding="utf-8"))
    if not d or not d.get("aliases"):
        continue
    prof = Professor.model_validate(d)
    new = [a for a in prof.aliases if a.lower() not in GARBAGE]
    if len(new) != len(prof.aliases):
        prof.aliases = new
        store.save_professor(prof)
        removed += 1
print(f"cleaned aliases in {removed} records")

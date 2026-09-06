"""一次性职称迁移：对全库 title 字段重跑 normalize_title（词表扩充后的版本），
拆开"教授、博导"这类粘连值（supervisor 并入导师资格）、剥"教师"段、
清空解析胶水垃圾（E-mail：Homepage： 等）。变更追加进各院系 changes JSONL。

用法: python scripts/fix_titles.py [--dry]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from crawler.title_util import normalize_title
from crawler.store import append_changes

ROOT = Path(__file__).resolve().parent.parent
TODAY = "2026-09-06"

# 明确的解析垃圾值(职称位上的粘连/错位产物), 直接置空
JUNK_EXACT = {
    "E-mail：Homepage：",                      # xmu/wanghanzi: 标签粘连
    "智能网络与网络安全教育部重点实验室主任助理",  # xjtu/zhangchong: 行政职务混入
}
# 含拉丁字母/URL 的职称必是解析垃圾
JUNK_LATIN = re.compile(r"[A-Za-z@：:]{3,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    changes_by_dept = {}
    n_fixed = n_junk = n_sup = 0
    for f in sorted((ROOT / "data" / "professors").glob("*/*/*.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        t = d.get("title")
        if not t:
            continue
        school, dept = d["school"], d["dept"]
        old = str(t)
        prov = d.get("provenance", {}).get("title", {})
        if old in JUNK_EXACT or JUNK_LATIN.search(old):
            new, sup = None, None
            n_junk += 1
        else:
            new, sup = normalize_title(old)
            new = str(new) if new is not None else None
        if new == old and not (sup and not d.get("supervisor")):
            continue
        if not args.dry:
            if new is None:
                d.pop("title", None)
                d.get("provenance", {}).pop("title", None)
            else:
                d["title"] = new
            if sup and not d.get("supervisor"):
                d["supervisor"] = sup
                d.setdefault("provenance", {})["supervisor"] = {
                    "origin": prov.get("origin", "crawled"),
                    "source": prov.get("source", ""),
                    "fetched_at": prov.get("fetched_at", TODAY),
                    "confidence": "auto"}
                n_sup += 1
            f.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
            changes_by_dept.setdefault(f"{school}-{dept}", []).append(
                {"slug": d["slug"], "field": "title",
                 "old": old[:200], "new": str(new)[:200], "date": TODAY})
        if new is None:
            n_junk += 1
        else:
            n_fixed += 1

    if not args.dry:
        for dept_key, rows in changes_by_dept.items():
            school, dept = dept_key.split("-", 1)
            append_changes(school, dept, rows)
    print(f"职称改写 {n_fixed}, 垃圾清空 {n_junk}, 补 supervisor {n_sup}"
          + ("  [dry-run 未写盘]" if args.dry else ""))


if __name__ == "__main__":
    main()

"""一次性: 用 person.zju 搜索接口(appkey/sign 已逆向)把 detail 落在名录页的
浙大教师 detail_url 修正为 person.zju.edu.cn/<mapping_name> 个人主页。
只改 detail_url/profile_url, 字段富化交给 crawl enrich(CDP)。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml

cs = json.load(open(ROOT / "cache" / "zju_cs_person.json", encoding="utf-8"))
fixed = skipped = 0
for p in (ROOT / "data" / "professors" / "zju" / "cs").glob("*.yaml"):
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    if "cs.zju" not in (d.get("detail_url") or ""):
        continue
    rec = cs.get(d["name"])
    if not rec or not rec.get("mapping_name"):
        continue
    new_url = "https://person.zju.edu.cn/" + rec["mapping_name"]
    if d["detail_url"] == new_url:
        skipped += 1
        continue
    d["detail_url"] = d["profile_url"] = new_url
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    fixed += 1
print(f"detail_url 修正 {fixed} 人, 跳过 {skipped}")

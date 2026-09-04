import json
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import store

SITE = ROOT / "site"


def load_cfgs():
    out = []
    for f in sorted((ROOT / "sites").glob("*/*.yaml")):
        out.append(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


def main():
    env = Environment(loader=FileSystemLoader(ROOT / "site" / "templates"))
    school_names = {}
    sf = ROOT / "data" / "schools.yaml"
    if sf.exists():
        for s in yaml.safe_load(sf.read_text(encoding="utf-8"))["schools"]:
            school_names[s["id"]] = s["name"]

    profs = []
    for cfg in load_cfgs():
        for p in store.load_all(cfg["school"], cfg["dept"]).values():
            rec = p.model_dump(mode="json", exclude_none=True)
            rec["dept_name"] = cfg.get("dept_name", cfg["dept"])
            rec["school_name"] = school_names.get(cfg["school"], cfg["school"])
            prov = rec.get("provenance", {})
            rec["institutes"] = rec.get("institutes") or []
            rec["inst"] = "、".join(rec["institutes"])
            rec["page"] = f"{cfg['school']}-{cfg['dept']}-{p.slug}"
            profs.append(rec)
    profs.sort(key=lambda r: (r["school"], r["dept"], (r["institutes"] or [""])[0], r["slug"]))

    schools = sorted({(r["school"], r["school_name"]) for r in profs})
    depts = sorted({(r["school"], r["dept"], r["dept_name"]) for r in profs})
    titles = sorted({r["title"] for r in profs if r.get("title")})
    insts = sorted({i for r in profs for i in r["institutes"]})
    verified = [r["last_verified"] for r in profs if r.get("last_verified")]
    fresh = max(verified) if verified else None

    (SITE / "p").mkdir(parents=True, exist_ok=True)
    html = env.get_template("index.html.j2").render(
        profs=profs,
        schools=[{"id": s, "name": n} for s, n in schools],
        depts=[{"id": d, "name": n} for _, d, n in depts],
        titles=titles, institutes=insts, inst_count=len(insts), fresh=fresh,
        payload=json.dumps(profs, ensure_ascii=False).replace("</", "<\\/"))
    (SITE / "index.html").write_text(html, encoding="utf-8")
    for r in profs:
        html = env.get_template("detail.html.j2").render(p=r)
        (SITE / "p" / f"{r['page']}.html").write_text(html, encoding="utf-8")
    print(f"site: {len(profs)} professors, {len(schools)} schools, "
          f"{len(depts)} depts -> index + {len(profs)} detail pages")


if __name__ == "__main__":
    main()

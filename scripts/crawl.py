import argparse
import datetime
import importlib.util
import re
import sys
from pathlib import Path

import yaml
from pypinyin import lazy_pinyin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import fetch, store
from crawler.model import Provenance, Professor

TODAY = datetime.date.today().isoformat()


def list_url(cfg):
    lst = cfg["list"]
    return lst.get("url") or (lst["urls"][0] if "urls" in lst
                              else lst["channels"][0]["url"])


def load_cfg(school, dept):
    f = ROOT / "sites" / school / f"{dept}.yaml"
    return yaml.safe_load(f.read_text(encoding="utf-8"))


def load_hook(cfg):
    for base in (ROOT / "sites" / cfg["school"], ROOT / "sites"):
        path = base / (cfg["hook"] + ".py")
        if path.exists():
            spec = importlib.util.spec_from_file_location(cfg["hook"], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(cfg["hook"])


def make_slug(name, used):
    base = "".join(lazy_pinyin("".join(name.split())))
    slug, n = base, 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def phase_roster(cfg, hook, refresh):
    school, dept = cfg["school"], cfg["dept"]
    people, _ = hook.iter_roster(cfg)
    existing = store.load_all(school, dept)
    by_url = {(p.detail_url, p.name): p for p in existing.values()}
    used = set(existing)
    issues = store.load_issues(school, dept)
    created = updated = 0
    for rec in people:
        prof = by_url.get((rec["url"], rec["name"]))
        if prof is None:
            slug = make_slug(rec["name"], used)
            prov_name = Provenance(source=list_url(cfg), fetched_at=TODAY)
            prof = Professor(slug=slug, name=rec["name"], school=school, dept=dept,
                             detail_url=rec["url"], first_seen=TODAY,
                             provenance={"name": prov_name})
            created += 1
        # 从 URL 提取有信息量的别名（常是拼音/工号）。文件名可能是 index/page/list 等
        # 通用名（截碎就是 'inde'/'pag'/'lis' 事故），此时改用上一级有字母的目录名。
        seg = rec["url"].rstrip("/").rsplit("/", 1)[1]
        stem = re.sub(r"\.(s?html?|jspx?|aspx?|php)$", "", seg, flags=re.I)
        if stem.lower() in ("index", "list", "main", "default", "page", ""):
            parts = [p for p in rec["url"].rstrip("/").split("/")[:-1] if p]
            stem = next((p for p in reversed(parts)
                         if p.isascii() and p.isalpha()
                         and p.lower() not in ("en", "zh", "cn")), "")
        if stem.isascii() and stem.isalpha() and stem != prof.slug and stem not in prof.aliases:
            prof.aliases.append(stem)
        for al in rec.get("aliases", []):
            if al and al not in prof.aliases:
                prof.aliases.append(al)
        if rec.get("profile_url") and prof.profile_url != rec["profile_url"]:
            prof.profile_url = rec["profile_url"]
        list_prov = Provenance(source=list_url(cfg), fetched_at=TODAY)
        for key in ("title", "email", "phone", "supervisor", "subjects",
                    "research_direction_raw", "photo_url", "homepage"):
            v = rec.get(key) or rec.get("list_" + key)
            if v and not getattr(prof, key, None):
                if key == "email":
                    from crawler.email_util import normalize_email
                    v = normalize_email(v)
                    if not v:
                        continue
                setattr(prof, key, v.strip() if isinstance(v, str) else v)
                prof.provenance.setdefault(key, list_prov)
        for inst in rec.get("institutes", []):
            if inst not in prof.institutes:
                prof.institutes.append(inst)
                prof.provenance.setdefault(
                    "institutes", Provenance(source=list_url(cfg), fetched_at=TODAY))
                updated += 1
        store.save_professor(prof)
    current_urls = {(r["url"], r["name"]) for r in people}
    current_slugs = set()
    for prof in existing.values():
        if (prof.detail_url, prof.name) in current_urls:
            current_slugs.add(prof.slug)
        else:
            store.upsert_issue(issues, "missing_in_list", prof.slug,
                               f"官网名单中未出现，详情页 {prof.detail_url}")
    for i in issues:
        if i.kind == "missing_in_list" and i.ref in current_slugs:
            i.resolved = True
    store.save_issues(school, dept, issues)
    return {"roster_total": len(people), "created": created,
            "institute_updates": updated, "existing": len(existing)}


def phase_enrich(cfg, hook, refresh):
    if cfg.get("roster_only"):
        return {"enriched": 0, "failed": 0, "field_changes": 0, "note": "roster_only"}
    school, dept = cfg["school"], cfg["dept"]
    existing = store.load_all(school, dept)
    issues = store.load_issues(school, dept)
    done = failed = 0
    changes = []
    for prof in existing.values():
        if prof.status == "verified":
            continue
        try:
            html, meta, _ = fetch.fetch_text("GET", prof.detail_url, refresh=refresh)
            d = hook.parse_detail(cfg, html, prof.detail_url)
        except Exception as e:
            store.upsert_issue(issues, "fetch_or_parse_error", prof.slug, repr(e))
            failed += 1
            continue
        prov = Provenance(source=prof.detail_url, fetched_at=meta["fetched_at"])
        for field in ("title", "supervisor", "subjects", "email", "homepage", "photo_url",
                      "phone", "office_address", "bio_raw"):
            _merge(prof, field, d.get(field), prov, changes)
        canonical = d.get("name")
        if canonical and canonical != prof.name and canonical not in prof.aliases:
            prof.aliases.append(canonical)
        for inst in d.get("institute_from_detail") or []:
            if inst not in prof.institutes:
                prof.institutes.append(inst)
                _merge(prof, "institutes", prof.institutes, prov, changes)
        rd = d.get("research_directions") or []
        if rd:
            _merge(prof, "research_direction_raw", "、".join(rd), prov, changes)
        for msg in d.get("unknown_fields") or []:
            store.upsert_issue(issues, "unknown_detail_field", prof.slug, msg)
        for i in issues:
            if i.kind == "fetch_or_parse_error" and i.ref == prof.slug:
                i.resolved = True
        prof.status = "enriched"
        prof.last_verified = TODAY
        if d.get("source_updated_at"):
            prof.source_updated_at = str(d["source_updated_at"])
        store.save_professor(prof)
        done += 1
    store.save_issues(school, dept, issues)
    if changes:
        store.append_changes(school, dept, changes)
    return {"enriched": done, "failed": failed, "field_changes": len(changes)}


def _merge(prof, field, value, prov, changes=None):
    if value is None or value == "":
        return
    if field == "email":
        from crawler.email_util import normalize_email
        value = normalize_email(value)
        if not value:
            return
    if field == "title":
        # 职称规范化: 剥括号导师资格/长尾/空格, 统一规范词表
        from crawler.title_util import normalize_title
        value, sup_bits = normalize_title(value)
        if sup_bits and not prof.supervisor:
            prov_sup = Provenance(source=prov.source, fetched_at=prov.fetched_at)
            _merge(prof, "supervisor", sup_bits, prov_sup, changes)
        if not value:
            return
    old = prof.provenance.get(field)
    if old is not None and old.origin == "manual":
        return
    prev = getattr(prof, field, None)
    setattr(prof, field, value)
    prof.provenance[field] = prov
    if changes is not None and prev not in (None, "", value):
        changes.append({"slug": prof.slug, "field": field,
                        "old": str(prev)[:200], "new": str(value)[:200]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--school", default="sjtu")
    ap.add_argument("--dept", default="cs")
    ap.add_argument("--phase", choices=["all", "roster", "enrich"], default="all")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cfg = load_cfg(args.school, args.dept)
    if cfg.get("direct"):
        fetch.set_direct(True)
    if cfg.get("cdp_fallback"):
        # 瑞数/网防站点: requests 412/403/202 质询页自动降级 CDP 真实浏览器
        fetch.set_cdp_fallback(True)
    hook = load_hook(cfg)
    stats = {}
    if args.phase in ("all", "roster"):
        stats.update(phase_roster(cfg, hook, args.refresh))
    if args.phase in ("all", "enrich"):
        stats.update(phase_enrich(cfg, hook, args.refresh))
    issues = store.load_issues(args.school, args.dept)
    open_issues = [i for i in issues if not i.resolved]
    all_profs = store.load_all(args.school, args.dept)
    by_status = {}
    for p in all_profs.values():
        by_status[p.status] = by_status.get(p.status, 0) + 1
    print("== report ==")
    print("stats:", stats)
    print("total:", len(all_profs), "by_status:", by_status)
    print("open_issues:", len(open_issues))
    for i in open_issues:
        print(f"  [{i.kind}] {i.ref}: {i.message[:80]}")


if __name__ == "__main__":
    main()

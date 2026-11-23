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

from crawler import fetch, mentor_direction_review, store
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


def _save_professor(cfg, prof, original):
    if not cfg.get('contact_hook_only'):
        store.save_professor(prof)
        return
    from crawler.legacy_refresh import write_yaml
    from crawler.opportunity_monitor import output_lock
    path = store.professors_dir(prof.school, prof.dept) / (prof.slug + '.yaml')
    with output_lock(path):
        current = (Professor.model_validate(yaml.safe_load(path.read_text(encoding='utf-8'))).model_dump()
                   if path.is_file() else None)
        if current != original:
            raise ValueError('核验期间导师记录已变化，未覆盖')
        write_yaml(path, prof.model_dump(mode='json', exclude_none=True))


def _save_issues(cfg, issues):
    school, dept = cfg['school'], cfg['dept']
    if mentor_direction_review.enabled(school + '/' + dept, cfg):
        store.save_issues(school, dept, issues, preserve_kind=mentor_direction_review.KIND)
    else:
        store.save_issues(school, dept, issues)


def phase_roster(cfg, hook, refresh):
    school, dept = cfg["school"], cfg["dept"]
    with fetch.refresh_scope(refresh):
        people, roster_meta = hook.iter_roster(cfg)
    if not people:
        raise ValueError('名单为空，停止入库；请核验官网和解析器，不将抓取失败当作人员消失')
    if not roster_meta or not roster_meta.get('fetched_at'):
        raise ValueError('名单缺少真实抓取日期，停止入库，不能用解析日期替代来源日期')
    fetched_at = roster_meta['fetched_at']
    existing = store.load_all(school, dept)
    by_url = {(p.detail_url, p.name): p for p in existing.values()}
    by_name = {p.name: p for p in existing.values()}
    used = set(existing)
    issues = store.load_issues(school, dept)
    created = updated = 0
    # stable_urls: 名单 URL 会漂移的站点(zju xlsx 导师的"#姓名"锚点 vs 门户 API
    # 富化后的 person 主页)按姓名回退匹配存量, 保留既有详情页 URL, 不重复入库
    url_matched = set()
    name_matched = set()
    for rec in people:
        record_source = rec.get('roster_source') or list_url(cfg)
        record_date = rec.get('roster_fetched_at') or fetched_at
        prof = by_url.get((rec["url"], rec["name"]))
        name_only = False
        if prof is None and cfg.get("stable_urls"):
            cand = by_name.get(rec["name"])
            if cand is not None and cand.slug not in url_matched \
                    and cand.slug not in name_matched:
                prof = cand
                name_only = True
        if prof is not None:
            url_matched.add(prof.slug)
            if name_only:
                name_matched.add(prof.slug)
        original = prof.model_dump() if prof is not None and cfg.get('contact_hook_only') else None
        if prof is None:
            slug = make_slug(rec["name"], used)
            prov_name = Provenance(source=record_source, fetched_at=record_date)
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
        if rec.get("profile_url") and prof.profile_url != rec["profile_url"] \
                and not name_only:
            prof.profile_url = rec["profile_url"]
        list_prov = Provenance(source=record_source, fetched_at=record_date)
        for key in ("title", "email", "phone", "supervisor", "subjects",
                    "research_direction_raw", "photo_url", "homepage", "bio_raw"):
            if key == "email" and cfg.get("contact_hook_only"):
                continue
            if key == "bio_raw" and prof.provenance.get(key) and prof.provenance[key].origin == "manual":
                continue
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
            if prof.provenance.get('institutes') and prof.provenance['institutes'].origin == 'manual':
                continue
            if inst not in prof.institutes:
                prof.institutes.append(inst)
                prof.provenance.setdefault(
                    "institutes", Provenance(source=record_source, fetched_at=record_date))
                updated += 1
        _save_professor(cfg, prof, original)
    current_urls = {(r["url"], r["name"]) for r in people}
    current_slugs = set()
    for prof in existing.values():
        if (prof.detail_url, prof.name) in current_urls or prof.slug in name_matched:
            current_slugs.add(prof.slug)
        else:
            store.upsert_issue(issues, "missing_in_list", prof.slug,
                               f"官网名单中未出现，详情页 {prof.detail_url}")
    for i in issues:
        if i.kind == "missing_in_list" and i.ref in current_slugs:
            i.resolved = True
    _save_issues(cfg, issues)
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
        original = prof.model_dump() if cfg.get('contact_hook_only') else None
        try:
            with fetch.refresh_scope(refresh):
                html, meta, hit = fetch.fetch_text("GET", prof.detail_url, refresh=refresh)
                parse_cfg = cfg
                if cfg.get("hook") == "nwpu_cs" or cfg.get("contact_hook_only"):
                    parse_cfg = dict(cfg, _expected_name=prof.name, _original_profile=prof.model_dump())
                d = hook.parse_detail(parse_cfg, html, prof.detail_url)
        except Exception as e:
            store.upsert_issue(issues, "fetch_or_parse_error", prof.slug, repr(e))
            if cfg.get('hook') == 'related_v7' and (school, dept) in {('hust', 'aia'), ('csu', 'auto')} \
                    and isinstance(e, getattr(hook, 'IdentityMismatch', ())):
                for field in ('title', 'supervisor', 'subjects', 'email', 'homepage', 'photo_url',
                              'phone', 'office_address', 'bio_raw', 'research_direction_raw', 'institutes'):
                    if field == 'email' and cfg.get('contact_hook_only'):
                        continue
                    previous = prof.provenance.get(field)
                    if previous is None or previous.origin == 'manual' or previous.source != prof.detail_url:
                        continue
                    replacement = [] if field == 'institutes' else None
                    changes.append({'slug': prof.slug, 'field': field, 'old': getattr(prof, field),
                                    'new': replacement, 'reason': 'detail_identity_mismatch', 'source': prof.detail_url,
                                    'old_provenance': previous.model_dump(mode='json')})
                    setattr(prof, field, replacement)
                    prof.provenance.pop(field)
                prof.status = 'roster'
                prof.last_parsed = None
                _save_professor(cfg, prof, original)
            failed += 1
            continue
        prov = Provenance(source=prof.detail_url, fetched_at=meta["fetched_at"])
        for field in ("title", "supervisor", "subjects", "email", "homepage", "photo_url",
                      "phone", "office_address", "bio_raw"):
            if field == "email" and cfg.get("contact_hook_only"):
                continue
            _merge(prof, field, d.get(field), prov, changes)
        canonical = d.get("name")
        if canonical and canonical != prof.name and canonical not in prof.aliases:
            prof.aliases.append(canonical)
        for inst in d.get("institute_from_detail") or []:
            if inst not in prof.institutes:
                _merge(prof, "institutes", prof.institutes + [inst], prov, changes)
        rd = d.get("research_directions") or []
        if rd:
            _merge(prof, "research_direction_raw", "、".join(rd), prov, changes)
        if not cfg.get('explicit_supervisor_only') and not prof.supervisor and d.get("bio_raw"):
            # 导师资格兜底: 简介自述"教授、博士生导师"(职称相邻紧模式, 见
            # supervisor_util)。bio_raw 是简介正文, 站内导航栏目名不混入
            from crawler.supervisor_util import extract_supervisor
            sup = extract_supervisor(d["bio_raw"])
            if sup:
                _merge(prof, "supervisor", sup, prov, changes)
        for msg in d.get("unknown_fields") or []:
            store.upsert_issue(issues, "unknown_detail_field", prof.slug, msg)
        for i in issues:
            if i.kind == "fetch_or_parse_error" and i.ref == prof.slug:
                i.resolved = True
        prof.status = "enriched"
        prof.last_parsed = TODAY
        prof.last_fetched = meta['fetched_at']
        if not hit:
            prof.last_verified = meta['fetched_at']
        if d.get("source_updated_at"):
            prof.source_updated_at = str(d["source_updated_at"])
        _save_professor(cfg, prof, original)
        done += 1
    _save_issues(cfg, issues)
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
    if cfg.get('roster_pending') and not cfg.get('hook'):
        raise SystemExit('该院系师资采集尚未接入：' + cfg['roster_pending'])
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

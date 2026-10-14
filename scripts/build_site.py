import json
from datetime import date
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import store
from crawler import admissions_util

SITE = ROOT / "site"


def template_environment():
    return Environment(loader=FileSystemLoader(ROOT / 'site' / 'templates'), autoescape=True)


def write_html(path, html):
    # 仅规范生成文件行尾；官网原文仍保存在 YAML，不改源数据。
    path.write_text('\n'.join(line.rstrip() for line in html.splitlines()) + '\n', encoding='utf-8', newline='\n')


def safe_url(value):
    return value if value and urlsplit(value).scheme in ('http', 'https') else '#'


def list_record(p):
    keys = ('name', 'school', 'school_name', 'dept', 'dept_name', 'page', 'title',
            'supervisor', 'email', 'phone', 'institutes', 'inst', 'homepage',
            'detail_url', 'profile_url', 'first_seen', 'last_verified', 'source_date',
            'facets', 'status', 'research_direction_raw')
    rec = {k: p[k] for k in keys if k in p}
    rec['search_text'] = ' '.join(str(p.get(k) or '') for k in
                                 ('name', 'school_name', 'dept_name', 'email', 'aliases',
                                  'institutes', 'research_direction_raw')).lower()
    rec['facets'] = [{'id': f['id']} for f in p.get('facets', [])]
    return rec


def search_record(p):
    return (p.get('bio_raw') or '').lower()


def compare_record(p):
    rec = {'bio_excerpt': (p.get('bio_raw') or '')[:130]}
    rec['provenance'] = {k: v for k, v in p.get('provenance', {}).items()
                         if k in ('title', 'supervisor', 'email', 'phone', 'institutes',
                                  'homepage', 'bio_raw', 'research_direction_raw')}
    return rec


def load_cfgs():
    out = []
    for f in sorted((ROOT / "sites").glob("*/*.yaml")):
        out.append(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


def main():
    env = template_environment()
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
            rec["facets"] = [dict(f, id=f["id"].split(".", 1)[-1])
                             for f in rec.get("facets") or []]
            rec["inst"] = "、".join(rec["institutes"])
            rec["page"] = f"{cfg['school']}-{cfg['dept']}-{p.slug}"
            rec['source_date'] = p.last_fetched or max(
                (v.fetched_at for v in p.provenance.values() if v.origin == 'crawled'), default=None)
            for key in ('homepage', 'photo_url', 'detail_url', 'profile_url'):
                if rec.get(key):
                    rec[key] = safe_url(rec[key])
            for value in rec.get('provenance', {}).values():
                value['source'] = safe_url(value['source'])
            profs.append(rec)
    profs.sort(key=lambda r: (r["school"], r["dept"], (r["institutes"] or [""])[0], r["slug"]))

    schools = sorted({(r["school"], r["school_name"]) for r in profs})
    depts = sorted({(r["school"], r["dept"], r["dept_name"]) for r in profs})
    titles = sorted({r["title"] for r in profs if r.get("title")})
    insts = sorted({i for r in profs for i in r["institutes"]})
    source_dates = [r['source_date'] for r in profs if r.get('source_date')]
    fresh = max(source_dates) if source_dates else None
    stale_count = sum(not r.get('source_date') or (date.today() - date.fromisoformat(r['source_date'])).days > 30 for r in profs)

    (SITE / "p").mkdir(parents=True, exist_ok=True)
    # slug 变更或记录下线会留下孤儿详情页（csu 职称误作姓名事故残留 100 个），重建时按当前名单清掉
    live_pages = {r["page"] for r in profs}
    payload = json.dumps([list_record(p) for p in profs], ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (SITE / 'data.js').write_text('window.MENTOR_DATA = ' + payload + ';\n', encoding='utf-8')
    for filename, variable, make_record in (('search.js', 'MENTOR_SEARCH', search_record),
                                            ('compare-data.js', 'MENTOR_COMPARE', compare_record)):
        extra = json.dumps({p['page']: make_record(p) for p in profs}, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
        (SITE / filename).write_text('window.' + variable + ' = ' + extra + ';\n', encoding='utf-8')
    for stale_page in (SITE / "p").glob("*.html"):
        if stale_page.stem not in live_pages:
            stale_page.unlink()
    html = env.get_template("index.html.j2").render(
        profs=profs,
        schools=[{"id": s, "name": n} for s, n in schools],
        depts=[{"id": d, "name": n} for _, d, n in depts],
        titles=titles, institutes=insts, inst_count=len(insts), fresh=fresh, stale=stale_count)
    write_html(SITE / 'index.html', html)
    # 看板页：与列表页共用 payload（不含跟进数据——隐私分界，outreach 只经 serve.py 的 API 提供）
    board = env.get_template("board.html.j2").render(
        profs=profs, fresh=fresh)
    write_html(SITE / 'board.html', board)
    write_html(SITE / 'applications.html', env.get_template('applications.html.j2').render())
    write_html(SITE / 'desk.html', env.get_template('desk.html.j2').render())
    write_html(SITE / 'discovery.html', env.get_template('discovery.html.j2').render())
    admission_file = ROOT / 'data/admissions.yaml'
    admissions = yaml.safe_load(admission_file.read_text(encoding='utf-8')) if admission_file.exists() else {'version': 1, 'sources': {}, 'policies': []}
    units = {}
    for p in profs:
        units.setdefault(p['school'], set()).add(p['dept'])
    admissions_util.validate(admissions, units)
    checks_file = ROOT / 'data/admissions_checks.json'
    admissions['checks'] = json.loads(checks_file.read_text(encoding='utf-8')) if checks_file.exists() else {}
    admissions_util.validate_checks(admissions['checks'], admissions['sources'])
    notice_cfg = ROOT / 'sites/notices.yaml'
    notice_urls = {(c['school'], c['dept']): safe_url(c['url']) for c in yaml.safe_load(notice_cfg.read_text(encoding='utf-8'))['targets']} if notice_cfg.exists() else {}
    admissions['units'] = [{'school': s, 'school_name': school_names.get(s, s), 'dept': d, 'dept_name': n,
                            'count': sum(p['school'] == s and p['dept'] == d for p in profs), 'notice_url': notice_urls.get((s, d), '')} for s, d, n in depts]
    content = json.dumps(admissions, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (SITE / 'admissions-data.js').write_text('window.ADMISSIONS_DATA = ' + content + ';\n', encoding='utf-8')
    write_html(SITE / 'admissions.html', env.get_template('admissions.html.j2').render())
    # 对比页：同 payload；选人名单在 localStorage，纯静态无服务依赖
    cmp = env.get_template("compare.html.j2").render(
        profs=profs, fresh=fresh)
    write_html(SITE / 'compare.html', cmp)
    nf = ROOT / 'data/notices.json'
    if nf.exists():
        notices = json.loads(nf.read_text(encoding='utf-8'))
        html = env.get_template('notices.html.j2').render(notices=notices['notices'], sources=notices['sources'])
        write_html(SITE / 'notices.html', html)
    for r in profs:
        html = env.get_template("detail.html.j2").render(p=r)
        write_html(SITE / 'p' / f"{r['page']}.html", html)
    print(f"site: {len(profs)} professors, {len(schools)} schools, "
          f"{len(depts)} depts -> index + {len(profs)} detail pages")


if __name__ == "__main__":
    main()

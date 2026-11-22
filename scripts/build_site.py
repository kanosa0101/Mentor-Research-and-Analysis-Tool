import json
import re
from datetime import date, datetime, timedelta, timezone
import sys
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler import store
from crawler import admissions_util
from crawler.policy_revalidation import public_policy
from crawler import opportunity_util
from crawler.notice_util import annotate_notices
from crawler.admissions_entries import load_catalog, load_entries
from crawler.unit_util import groups, GROUPS

SITE = ROOT / "site"


def template_environment():
    return Environment(loader=FileSystemLoader(ROOT / 'site' / 'templates'), autoescape=True)


def write_html(path, html):
    # 仅规范生成文件行尾；官网原文仍保存在 YAML，不改源数据。
    path.write_text('\n'.join(line.rstrip() for line in html.splitlines()) + '\n', encoding='utf-8', newline='\n')


def inline_scripts(site, names):
    paths = [site / name if (site / name).is_file() else ROOT / 'site' / name for name in names]
    javascript = '\n;\n'.join(path.read_text(encoding='utf-8') for path in paths)
    return re.sub(r'</script', lambda match: '<\\/' + match.group(0)[2:], javascript, flags=re.I)


def entry_head(site):
    css = site / 'ui.css' if (site / 'ui.css').is_file() else ROOT / 'site' / 'ui.css'
    return dict(entry_css=css.read_text(encoding='utf-8'),
                entry_session_js=inline_scripts(site, ('account-session.js', 'cloud-library.js')))


def render_start_page(site=None, env=None):
    site = SITE if site is None else Path(site)
    return (env or template_environment()).get_template('start.html.j2').render(
        **entry_head(site), start_js=inline_scripts(site, (
            'school-catalog.js', 'browser-library-core.js', 'plan-transfer.js', 'start.js')))


def render_opportunities_page(site=None, env=None):
    site = SITE if site is None else Path(site)
    return (env or template_environment()).get_template('opportunities.html.j2').render(
        **entry_head(site), opportunity_js=inline_scripts(site, (
            'school-catalog.js', 'opportunities-core.js', 'opportunities.js', 'opportunity-push.js',
            'browser-library-core.js', 'browser-library.js')))


def build_discovery_entry(site=None):
    site = SITE if site is None else Path(site)
    files = [site / 'school-catalog.js']
    files.extend(site / name if (site / name).is_file() else ROOT / 'site' / name
                 for name in ('discovery-core.js', 'discovery.js'))
    (site / 'discovery-entry.js').write_text('\n;\n'.join(
        path.read_text(encoding='utf-8') for path in files), encoding='utf-8', newline='\n')


def build_application_entry(site=None):
    site = SITE if site is None else Path(site)
    files = [site / 'application-data.js']
    files.extend(site / name if (site / name).is_file() else ROOT / 'site' / name
                 for name in ('admissions-core.js', 'material-actions.js', 'opportunities-core.js', 'workflow.js'))
    (site / 'application-entry.js').write_text('\n;\n'.join(
        path.read_text(encoding='utf-8') for path in files), encoding='utf-8', newline='\n')


def render_discovery_page(site=None, env=None):
    site = SITE if site is None else Path(site)
    javascript = inline_scripts(site, ('school-catalog.js', 'discovery-core.js', 'discovery.js',
                                       'browser-library-core.js', 'browser-library.js'))
    return (env or template_environment()).get_template('discovery.html.j2').render(
        discovery_js=javascript, **entry_head(site))


def render_admissions_page(site=None, env=None):
    site = SITE if site is None else Path(site)
    return (env or template_environment()).get_template('admissions.html.j2').render(
        **entry_head(site), admissions_js=inline_scripts(site, (
            'admissions-data.js', 'admissions-core.js', 'material-actions.js', 'admissions.js')))


def safe_url(value):
    return value if value and urlsplit(value).scheme in ('http', 'https') else '#'


def roster_url(cfg):
    listing = cfg.get('list', {})
    source = listing.get('public_url') or listing.get('url') or next(iter(listing.get('urls', [])), '') or next((c['url'] for c in listing.get('channels', [])), '')
    return safe_url(source) if source else ''


def unit_coverage(profs):
    coverage = {field: sum(bool(p.get(field)) for p in profs)
                for field in ('email', 'research_direction_raw', 'bio_raw', 'supervisor')}
    dates = [p['source_date'] for p in profs if p.get('source_date')]
    coverage['source_dates'] = {'known': len(dates), 'unknown': len(profs) - len(dates),
                                'earliest': min(dates, default=''), 'latest': max(dates, default='')}
    return coverage


def list_record(p):
    keys = ('name', 'school', 'school_name', 'dept', 'dept_name', 'page', 'title',
            'supervisor', 'email', 'phone', 'institutes', 'inst', 'homepage',
            'detail_url', 'profile_url', 'first_seen', 'last_verified', 'source_date',
            'facets', 'status', 'research_direction_raw', 'unit_groups')
    rec = {k: p[k] for k in keys if k in p}
    rec['search_text'] = ' '.join(str(p.get(k) or '') for k in
                                 ('name', 'school_name', 'dept_name', 'email', 'aliases',
                                  'institutes', 'research_direction_raw')).lower()
    rec['facets'] = [{'id': f['id']} for f in p.get('facets', [])]
    return rec


def search_record(p):
    return (p.get('bio_raw') or '').lower()


def contact_record(p):
    # Application forms need identities and contact context, not directory facets or biographies.
    keys = ('page', 'name', 'school', 'dept', 'school_name', 'dept_name',
            'email', 'research_direction_raw')
    return {k: p[k] for k in keys if k in p}


def application_payload(profs, admissions):
    # The project picker needs identities; email/research remain on the contact page.
    identity = ('page', 'name', 'school', 'dept', 'school_name', 'dept_name')
    people = [{k: p[k] for k in identity if k in p} for p in profs]
    context = {k: admissions[k] for k in ('schools', 'sources', 'checks')}
    context['units'] = [{k: unit[k] for k in ('school', 'dept', 'school_name', 'dept_name')}
                        for unit in admissions['units']]
    # Preparation actions are loaded from the account API when that panel opens.
    context['policies'] = [{k: v for k, v in p.items() if k != 'material_actions'}
                           for p in admissions['policies']]
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return 'window.MENTOR_DATA = ' + encode(people) + ';\nwindow.ADMISSIONS_DATA = ' + encode(context) + ';\n'


def compare_record(p):
    rec = {'bio_excerpt': (p.get('bio_raw') or '')[:130]}
    rec['provenance'] = {k: v for k, v in p.get('provenance', {}).items()
                         if k in ('title', 'supervisor', 'email', 'phone', 'institutes',
                                  'homepage', 'bio_raw', 'research_direction_raw')}
    return rec


def discovery_record(p):
    keys = ('name', 'school', 'school_name', 'dept', 'dept_name', 'page', 'title',
            'supervisor', 'email', 'detail_url', 'profile_url', 'source_date',
            'research_direction_raw', 'unit_groups')
    rec = {k: p[k] for k in keys if k in p}
    rec['bio_excerpt'] = (p.get('bio_raw') or '')[:130]
    email_provenance = p.get('provenance', {}).get('email', {})
    rec['email_source'] = email_provenance.get('source', '')
    rec['email_source_date'] = email_provenance.get('fetched_at', '')
    host = urlsplit(rec['email_source']).hostname or ''
    rec['source_label'] = (p.get('name', '') + ' · 个人主页' if host.endswith('github.io')
                           else p.get('school_name', '') + ' · 公开资料')
    rec['recruitment_labels'] = p.get('recruitment_labels', [])
    field = 'research_direction_raw' if p.get('research_direction_raw') else 'bio_raw'
    rec['provenance'] = {field: p['provenance'][field]} if field in p.get('provenance', {}) else {}
    return rec


def mentor_recruitment(catalog):
    """Link explicit, reviewed identities only; recruitment does not imply supervisor status."""
    out = {}
    for item in catalog.get('opportunities', []):
        if opportunity_util.content_scope(item) != 'mentor_recruitment':
            continue
        for mentor_id in item.get('mentor_ids', []):
            out.setdefault(mentor_id, []).append(item)
    return out


def load_cfgs():
    out = []
    for f in sorted((ROOT / "sites").glob("*/*.yaml")):
        out.append(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


def main():
    env = template_environment()
    all_opportunities = opportunity_util.load(ROOT)
    recruitment = mentor_recruitment(all_opportunities)
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
            rec['unit_groups'] = groups(rec['dept_name'])
            rec["school_name"] = school_names.get(cfg["school"], cfg["school"])
            prov = rec.get("provenance", {})
            rec["institutes"] = rec.get("institutes") or []
            rec["facets"] = [dict(f, id=f["id"].split(".", 1)[-1])
                             for f in rec.get("facets") or []]
            rec["inst"] = "、".join(rec["institutes"])
            rec["page"] = f"{cfg['school']}-{cfg['dept']}-{p.slug}"
            rec['recruitment'] = recruitment.get(rec['page'], [])
            rec['recruitment_labels'] = ['科研实习招募记录'] if rec['recruitment'] else []
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
    contacts = json.dumps([contact_record(p) for p in profs], ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (SITE / 'contact-data.js').write_text('window.MENTOR_DATA = ' + contacts + ';\n', encoding='utf-8')
    lean = json.dumps([discovery_record(p) for p in profs], ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (SITE / 'discovery-data.js').write_text('window.MENTOR_DATA = ' + lean + ';\n', encoding='utf-8')
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
    opportunities = opportunity_util.public_catalog(all_opportunities)
    payload = json.dumps(opportunities, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (SITE / 'opportunities-data.js').write_text('window.OPPORTUNITIES = ' + payload + ';\n', encoding='utf-8')
    write_html(SITE / 'local.html', env.get_template('local.html.j2').render())
    write_html(SITE / 'account.html', env.get_template('account.html.j2').render())
    coverage_path = ROOT / 'data/coverage.json'
    if coverage_path.exists():
        coverage = json.loads(coverage_path.read_text(encoding='utf-8'))
        mentor_counted_at = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        school_names = {s['id']: s['name'] for s in yaml.safe_load((ROOT / 'data/schools.yaml').read_text(encoding='utf-8'))['schools']}
        for unit in coverage['units']:
            unit['school_name'] = school_names.get(unit['school'], unit['school'])
            members = [p for p in profs if (p['school'], p['dept']) == (unit['school'], unit['dept'])]
            dates = [p['last_verified'] for p in members if p.get('last_verified')]
            unit['current_mentors'] = dict(unit_coverage(members), count=len(members),
                                           first_verified=min(dates, default=''), last_verified=max(dates, default=''))
        source_coverage_path = ROOT / 'data/source_coverage.json'
        source_coverage = json.loads(source_coverage_path.read_text(encoding='utf-8')) if source_coverage_path.exists() else {}
        source_units = {(u['school'], u['dept']): u for u in source_coverage.get('units', [])}
        write_html(SITE / 'coverage.html', env.get_template('coverage.html.j2').render(
            coverage=coverage, mentor_counted_at=mentor_counted_at, safe_url=safe_url,
            source_coverage=source_coverage, source_units=source_units))
    admission_file = ROOT / 'data/admissions.yaml'
    admissions = yaml.safe_load(admission_file.read_text(encoding='utf-8')) if admission_file.exists() else {'version': 1, 'sources': {}, 'policies': []}
    configured_schools, units = load_catalog(ROOT)
    admissions_util.validate(admissions, units)
    admissions['policies'] = [public_policy(policy, admissions['sources']) for policy in admissions['policies']]
    checks_file = ROOT / 'data/admissions_checks.json'
    admissions['checks'] = json.loads(checks_file.read_text(encoding='utf-8')) if checks_file.exists() else {}
    admissions_util.validate_checks(admissions['checks'], admissions['sources'])
    admissions['schools'] = configured_schools
    admissions['entries'] = load_entries(ROOT, units, admissions['sources'])
    notice_cfg = ROOT / 'sites/notices.yaml'
    notice_urls = {(c['school'], c['dept']): safe_url(c['url']) for c in yaml.safe_load(notice_cfg.read_text(encoding='utf-8'))['targets']} if notice_cfg.exists() else {}
    admissions['groups'] = GROUPS
    admissions['units'] = [{'school': c['school'], 'school_name': school_names.get(c['school'], c['school']), 'dept': c['dept'], 'dept_name': c.get('dept_name', c['dept']),
                            'count': sum(p['school'] == c['school'] and p['dept'] == c['dept'] for p in profs), 'notice_url': notice_urls.get((c['school'], c['dept']), ''),
                            'groups': groups(c.get('dept_name', c['dept'])), 'roster_pending': c.get('roster_pending', ''),
                            'coverage': unit_coverage([p for p in profs if p['school'] == c['school'] and p['dept'] == c['dept']]),
                            'official_url': safe_url(c.get('base_url', '')), 'roster_url': roster_url(c)} for c in load_cfgs()]
    catalog = {'schools': configured_schools, 'units': [{k: v for k, v in unit.items() if k != 'coverage'} for unit in admissions['units']]}
    (SITE / 'school-catalog.js').write_text('window.SCHOOL_CATALOG = ' + json.dumps(catalog, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + ';\n', encoding='utf-8')
    write_html(SITE / 'opportunities.html', render_opportunities_page(env=env))
    write_html(SITE / 'start.html', render_start_page(env=env))
    build_discovery_entry()
    write_html(SITE / 'discovery.html', render_discovery_page(env=env))
    content = json.dumps(admissions, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (SITE / 'admissions-data.js').write_text('window.ADMISSIONS_DATA = ' + content + ';\n', encoding='utf-8')
    (SITE / 'application-data.js').write_text(application_payload(profs, admissions), encoding='utf-8')
    build_application_entry()
    write_html(SITE / 'admissions.html', render_admissions_page(env=env))
    release_file = ROOT / 'release.json'
    if release_file.exists():
        release = json.loads(release_file.read_text(encoding='utf-8'))
        write_html(SITE / 'release.html', env.get_template('release.html.j2').render(
            release=release, school_count=len(configured_schools), unit_count=sum(len(v) for v in units.values()),
            record_unit_count=len({(p['school'], p['dept']) for p in profs}), professor_count=len(profs),
            policy_count=len(admissions['policies']), source_count=len(admissions['sources']),
            entry_count=len(admissions['entries']), action_count=sum(len(p.get('material_actions', [])) for p in admissions['policies']),
            source_ok=sum(c.get('status') == 'ok' for c in admissions['checks'].values()),
            source_error=sum(c.get('status') == 'error' for c in admissions['checks'].values()), stale_count=stale_count))
    # 对比页：同 payload；选人名单在 localStorage，纯静态无服务依赖
    cmp = env.get_template("compare.html.j2").render(
        profs=profs, fresh=fresh)
    write_html(SITE / 'compare.html', cmp)
    nf = ROOT / 'data/notices.json'
    if nf.exists():
        notices = json.loads(nf.read_text(encoding='utf-8'))
        html = env.get_template('notices.html.j2').render(
            notices=annotate_notices(notices['notices'], opportunities=opportunity_util.load(ROOT)['opportunities']),
            sources=notices['sources'])
        write_html(SITE / 'notices.html', html)
    for r in profs:
        html = env.get_template("detail.html.j2").render(p=r)
        write_html(SITE / 'p' / f"{r['page']}.html", html)
    print(f"site: {len(profs)} professors, {len(schools)} schools, "
          f"{len(depts)} depts -> index + {len(profs)} detail pages")


if __name__ == "__main__":
    main()

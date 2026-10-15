"""按配置学校与院系列出分层政策/入口缺口，不计算整体完整率。"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import admissions_util
from crawler.admissions_entries import load_catalog, load_entries, source_status


def build_report(schools, units, data, entries, checks, year=2027, degree='master', route='exam', track='ordinary', program='', today=None):
    today = today or date.today().isoformat()
    policies = [p for p in data['policies'] if p['year'] == year and p['degree'] == degree and p['route'] == route
                and p.get('track', 'general' if p['level'] == 'school' else 'ordinary') in (track, 'general')]
    rows = []
    for school in schools:
        sid = school['id']
        for dept in ['', *sorted(units.get(sid, set()))]:
            scope = [p for p in policies if p['school'] == sid and (not p['dept'] or p['dept'] == dept)]
            is_program = lambda p: p['level'] == 'program' or p.get('track') == 'special' and bool(p['program'])
            levels = {level: [p for p in scope if p['level'] == level and not is_program(p)] for level in ('school', 'dept')}
            available = [p for p in scope if is_program(p)]
            levels['program'] = [p for p in available if program and (p['program_code'] + '|' + p['program']) == program]
            selected = [p for ps in levels.values() for p in ps]
            matching_entries = [e for e in entries if e['school'] == sid and e['dept'] == dept]
            gaps = []
            if not units.get(sid):
                gaps.append('院系目录待接入')
            if not levels['school']:
                gaps.append('学校规则未整理')
            if dept and not levels['dept']:
                gaps.append('院系附加要求未整理')
            if not program:
                gaps.append('专业未指定，专属条款不计覆盖')
            elif not levels['program']:
                gaps.append('该专业专属条款未整理')
            if not matching_entries:
                gaps.append('本层官方招生入口未登记')
            if track == 'special' and levels['school']:
                gaps.append('学校通用条款对专项的适用仍待核对')
            source_states = {source: source_status({'reviewed_at': today}, checks.get(source, {}), today)['state']
                             for p in selected for source in p['review_hashes']}
            review_due = [p['id'] for p in selected if not 0 <= (date.fromisoformat(today) - date.fromisoformat(p['reviewed_at'])).days <= 30
                          or any(checks.get(s, {}).get('hash') != h or source_states[s] != 'checked' for s, h in p['review_hashes'].items())]
            rows.append({'school': sid, 'school_name': school['name'], 'dept': dept,
                         'year': year, 'degree': degree, 'route': route, 'track': track, 'program': program,
                         **{level + '_policy_ids': [p['id'] for p in ps] for level, ps in levels.items()},
                         'available_program_policy_ids': [p['id'] for p in available],
                         'fields_by_layer': {level: sorted({f for p in ps for f in p['fields']}) for level, ps in levels.items()},
                         'source_states': source_states, 'summary_review_due': review_due,
                         'entries': [dict(e, status=source_status(e, checks.get(e['source_id'], {}), today)) for e in matching_entries],
                         'gaps': gaps})
    return {'scope': {'year': year, 'degree': degree, 'route': route, 'track': track, 'program': program},
            'generated_at': today,
            'denominators': {'schools': len(schools), 'schools_with_units': sum(bool(u) for u in units.values()), 'units': sum(map(len, units.values()))},
            'note': '摘要类别与来源状态分别记录；已有八类摘要也不代表条款完整或个人符合资格。', 'rows': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--year', type=int, default=2027)
    parser.add_argument('--degree', choices=('master', 'phd'), default='master')
    parser.add_argument('--route', choices=('exam', 'recommend', 'assessment'), default='exam')
    parser.add_argument('--track', choices=('ordinary', 'special'), default='ordinary')
    parser.add_argument('--program', default='', help='专业代码|正式专业名；未指定不计专属条款覆盖')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    schools, units = load_catalog(args.root)
    path = args.root / 'data/admissions.yaml'
    data = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'sources': {}, 'policies': []}
    admissions_util.validate(data, units)
    path = args.root / 'data/admissions_checks.json'
    checks = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    admissions_util.validate_checks(checks, data['sources'])
    entries = load_entries(args.root, units, data['sources'])
    report = build_report(schools, units, data, entries, checks, args.year, args.degree, args.route, args.track, args.program)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())

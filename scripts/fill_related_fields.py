"""Bounded official-section backfill pilot for two registered department rosters."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import crawler.fetch as http
from crawler.model import Professor
from crawler.store import append_changes

PILOT = ROOT / 'cache' / 'field_fill'
FIELDS = ('research_direction_raw', 'email')
LABELS = ('研究方向', '研究领域')


def allowed_url(school, url):
    parsed = urlsplit(url)
    host = {'tsinghua': 'www.au.tsinghua.edu.cn', 'sjtu': 'sais.sjtu.edu.cn'}.get(school)
    pattern = r'/info/\d+/\d+\.htm' if school == 'tsinghua' else r'/faculty/[^/]+\.html'
    return parsed.scheme == 'https' and parsed.netloc == host and bool(re.fullmatch(pattern, parsed.path))


def record_path(school, slug):
    if school not in ('tsinghua', 'sjtu') or not re.fullmatch(r'[a-z0-9_-]+', slug):
        raise ValueError('Outside the two registered pilot directories')
    return ROOT / 'data' / 'professors' / school / 'auto' / (slug + '.yaml')


def matches_name(school, html, expected):
    selector = '.fl01 h2' if school == 'tsinghua' else '.js-info .tit p'
    node = BeautifulSoup(html, 'html.parser').select_one(selector)
    return bool(node) and re.sub(r'\s+', '', node.get_text()) == re.sub(r'\s+', '', expected)


def extract(school, html):
    soup = BeautifulSoup(html, 'html.parser')
    result = {}
    if school == 'sjtu':
        for item in soup.select('.js-item'):
            heading = item.select_one('.tit')
            body = item.select_one('.detail')
            if heading and body and heading.get_text(strip=True) in LABELS:
                lines = []
                for line in body.stripped_strings:
                    if line in ('个人简介', '招生及招聘', '工作经历', '教育背景', '荣誉奖励', '学术成果'):
                        break
                    lines.append(line)
                value = '\n'.join(lines)
                if value:
                    result['research_direction_raw'] = {'value': value, 'locator': '.js-item > .tit: ' + heading.get_text(strip=True)}
                    break
        email_nodes = soup.select('.js-info .detail p')
        email_text = '\n'.join(n.get_text(' ', strip=True) for n in email_nodes if '电子邮件' in n.get_text())
    else:
        for root in soup.select('.leader_d .fl02'):
            headings = root.select('.t-tag')
            for heading in headings:
                label = heading.get_text(strip=True)
                if label not in LABELS:
                    continue
                # Only the text bounded by this explicit heading and the next section.
                lines = list(root.stripped_strings)
                start = lines.index(label) + 1
                end_labels = {h.get_text(strip=True) for h in headings if h is not heading}
                values = []
                for line in lines[start:]:
                    if line in end_labels:
                        break
                    values.append(line)
                if values:
                    result['research_direction_raw'] = {'value': '\n'.join(values), 'locator': '.leader_d .fl02 .t-tag: ' + label}
                break
            if 'research_direction_raw' in result:
                break
        email_text = '\n'.join(n.get('href', '') for n in soup.select('.fl01 a[href^="mailto:"]'))
    emails = set(re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email_text))
    if len(emails) == 1:
        result['email'] = {'value': emails.pop(), 'locator': '个人联系信息/电子邮件'}
    return result


def patch(raw, evidence, source, fetched_at):
    """Insert only missing fields; leave unrelated YAML text and provenance intact."""
    data = yaml.safe_load(raw)
    changes = []
    for field in FIELDS:
        item = evidence.get(field)
        provenance = data.get('provenance', {}).get(field, {})
        if not item or data.get(field) or provenance.get('origin') == 'manual':
            continue
        # Existing per-field provenance needs review rather than blind replacement.
        if provenance:
            continue
        value = item['value']
        field_yaml = yaml.safe_dump({field: value}, allow_unicode=True, sort_keys=False)
        if field in data:
            empty = re.compile(r'^' + field + r':\s*(?:null|~|\'\'|"")?\s*$', re.MULTILINE)
            raw, count = empty.subn(lambda m: field_yaml.rstrip('\n'), raw, count=1)
            if count != 1:
                raise ValueError('Cannot surgically patch existing empty field')
        else:
            raw = raw.rstrip('\n') + '\n' + field_yaml
        new_provenance = yaml.safe_dump({field: {'origin': 'crawled', 'source': source, 'fetched_at': fetched_at, 'confidence': 'auto'}}, allow_unicode=True, sort_keys=False)
        nested = ''.join('  ' + line + '\n' for line in new_provenance.splitlines())
        if 'provenance:\n' not in raw:
            raise ValueError('Missing explicit provenance map')
        raw = raw.replace('provenance:\n', 'provenance:\n' + nested, 1)
        changes.append({'slug': data['slug'], 'field': field, 'old': data.get(field), 'new': value, 'source': source, 'fetched_at': fetched_at, 'locator': item['locator']})
    Professor.model_validate(yaml.safe_load(raw))
    return raw, changes


def digest(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def dry_run(limit):
    if not 1 <= limit <= 20:
        raise ValueError('Pilot limit must be between 1 and 20 per department')
    PILOT.mkdir(parents=True, exist_ok=True)
    http.CACHE = PILOT / 'http'
    http.set_direct(True)
    plan = {'limit': limit, 'records': [], 'attempts': []}
    for school in ('tsinghua', 'sjtu'):
        changed = 0
        paths = list((ROOT / 'data' / 'professors' / school / 'auto').glob('*.yaml'))
        paths.sort(key=lambda p: (bool(yaml.safe_load(p.read_text(encoding='utf-8')).get('email')), p.name))
        for path in paths:
            if changed >= limit:
                break
            raw = path.read_text(encoding='utf-8')
            data = yaml.safe_load(raw)
            if all(data.get(field) or data.get('provenance', {}).get(field, {}).get('origin') == 'manual' for field in FIELDS):
                continue
            source = data['detail_url']
            attempt = {'school': school, 'slug': data['slug'], 'source': source}
            if not allowed_url(school, source):
                attempt['status'] = 'unsupported_official_path'
                plan['attempts'].append(attempt)
                continue
            try:
                html, meta, _ = http.fetch_text('GET', source, refresh=True)
                if not matches_name(school, html, data['name']):
                    attempt['status'] = 'profile_identity_mismatch'
                    plan['attempts'].append(attempt)
                    continue
                proposed, changes = patch(raw, extract(school, html), source, meta['fetched_at'])
                attempt['status'] = 'proposed' if changes else 'no_missing_field_with_explicit_section'
                if changes:
                    plan['records'].append({'school': school, 'slug': data['slug'], 'before_sha256': digest(raw), 'after_sha256': digest(proposed), 'changes': changes})
                    changed += 1
            except Exception as error:
                attempt['status'] = 'fetch_or_parse_failed'
                attempt['error'] = str(error)
            plan['attempts'].append(attempt)
    target = PILOT / 'plan.json'
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'plan': str(target), 'records': len(plan['records']), 'attempts': len(plan['attempts'])}, ensure_ascii=False))


def apply_plan(path):
    plan = json.loads(path.read_text(encoding='utf-8'))
    counts = {}
    prepared = []
    for record in plan['records']:
        school, slug = record['school'], record['slug']
        counts[school] = counts.get(school, 0) + 1
        if counts[school] > 20:
            raise ValueError('Pilot is limited to twenty records per department')
        target = record_path(school, slug)
        raw = target.read_text(encoding='utf-8')
        if digest(raw) != record['before_sha256']:
            raise ValueError('Record changed since dry-run: ' + slug)
        changes = record['changes']
        if not changes or len({c['source'] for c in changes}) != 1:
            raise ValueError('Expected a single verified official page')
        source = changes[0]['source']
        if not allowed_url(school, source) or source != yaml.safe_load(raw)['detail_url']:
            raise ValueError('Source does not match the registered official teacher page')
        evidence = {c['field']: {'value': c['new'], 'locator': c['locator']} for c in changes}
        if set(evidence) - set(FIELDS):
            raise ValueError('Unsupported field')
        proposed, actual = patch(raw, evidence, source, changes[0]['fetched_at'])
        if actual != changes or digest(proposed) != record['after_sha256']:
            raise ValueError('Dry-run diff mismatch')
        prepared.append((target, proposed, actual, school))
    for target, proposed, changes, school in prepared:
        target.write_text(proposed, encoding='utf-8', newline='\n')
        append_changes(school, 'auto', changes)
    print(json.dumps({'applied_records': len(prepared), 'departments': counts}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--apply-plan', type=Path)
    args = parser.parse_args()
    if args.apply_plan:
        apply_plan(args.apply_plan)
    else:
        dry_run(args.limit)

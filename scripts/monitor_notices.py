"""官方招生栏目小样本监测。缓存优先；--refresh 回源；只输出候选，不猜截止日期。"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import fetch

KEYWORDS = ('招生', '推免', '免试', '夏令营', '冬令营', '科研实践', '科研实习', '暑期研修', '春闱计划', '科创计划', '深瞳计划', '创新实践', '暑期科学营', '复试', '录取', '统考', '申请', '初试', '网上确认', '网报', '考点', '考试大纲', '专业目录')


def notice_hints(title):
    return {'title_years': sorted({int(y) for y in re.findall(r'20\d{2}', title)}),
            'route_hint': next((k for k in ('冬令营', '夏令营', '推免', '免试', '统考', '博士') if k in title), None),
            'admission_year': None, 'deadline': None, 'reviewed': False}


def parse_list(html, cfg):
    soup = BeautifulSoup(html, 'html.parser')
    records = {}
    date_parents = soup.select(cfg['date_parent_selector']) if cfg.get('date_parent_selector') else []
    for a in soup.select(cfg['selector']):
        title_node = a if cfg.get('title_selector') == 'self' else a.select_one(cfg.get('title_selector', 'h4'))
        title = a.get('title') or (title_node.get_text(' ', strip=True) if title_node else '')
        if '<' in title:
            title = BeautifulSoup(title, 'html.parser').get_text(' ', strip=True)
        link_attr = cfg.get('link_attr', 'href')
        link = a.get(link_attr, '')
        if link_attr == 'onclick':
            # Some official columns use table-row navigation; never evaluate JS.
            assignment = re.fullmatch(r"\s*window\.location\.href\s*=\s*(['\"])([^'\"\r\n\\]+)\1\s*;?\s*", link)
            if not assignment:
                continue
            link = assignment.group(2)
        if not link:
            continue
        url = urljoin(cfg['url'], link)
        if not title or not any(k in title for k in KEYWORDS):
            continue
        if urlsplit(url).scheme not in ('http', 'https') or urlsplit(url).hostname != urlsplit(cfg['url']).hostname:
            continue
        stamp = (next((p for p in a.parents if p in date_parents), None) or a.find_parent('li') or a).select_one(cfg['date_selector']) if cfg.get('date_selector') else a.select_one('.time')
        stamp = stamp.get_text(' ', strip=True) if stamp else ''
        published = None
        match = re.search(r'(20\d{2})(?:[.\-/年]|\s+)(\d{1,2})[.\-/月](\d{1,2})(?:日)?', stamp)
        reverse = re.fullmatch(r'(\d{1,2})\s+(20\d{2})[.\-/](\d{2})', stamp)
        split_day = re.fullmatch(r'(20\d{2})-(\d{2})\s+(\d{1,2})', stamp)
        if match:
            year, month, day = match.groups()
            published = f'{year}-{int(month):02d}-{int(day):02d}'
        elif reverse:
            day, year, month = reverse.groups()
            published = f'{year}-{month}-{int(day):02d}'
        elif split_day:
            year, month, day = split_day.groups()
            published = f'{year}-{month}-{int(day):02d}'
        if published:
            try:
                date.fromisoformat(published)
            except ValueError:
                published = None
        records[url] = {'id': hashlib.sha256(url.encode()).hexdigest()[:16],
                        'school': cfg['school'], 'dept': cfg['dept'], 'unit': cfg.get('name', cfg['school']),
                        'title': title, 'url': url, 'source': cfg['url'],
                        'publication_date': published, **notice_hints(title)}
    return list(records.values())


def signature(rows):
    content = sorted((r['url'], r['title']) for r in rows)
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


def sort_notices(rows):
    """当前栏目在先；组内按公开日期倒序，未标日期在后，保留原记录。"""
    def key(row):
        published = row.get('publication_date')
        return (row.get('seen_in_latest_list') is not True, not bool(published),
                -int(published.replace('-', '')) if published else 0,
                row['school'], row['url'])
    return sorted(rows, key=key)


def collect(cfgs, output, *, refresh=False, fetcher=None):
    # Imported at call time: the opportunity monitor shares this module's list parser.
    from crawler.opportunity_monitor import atomic_json, output_lock
    with output_lock(output):
        return _collect(cfgs, Path(output), refresh=refresh, fetcher=fetcher, writer=atomic_json)


def _collect(cfgs, output, *, refresh, fetcher, writer):
    output.parent.mkdir(parents=True, exist_ok=True)
    previous = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {'notices': [], 'sources': {}}
    rows = {r['url']: r for r in previous['notices']}
    sources = previous.get('sources', {})
    failed = changes = 0
    checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    fetch.set_direct(True)
    for cfg in cfgs:
        key = cfg['school'] + '/' + cfg['dept']
        try:
            if fetcher:
                html, meta, hit = fetcher(cfg)
            else:
                with fetch.refresh_scope(refresh):
                    if cfg.get('api'):
                        body, meta, hit = fetch.fetch_text('POST', cfg['api'], data=cfg['post'])
                        html = json.loads(body)['content']
                    else:
                        html, meta, hit = fetch.fetch_text('GET', cfg['url'])
            found = parse_list(html, cfg)
            if not found:
                raise ValueError('未提取到通知，保留旧记录并报告解析失败')
            fingerprint = signature(found)
            old = sources.get(key, {})
            if fingerprint != old.get('signature'):
                changes += 1
                with (output.parent / 'notices_changes.jsonl').open('a', encoding='utf-8') as f:
                    f.write(json.dumps({'source': key, 'fetched_at': meta['fetched_at'],
                                        'old': old.get('signature'), 'new': fingerprint,
                                        'urls': [r['url'] for r in found]}, ensure_ascii=False) + '\n')
            for r in found:
                prior = rows.get(r['url'], {})
                if prior.get('title') == r['title']:
                    for field in ('admission_year', 'graduation_year', 'activity_year', 'deadline', 'reviewed', 'review_note'):
                        if field in prior:
                            r[field] = prior[field]
                r['first_seen'] = prior.get('first_seen', meta['fetched_at'])
                r['fetched_at'] = meta['fetched_at']
                r['seen_in_latest_list'] = True
                rows[r['url']] = r
            current = {r['url'] for r in found}
            for r in rows.values():
                if r['school'] == cfg['school'] and r['dept'] == cfg['dept'] and r['url'] not in current:
                    r['seen_in_latest_list'] = False
            sources[key] = {'url': cfg['url'], 'fetched_at': meta['fetched_at'],
                            'last_attempt': checked_at, 'signature': fingerprint, 'count': len(found), 'error': None}
            print(f'{key}: {len(found)} 通知 | cache={hit}')
        except Exception as e:
            failed += 1
            sources.setdefault(key, {}).update(url=cfg['url'], last_attempt=checked_at, error=str(e)[:500])
            print(f'{key}: ERROR {e}', file=sys.stderr)
    result = {'scope': 'configured-official-columns', 'checked_at': checked_at,
              'sources': sources, 'notices': sort_notices(rows.values()),
              'summary': {'source_count': len(cfgs), 'sources_ok': len(cfgs)-failed,
                          'sources_error': failed, 'changed_count': changes, 'notice_count': len(rows)}}
    writer(output, result)
    print(f'栏目变化 {changes} | 失败 {failed} | 候选通知 {len(rows)}；截止日期与入学年份待人工核验')
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--config', type=Path, default=ROOT / 'sites/notices.yaml')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/notices.json')
    args = ap.parse_args()
    cfgs = yaml.safe_load(args.config.read_text(encoding='utf-8'))['targets']
    return int(collect(cfgs, args.output, refresh=args.refresh)['summary']['sources_error'] > 0)


if __name__ == '__main__':
    sys.exit(main())

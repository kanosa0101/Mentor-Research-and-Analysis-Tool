"""Evidence-bound issue repair and recurring checks for public mentor records."""
import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
import yaml
from bs4 import BeautifulSoup, UnicodeDammit

from crawler import legacy_refresh
from crawler.email_util import normalize_email
from crawler.opportunity_monitor import atomic_json, output_lock

EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def load_yaml(path):
    return yaml.load(path.read_text(encoding='utf-8'), Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))


def fetch_source(source, timeout=15):
    with requests.Session() as session:
        session.trust_env = False
        response = session.request(source.get('method', 'GET'), source['url'], data=source.get('data'),
                                   timeout=timeout, headers={'User-Agent': 'Mozilla/5.0 (public faculty source verification)'})
        response.raise_for_status()
        if response.status_code != 200 or len(response.content) > 3_000_000:
            raise ValueError('来源状态或体积异常')
        return response.content


class Sources:
    def __init__(self, root, fetcher, stamp):
        self.folder = root / 'cache/mentor_quality/evidence'
        self.folder.mkdir(parents=True, exist_ok=True)
        self.fetcher, self.stamp, self.cache, self.used = fetcher, stamp, {}, []
        self.day = datetime.fromisoformat(stamp).astimezone(timezone(timedelta(hours=8))).date().isoformat()

    def read(self, url, data=None):
        source = {'url': url, **({'method': 'POST', 'data': data} if data else {})}
        key = json.dumps(source, sort_keys=True)
        if key not in self.cache:
            try:
                raw = self.fetcher(source)
                raw = raw.encode('utf-8') if isinstance(raw, str) else raw
                digest = hashlib.sha256(raw).hexdigest()
                (self.folder / (digest + '.body')).write_bytes(raw)
                self.cache[key] = raw, {'url': url, 'sha256': digest, 'fetched_at': self.stamp,
                                        **({'request': data} if data else {})}
            except Exception as error:
                self.cache[key] = error, {'url': url, 'fetched_at': self.stamp, 'error': str(error)[:500]}
        raw, evidence = self.cache[key]
        if evidence not in self.used:
            self.used.append(evidence)
        if isinstance(raw, Exception):
            raise raw
        text = UnicodeDammit(raw).unicode_markup
        if text is None:
            raise ValueError('无法解码官方正文')
        return raw, text


def alternatives(original, cfg, sources):
    """Discover only named links on configured official directories, then verify email in detail."""
    urls = []
    seeds = cfg.get('profile_lookup_urls', [])
    hosts = {urlsplit(url).hostname for url in seeds}
    for seed in seeds:
        try:
            _, html = sources.read(seed)
        except Exception:
            continue
        for anchor in BeautifulSoup(html, 'html.parser').select('a[href]'):
            name = re.sub(r'[（(][^）)]+[）)]', '', anchor.get_text(' ', strip=True)).split()
            url = urljoin(seed, anchor['href'])
            parts = urlsplit(url)
            if (name and name[0] == original['name'] and parts.scheme == 'https' and
                    parts.hostname in hosts and re.search(r'/page\.htm$', parts.path) and
                    url != original['detail_url'] and url not in [row[0] for row in urls]):
                urls.append((url, seed))
    if len(urls) > 8:
        raise ValueError('同名官方候选过多，不能自动确认身份')
    return urls


def profile(root, original, cfg, sources, *, allow_alternative=True, raw_title=False):
    hook = legacy_refresh.load_hook(root, cfg)
    parse_cfg = copy.deepcopy(cfg)
    if raw_title:
        parse_cfg.pop('title_conflicts', None)
        parse_cfg.pop('_title_conflict_names', None)
    candidates = [(original['detail_url'], None)]
    expanded = False
    if allow_alternative and '-backend.nankai.edu.cn' in (urlsplit(original['detail_url']).hostname or ''):
        preferred = alternatives(original, cfg, sources)
        if preferred:
            candidates = preferred + candidates
            expanded = True
    errors = []
    index = 0
    while index < len(candidates):
        url, directory = candidates[index]
        index += 1
        try:
            raw, html = sources.read(url)
            parsed = hook.parse_detail(parse_cfg, html, url)
            if directory:
                if isinstance(directory, dict):
                    head = BeautifulSoup(html, 'html.parser').select_one('.js-top .info h2')
                    if head is None or head.get_text(strip=True) != original['name']:
                        raise ValueError('官方同一教师中文链接的个人姓名未确认')
                else:
                    expected = normalize_email(original.get('email'))
                    if (not expected or parsed.get('name') != original['name'] or
                            str(normalize_email(parsed.get('email'))).lower() != expected.lower()):
                        raise ValueError('备用官方详情未通过姓名和邮箱双重身份匹配')
            candidate = dict(original, detail_url=url)
            updated, changed, checked = legacy_refresh.merge_profile(candidate, parsed, raw,
                sources.day)
            if directory:
                updated['profile_url'] = url
                for field in ('detail_url', 'profile_url'):
                    updated.setdefault('provenance', {})[field] = dict(origin='crawled', source=directory['url'] if isinstance(directory, dict) else directory,
                        fetched_at=sources.day, confidence='auto')
                changed += ['detail_url', 'profile_url']
            return updated, parsed, changed, checked
        except Exception as error:
            errors.append(str(error)[:300])
            if index == 1 and allow_alternative and not expanded:
                expanded = True
                # Follow an actual language link for the same official person path;
                # English pinyin or arbitrary metadata never establishes identity.
                if urlsplit(original['detail_url']).hostname == 'faculty.hust.edu.cn':
                    try:
                        _, page = sources.read(original['detail_url'])
                        source = urlsplit(original['detail_url'])
                        prefix = '/' + source.path.strip('/').split('/')[0] + '/'
                        for anchor in BeautifulSoup(page, 'html.parser').select('a[href]'):
                            target = urljoin(original['detail_url'], anchor['href'])
                            parts = urlsplit(target)
                            if (anchor.get_text(strip=True) == '中文' and parts.hostname == source.hostname and
                                    parts.scheme in ('http', 'https') and parts.path.startswith(prefix + 'zh_CN/') and
                                    target not in [value[0] for value in candidates]):
                                candidates.append((target, {'url': original['detail_url']}))
                    except Exception:
                        pass
                candidates.extend(alternatives(original, cfg, sources))
    raise ValueError('；'.join(dict.fromkeys(errors))[:1200])


def write_profile(path, before, updated):
    with output_lock(path):
        if load_yaml(path) != before:
            raise ValueError('核验期间导师记录已变化，未覆盖')
        legacy_refresh.write_yaml(path, updated)


def ensure_issue(issues, kind, ref, message, day):
    if any(row['kind'] == kind and row['ref'] == ref for row in issues):
        return 0
    issues.append(dict(kind=kind, ref=ref, message=message, first_seen=day, resolved=False,
                       reviewed=None, review_note=None, review_history=[]))
    return 1


def newer_attempt(attempt, checked):
    if not attempt:
        return False
    try:
        values = []
        for value in (attempt, checked or '1970-01-01T00:00:00+00:00'):
            parsed = datetime.fromisoformat(value)
            values.append(parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc))
        return values[0] > values[1]
    except (TypeError, ValueError):
        return False


def seed_issues(root, now):
    """Turn real refresh failures and ambiguous public registrations into persistent work."""
    created = 0
    state = root / 'cache/legacy_refresh/state.json'
    records = json.loads(state.read_text(encoding='utf-8')).get('records', {}) if state.exists() else {}
    units = defaultdict(list)
    for key, record in records.items():
        parts = key.split('/')
        if len(parts) != 4 or parts[0] != 'professor' or record.get('status') != 'error':
            continue
        path = root / 'data/professors' / parts[1] / parts[2] / parts[3]
        if path.exists() and load_yaml(path).get('detail_url') == record.get('source_url'):
            units[(parts[1], parts[2])].append((Path(parts[3]).stem, record))
    for folder in (root / 'data/professors/nudt').glob('*'):
        if folder.is_dir():
            units.setdefault(('nudt', folder.name), [])
    for (school, dept), failures in units.items():
        path = root / 'data/issues' / f'{school}-{dept}.yaml'
        path.parent.mkdir(parents=True, exist_ok=True)
        with output_lock(path):
            issues = load_yaml(path) or [] if path.exists() else []
            for ref, record in failures:
                created += ensure_issue(issues, 'fetch_or_parse_error', ref, record.get('error', '来源读取失败'), now.date().isoformat())
                issue = next(i for i in issues if i['kind'] == 'fetch_or_parse_error' and i['ref'] == ref)
                automatic = issue.get('automatic_check') or {}
                if (issue.get('resolved') and not issue.get('reviewed') and automatic.get('status') == 'resolved' and
                        newer_attempt(record.get('last_attempt'), automatic.get('checked_at'))):
                    issue['resolved'] = False
            if school == 'nudt':
                people = [load_yaml(p) for p in (root / 'data/professors' / school / dept).glob('*.yaml')]
                by_name, by_email = defaultdict(list), defaultdict(list)
                for person in people:
                    by_name[person['name']].append(person)
                    match = EMAIL.search(person.get('bio_raw') or '')
                    if match:
                        by_email[match[0].lower()].append(person)
                for name, group in by_name.items():
                    if len({p['detail_url'] for p in group}) > 1:
                        created += ensure_issue(issues, 'duplicate_public_registration', name,
                            '同名存在多个官方登记URL，尚未取得人员唯一标识；保留原记录，不能按姓名合并。', now.date().isoformat())
                shared = {email: sorted({p['name'] for p in group}) for email, group in by_email.items()
                          if len({p['name'] for p in group}) > 1}
                for email, names in shared.items():
                    for person in by_email[email]:
                        created += ensure_issue(issues, 'shared_public_contact', person['slug'],
                            f'不同姓名的官方简介共享邮箱{email}，不能确认本人独立邮箱。', now.date().isoformat())
                cfg_path = root / 'sites' / school / (dept + '.yaml')
                cfg = load_yaml(cfg_path)
                if shared and cfg.get('shared_public_contacts') != shared:
                    cfg['shared_public_contacts'] = shared
                    legacy_refresh.write_yaml(cfg_path, cfg)
            legacy_refresh.write_yaml(path, issues)
    return created


def inspect_issue(root, unit, issue, sources):
    school, dept = unit.split('/')
    cfg = load_yaml(root / 'sites' / school / (dept + '.yaml'))
    folder = root / 'data/professors' / school / dept
    path = folder / (issue['ref'] + '.yaml')
    kind = issue['kind']
    if kind in ('fetch_or_parse_error', 'unknown_detail_field', 'shared_public_contact'):
        original = load_yaml(path)
        if kind == 'unknown_detail_field':
            titles, failed, own = set(), 0, None
            options = [(original['detail_url'], None)] + alternatives(original, cfg, sources)
            for url, _ in options:
                try:
                    updated, parsed, changed, checked = profile(root, dict(original, detail_url=url), cfg, sources,
                                              allow_alternative=False, raw_title=True)
                    if url == original['detail_url']:
                        own = updated, changed, checked
                    if parsed.get('title'):
                        titles.add(parsed['title'])
                except Exception:
                    failed += 1
            if len(titles) == 1 and not failed and len(options) > 1 and own and own[0].get('title') in titles:
                write_profile(path, original, own[0])
                return dict(status='resolved', reason='全部已知官方详情的明确职称现已一致',
                            observed_titles=sorted(titles), changed_fields=own[1], checked_fields=own[2])
            return dict(status='pending', reason='官方职称仍有冲突、不可读页面或缺少充分统一依据，保留未知',
                        observed_titles=sorted(titles), unavailable_pages=failed)
        updated, parsed, changed, checked = profile(root, original, cfg, sources)
        if kind == 'shared_public_contact':
            # Refresh the complete conflict group, not only one current record.
            names = next((names for names in cfg.get('shared_public_contacts', {}).values() if original['name'] in names), [])
            for other in folder.glob('*.yaml'):
                person = load_yaml(other)
                if person['name'] in names and person['slug'] != original['slug']:
                    profile(root, person, cfg, sources, allow_alternative=False)
            write_profile(path, original, updated)
            return dict(status='pending', reason='官方登记仍共享联系方式；撤回自动个人邮箱，保留原文并继续复检',
                        changed_fields=changed, checked_fields=checked, personal_email_withheld=bool(parsed.get('_rejected_email')))
        write_profile(path, original, updated)
        return dict(status='resolved', reason='当前官方详情身份及字段解析通过', changed_fields=changed,
                    checked_fields=checked, previous_source=original['detail_url'], current_source=updated['detail_url'])
    if kind == 'duplicate_public_registration':
        people = [load_yaml(path) for path in folder.glob('*.yaml')]
        people = [person for person in people if person['name'] == issue['ref']]
        for person in people:
            profile(root, person, cfg, sources, allow_alternative=False)
        return dict(status='pending', reason='多个官方登记仍存在，缺人员唯一标识；不按同名合并或删除',
                    registrations=[person['slug'] for person in people])
    if kind == 'roster_count_mismatch' and school == 'seu' and dept == 'auto':
        params = {'siteId': 338, 'pageIndex': 1, 'rows': 50,
                  'conditions': json.dumps([{'field': 'published', 'value': '1', 'judge': '='}]),
                  'orders': json.dumps([{'field': 'letter', 'type': 'asc'}]),
                  'returnInfos': json.dumps([{'field': value, 'name': value} for value in
                                            ['title', 'exField1', 'degree', 'post', 'cnUrl', 'headerPic']]),
                  'articleType': 1, 'level': 1}
        rows, total, pages = [], None, 1
        while params['pageIndex'] <= pages:
            _, text = sources.read(urljoin(cfg['base_url'], '/_wp3services/generalQuery?queryObj=teacherHome'), params.copy())
            value = json.loads(text)
            if total is None:
                total, pages = int(value['total']), int(value['pageCount'])
            if not 1 <= pages <= 20 or int(value['total']) != total or int(value['pageCount']) != pages:
                raise ValueError('名单计数在分页间变化或页数异常')
            rows.extend(value['data'])
            params['pageIndex'] += 1
        unique = len({(row.get('title'), row.get('cnUrl')) for row in rows})
        complete = unique == len(rows) == total
        return dict(status='resolved' if complete else 'pending',
                    reason='实际分页数量与官网标称一致' if complete else '官方标称总数与实际公开分页仍不一致，不宣称全量',
                    reported=total, returned=len(rows), unique=unique, pages=pages)
    return dict(status='pending', reason='当前问题类型没有可证明的自动修复规则，保留并周期复检')


def run(root, *, limit=40, retry=False, units=(), fetcher=None, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec='seconds')
    state_path = root / 'cache/mentor_quality/state.json'
    with output_lock(state_path):
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'version': 1, 'records': {}}
        created = seed_issues(root, now)
        selected = []
        known = set()
        for path in sorted((root / 'data/issues').glob('*.yaml')):
            unit = path.stem.replace('-', '/', 1)
            for issue in load_yaml(path) or []:
                key = unit + '/' + issue['kind'] + '/' + issue['ref']
                known.add(key)
                previous = state['records'].get(key, {})
                if issue.get('reviewed') or (issue.get('resolved') and
                        (issue.get('automatic_check') or {}).get('status') != 'resolved'):
                    state['records'].pop(key, None)
                    continue
                if not issue.get('resolved') and (not previous or previous.get('status') == 'resolved'):
                    queued = dict(previous, id=key, kind=issue['kind'], ref=issue['ref'],
                        title=path.stem + ' · ' + issue['ref'] + ' · ' + issue['kind'],
                        original_message=issue['message'], status='pending', pending_since=stamp,
                        reason=('等待首次复核：' if not previous else '问题重新打开，等待复核：') + issue['message'],
                        next_check_at=stamp)
                    folder = root / 'data/professors' / unit
                    person_path = folder / (issue['ref'] + '.yaml')
                    if person_path.parent == folder and person_path.is_file():
                        url = load_yaml(person_path).get('detail_url')
                        if url:
                            queued['source_urls'] = {'profile': url}
                    state['records'][key] = previous = queued
                if units and unit not in units:
                    continue
                if (not retry and previous.get('next_check_at', '') > stamp and
                        bool(issue.get('resolved')) == (previous.get('status') == 'resolved')):
                    continue
                selected.append((previous.get('checked_at', ''), key, path, issue))
        state['records'] = {key: value for key, value in state['records'].items() if key in known}
        # Persist the whole observed queue before the request budget is applied.
        atomic_json(state_path, state)
        selected.sort(key=lambda row: (row[0], row[1]))
        sources = Sources(root, fetcher or fetch_source, stamp)
        results, reopened = [], 0
        for _, key, path, issue in selected[:limit]:
            sources.used = []
            try:
                result = inspect_issue(root, path.stem.replace('-', '/', 1), issue, sources)
            except Exception as error:
                result = dict(status='error', reason=str(error)[:1200])
            delay = timedelta(days=7) if result['status'] == 'resolved' else timedelta(hours=24)
            result.update(id=key, kind=issue['kind'], ref=issue['ref'], original_message=issue['message'],
                          checked_at=stamp, next_check_at=(now + delay).isoformat(timespec='seconds'),
                          evidence=copy.deepcopy(sources.used))
            previous = state['records'].get(key, {})
            result['title'] = path.stem + ' · ' + issue['ref'] + ' · ' + issue['kind']
            result['pending_since'] = (None if result['status'] == 'resolved' else
                previous.get('pending_since') if previous.get('status') in ('error', 'pending') and previous.get('pending_since') else stamp)
            result['last_success'] = stamp if result['status'] == 'resolved' else previous.get('last_success')
            with output_lock(path):
                issues = load_yaml(path) or []
                current = next(row for row in issues if row['kind'] == issue['kind'] and row['ref'] == issue['ref'])
                if current['message'] != issue['message'] or current.get('reviewed'):
                    result.update(status='pending', reason='核验期间台账或人工审阅已变化，未覆盖',
                        next_check_at=(now + timedelta(hours=24)).isoformat(timespec='seconds'),
                        pending_since=previous.get('pending_since') or stamp,
                        last_success=previous.get('last_success'))
                else:
                    was_resolved = current.get('resolved', False)
                    current['resolved'] = result['status'] == 'resolved'
                    reopened += int(was_resolved and not current['resolved'])
                    if (current.get('automatic_check') or {}).get('status') != result['status']:
                        current.setdefault('review_history', []).append({'date': stamp, 'automatic': True,
                            'state': result['status'], 'reason': result['reason'], 'evidence': result['evidence']})
                    current['automatic_check'] = result
                    legacy_refresh.write_yaml(path, issues)
            state['records'][key] = result
            results.append(result)
            atomic_json(state_path, state)
        active = [row for path in (root / 'data/issues').glob('*.yaml') for row in load_yaml(path) or []
                  if not row.get('resolved') and not row.get('reviewed')]
        report = dict(version=1, checked_at=stamp, attempted=len(results), created=created, reopened=reopened,
                      resolved=sum(row['status'] == 'resolved' for row in results),
                      pending=sum(row['status'] == 'pending' for row in results),
                      error=sum(row['status'] == 'error' for row in results), active=len(active),
                      overdue=sum(row.get('first_seen', stamp[:10]) < (now - timedelta(days=7)).date().isoformat() for row in active),
                      results=results)
        atomic_json(root / 'cache/mentor_quality/latest.json', report)
        return report

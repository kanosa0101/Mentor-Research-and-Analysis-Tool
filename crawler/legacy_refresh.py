"""Bounded public-data refresh; source access never rewrites a human review date."""
import copy
import hashlib
import importlib.util
import itertools
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
import yaml
from bs4 import BeautifulSoup, UnicodeDammit

from crawler import admissions_util, mentor_direction_review
from crawler.email_util import normalize_email
from crawler.model import Professor
from crawler.opportunity_monitor import atomic_json, output_lock
from crawler.title_util import normalize_title

FIELDS = ('title', 'supervisor', 'subjects', 'email', 'homepage', 'photo_url',
          'phone', 'office_address', 'bio_raw', 'research_direction_raw', 'institutes')


def fetch_source(source, timeout=20):
    if source.get('official_scope'):
        from crawler.source_discovery import fetch_html
        from crawler.mentor_recovery import content_types
        pdf = source.get('official_pdf', False)
        return fetch_html(source['url'],source['official_scope'],allow_pdf=pdf,
                          accepted_types=('application/pdf',) if pdf else content_types(source['url']))
    with requests.Session() as session:
        session.trust_env = False
        response = session.request(source.get('method', 'GET'), source.get('api') or source['url'],
                                   json=source.get('json'), timeout=timeout,
                                   headers={'User-Agent': 'Mozilla/5.0 (public data refresh)'})
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Source did not return HTTP 200')
        if (metadata := source.get('_response_metadata')) is not None:
            metadata.update(requested_url=source['url'], final_url=response.url, status=response.status_code,
                            redirected=bool(response.history), observed_utc=datetime.now(timezone.utc).isoformat())
        return response.content


def write_yaml(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def ordinary_profile_fields(cfg, parsed):
    if cfg.get('contact_hook_only'):
        return {key: value for key, value in parsed.items() if key not in ('email', '_rejected_email')}
    return parsed


def merge_profile(original, parsed, body, day, *, verified_sources=()):
    soup = BeautifulSoup(body, 'html.parser')
    text = ''.join(soup.get_text().split())
    names = []
    if urlsplit(original['detail_url']).hostname == 'faculty.hust.edu.cn':
        from sites.hust_profile import identity_names
        names = identity_names(soup)
    if parsed.get('name') and ''.join(parsed['name'].split()) != ''.join(original['name'].split()):
        raise ValueError('详情明确姓名与原记录不符，保留旧记录')
    if (''.join(original['name'].split()) not in text and original['name'] not in names and
            parsed.get('_verified_roster_name') != original['name']):
        raise ValueError('导师姓名未出现在返回正文，保留旧记录')
    parsed = dict(parsed)
    if not parsed.get('research_direction_raw') and parsed.get('research_directions'):
        parsed['research_direction_raw'] = '、'.join(parsed['research_directions'])
    if parsed.get('research_direction_raw'):
        from sites.profile_fields import clean_research
        parsed['research_direction_raw']=clean_research(parsed['research_direction_raw'])
    if parsed.get('institute_from_detail'):
        parsed['institutes'] = list(dict.fromkeys(original.get('institutes', []) + parsed['institute_from_detail']))
    if parsed.get('email'):
        parsed['email'] = normalize_email(parsed['email'])
    if parsed.get('title'):
        parsed['title'], _ = normalize_title(parsed['title'])
    if not any(parsed.get(k) for k in FIELDS):
        raise ValueError('未解析出可用详情字段，保留旧记录')
    result = copy.deepcopy(original)
    provenance = result.setdefault('provenance', {})
    changed = []
    checked = []
    sources = {row['url']: row for row in verified_sources
               if row.get('url') and row.get('sha256') and row.get('fetched_at')}
    from crawler.mentor_fields import secondary_email_source
    from crawler.mentor_recovery import personal_email
    secondary_email = secondary_email_source(original)
    if (parsed.get('_rejected_email') and
            str(result.get('email', '')).lower() == parsed['_rejected_email'].lower() and
            not secondary_email and
            provenance.get('email', {}).get('origin') != 'manual'):
        result.pop('email', None)
        provenance.pop('email', None)
        changed.append('email')
        checked.append('email')
    for field in FIELDS:
        value = parsed.get(field)
        if not value or provenance.get(field, {}).get('origin') == 'manual':
            continue
        source = (parsed.get('_field_sources') or {}).get(field)
        if source and source not in sources:
            continue  # A parser's URL alone does not establish fetched evidence.
        previous = provenance.get(field, {})
        same_value = result.get(field) == value
        if (field == 'email' and secondary_email and not same_value and
                not (source and personal_email(value) and (parsed.get('_verified_roster_name') or parsed.get('name')) == original['name'])):
            continue
        if result.get(field) != value:
            changed.append(field)
        result[field] = value
        if source:
            source_day = datetime.fromisoformat(sources[source]['fetched_at']).astimezone(
                timezone(timedelta(hours=8))).date().isoformat()
            provenance[field] = dict(origin='crawled', source=source, fetched_at=source_day, confidence='auto')
        elif not (same_value and previous.get('source') and previous['source'] != original['detail_url']):
            provenance[field] = dict(origin='crawled', source=original['detail_url'], fetched_at=day, confidence='auto')
        checked.append(field)
    if not checked:
        raise ValueError('可解析字段均为人工维护，本轮不改来源日期')
    result['last_fetched'] = day
    result['last_parsed'] = day
    if result.get('status') != 'verified':
        result['status'] = 'enriched'
    # last_verified is a separate historical assertion, not the transport timestamp.
    Professor.model_validate(result)
    return result, changed, checked


def load_hook(root, cfg):
    for directory in (root / 'sites' / cfg['school'], root / 'sites'):
        path = directory / (cfg['hook'] + '.py')
        if path.exists():
            spec = importlib.util.spec_from_file_location('legacy_' + cfg['hook'], path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise ValueError('未找到详情解析器')


def run(root, *, kind='all', limit=30, units=(), workers=4, timeout=20, retry=False, fetcher=None, now=None, priority_units=()):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec='seconds')
    day = now.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    cache = root / 'cache/legacy_refresh'
    state_path = cache / 'state.json'
    fetcher = fetcher or (lambda source: fetch_source(source, timeout))
    with output_lock(state_path):
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'version': 1, 'records': {}}
        records = state['records']
        results = []
        signatures = {}
        quality_path = root / 'cache/mentor_quality/state.json'
        quality_records = json.loads(quality_path.read_text(encoding='utf-8')).get('records', {}) if quality_path.exists() else {}
        recovery_signatures = {}

        def signature(key):
            if not key.startswith('professor/'):
                return None
            parts = key.split('/')[1:]
            unit = '/'.join(parts[:2])
            if unit not in signatures:
                cfg_path = root / 'sites' / parts[0] / (parts[1] + '.yaml')
                raw = cfg_path.read_bytes() if cfg_path.exists() else b''
                try:
                    cfg = yaml.safe_load(raw) or {}
                    if not isinstance(cfg, dict):
                        cfg = {}
                except yaml.YAMLError:
                    cfg = {}
                from crawler.mentor_recovery import parser_source
                cfg.setdefault('school',parts[0])
                raw += parser_source(root,cfg)
                signatures[unit] = hashlib.sha256(raw).hexdigest()
            return signatures[unit]

        def due(key):
            if key.startswith('professor/') and not retry:
                from crawler import mentor_recovery
                school, dept, filename = key.split('/')[1:]
                unit = school + '/' + dept
                recovery = quality_records.get(unit + '/fetch_or_parse_error/' + Path(filename).stem, {})
                if recovery.get('status') in ('error', 'pending') and recovery.get('next_check_at', '') > stamp:
                    cfg_path = root / 'sites' / school / (dept + '.yaml')
                    if cfg_path.exists():
                        if unit not in recovery_signatures:
                            recovery_signatures[unit] = mentor_recovery.signature(root, yaml.safe_load(cfg_path.read_text(encoding='utf-8')))
                        original = yaml.safe_load((root / 'data/professors' / school / dept / filename).read_text(encoding='utf-8'))
                        issue_source = (recovery.get('source_urls') or {}).get('profile') or records.get(key, {}).get('source_url')
                        if (recovery.get('repair_signature') == recovery_signatures[unit] and
                                original.get('detail_url') == issue_source):
                            return False
            if records.get(key, {}).get('status') == 'manual_required' and not retry:
                previous = records[key]
                if previous.get('parser_signature') != signature(key):
                    return True
                attempted = previous.get('last_attempt')
                return not attempted or (now - datetime.fromisoformat(attempted)).total_seconds() >= 7 * 86400
            attempted = records.get(key, {}).get('last_attempt')
            return retry or not attempted or (now - datetime.fromisoformat(attempted)).total_seconds() >= 86400

        def record(key, value):
            if key.startswith('professor/'):
                value = dict(value, parser_signature=signature(key))
            records[key] = dict(records.get(key, {}), **value, last_attempt=stamp)
            results.append(dict(id=key, **records[key]))
            atomic_json(state_path, state)

        def evidence(key, raw):
            digest = hashlib.sha256(raw).hexdigest()
            folder = cache / 'evidence'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (digest + '.body')).write_bytes(raw)
            return digest

        if kind in ('all', 'policies'):
            data = yaml.safe_load((root / 'data/admissions.yaml').read_text(encoding='utf-8'))
            path = root / 'data/admissions_checks.json'
            checks = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            sources = sorted(data['sources'].items(), key=lambda pair: (
                0 if retry and records.get('policy/' + pair[0], {}).get('status') == 'error' else 1,
                records.get('policy/' + pair[0], {}).get('last_attempt', ''), pair[0]))
            if units:
                allowed = {sid for p in data['policies'] if p['school'] + '/' + p['dept'] in units for sid in p['review_hashes']}
                sources = [(sid, src) for sid, src in sources if sid in allowed]
            selected = [(sid, src) for sid, src in sources if due('policy/' + sid)][:limit]
            def check(pair):
                sid, src = pair
                result = dict(checks.get(sid, {}), last_attempt=day)
                try:
                    raw = fetcher(src)
                    digest = admissions_util.fingerprint(raw, src)
                    raw_hash = evidence(sid, raw)
                    result.update(status='ok', hash=digest, last_success=day, cached=False, error=None)
                    return sid, result, {'status': 'ok', 'source_url': src['url'], 'last_success': stamp, 'raw_sha256': raw_hash, 'content_sha256': digest}
                except Exception as error:
                    result.update(status='error', error=str(error)[:500])
                    return sid, result, {'status': 'error', 'source_url': src['url'], 'error': str(error)[:500]}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for future in as_completed([pool.submit(check, pair) for pair in selected]):
                    sid, observation, report = future.result()
                    checks[sid] = observation
                    admissions_util.validate_checks(checks, data['sources'])
                    atomic_json(path, checks)
                    record('policy/' + sid, report)

        if kind in ('all', 'professors'):
            folders = sorted((root / 'data/professors').glob('*/*'))
            batches = [sorted(folder.glob('*.yaml')) for folder in folders
                       if not units or '/'.join(folder.parts[-2:]) in units]
            paths = [path for group in itertools.zip_longest(*batches) for path in group if path]
            paths.sort(key=lambda path: (
                0 if retry and records.get('professor/' + '/'.join(path.parts[-3:]), {}).get('status') in ('error', 'manual_required') else 1,
                records.get('professor/' + '/'.join(path.parts[-3:]), {}).get('last_attempt', '')))
            pending = [path for path in paths if due('professor/' + '/'.join(path.parts[-3:]))]
            # Reserve at most half the batch for current applications; keep a fair full-library rotation.
            priority = [path for path in pending if '/'.join(path.parts[-3:-1]) in priority_units][:limit // 2]
            from crawler import mentor_fields
            gaps=mentor_fields.read(root).get('records',{})
            field_priority=[path for path in pending if path not in priority and any(
                field.get('status') in ('pending','error') and (not field.get('next_check_at') or field['next_check_at']<=stamp)
                for field in gaps.get('/'.join(path.parts[-3:-1])+'/'+path.stem,{}).get('fields',{}).values())][:limit//4]
            selected = priority + field_priority
            selected += [path for path in pending if path not in selected][:limit-len(selected)]
            hooks = {}
            for path in selected:
                key = 'professor/' + '/'.join(path.parts[-3:])
                original_bytes = path.read_bytes()
                original = yaml.safe_load(original_bytes)
                parsed={};raw=None;raw_hash=None;cfg=None
                try:
                    unit = original['school'] + '/' + original['dept']
                    if unit not in hooks:
                        cfg = yaml.safe_load((root / 'sites' / original['school'] / (original['dept'] + '.yaml')).read_text(encoding='utf-8'))
                        hooks[unit] = cfg, None if cfg.get('roster_only') else load_hook(root, cfg)
                    cfg, hook = hooks[unit]
                    if cfg.get('roster_only') or not callable(getattr(hook, 'parse_detail', None)):
                        record(key, {'status': 'manual_required', 'source_url': original['detail_url'],
                                     'reason': '当前配置仅支持名单或未提供详情解析器；需维护者处理，修复后用 --retry 复检。',
                                     'error': None})
                        continue
                    observe = mentor_direction_review.enabled(unit, cfg)
                    response = {}
                    source = {'url': original['detail_url']}
                    if observe:
                        source['_response_metadata'] = response
                    raw = fetcher(source)
                    raw_hash = evidence(key, raw)
                    html = UnicodeDammit(raw).unicode_markup
                    if not html:
                        raise ValueError('无法解码导师正文')
                    supplemental=[]
                    def read_source(url):
                        from crawler.mentor_recovery import profile_pdf
                        source = {'url':url,'official_scope':cfg.get('base_url') or original['detail_url']}
                        if profile_pdf(url,cfg):
                            source['official_pdf'] = True
                        body=fetcher(source)
                        digest=evidence(key,body)
                        supplemental.append(dict(url=url,sha256=digest,fetched_at=stamp))
                        text = '' if source.get('official_pdf') else UnicodeDammit(body).unicode_markup or ''
                        return body,text
                    parse_cfg = dict(cfg, _expected_name=original['name'], _read_source=read_source,
                                     _original_profile=original)
                    if observe:
                        parse_cfg['_observe_research_changes'] = True
                    parsed = hook.parse_detail(parse_cfg, html, original['detail_url'])
                    direction = (mentor_direction_review.capture(original, parsed.pop('_research_direction_observation', None),
                                                                 response, raw_hash, stamp) if observe else None)
                    parsed = ordinary_profile_fields(cfg, parsed)
                    # The contact task verifies a declared independent homepage
                    # by fetching the target before publishing it.
                    parsed = {key: value for key, value in parsed.items() if key != 'homepage'}
                    if direction and not any(parsed.get(field) for field in FIELDS):
                        updated, changed, checked = original, [], []
                    else:
                        updated, changed, checked = merge_profile(original, parsed, raw, day, verified_sources=supplemental)
                    if direction:
                        with output_lock(path):
                            if path.read_bytes() != original_bytes:
                                raise ValueError('核验期间导师记录已变化，未覆盖')
                            if updated != original:
                                write_yaml(path, updated)
                            direction['current'] = mentor_direction_review.registration(updated)
                    elif cfg.get('contact_hook_only'):
                        from crawler.mentor_quality import write_profile
                        write_profile(path, original, updated)
                    else:
                        write_yaml(path, updated)
                    report = {'status': 'ok', 'source_url': original['detail_url'], 'last_success': stamp,
                              'raw_sha256': raw_hash, 'supplemental_evidence':supplemental,
                              'changed_fields': changed, 'checked_fields': checked, 'error': None, 'reason': None}
                    if observe:
                        report['research_direction_observation'] = direction
                    record(key, report)
                    from crawler import mentor_fields,mentor_recovery
                    mentor_fields.observation(root,updated,parsed=parsed,source_sha256=raw_hash,fetched_at=stamp,now=now,
                                              parser_signature=mentor_recovery.signature(root,cfg),verified_sources=supplemental)
                except Exception as error:
                    record(key, {'status': 'error', 'source_url': original['detail_url'], 'error': str(error)[:500]})
                    from crawler import mentor_fields,mentor_recovery
                    mentor_fields.observation(root,original,parsed=parsed,source_sha256=raw_hash,fetched_at=stamp if raw_hash else None,
                                              now=now,error=error,parser_signature=mentor_recovery.signature(root,cfg) if cfg else None)
        report = {'version': 1, 'completed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'kind': kind,
                  'attempted': len(results), 'ok': sum(r['status'] == 'ok' for r in results),
                  'error': sum(r['status'] == 'error' for r in results),
                  'manual_required': sum(r['status'] == 'manual_required' for r in results), 'results': results}
        atomic_json(cache / 'latest.json', report)
        return report

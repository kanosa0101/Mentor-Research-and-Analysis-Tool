"""Discover official activity links without promoting them to reviewed opportunities."""
import copy
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from scripts.monitor_notices import parse_list

ACTIVITIES = ('冬令营', '夏令营', '预推免', '推免预报名', '暑期研修', '科研实践', '科研实习', '春闱计划', '科创计划', '深瞳计划', '创新实践', '暑期科学营')
EXCLUDED = ('中学生', '中小学', '青少年', '奥林匹克', '出国', '境外', '访学', '海外', '名单', '公示', '考核结果', '录取结果', '复试成绩公布', '活动总结')


def activity_title(title):
    recommendation = any(word in title for word in ('推免', '推荐免试')) and any(word in title for word in ('报名', '招收', '接收'))
    return (any(word in title for word in ACTIVITIES) or recommendation) and not any(word in title for word in EXCLUDED)


def fetch_source(config, timeout=25):
    """Read publicly configured GET/POST sources, with TLS checks and no cache fallback."""
    with requests.Session() as session:
        session.trust_env = False
        response = session.request('POST' if config.get('api') else 'GET',
                                   config.get('api') or config['url'],
                                   data=config.get('post'), timeout=timeout,
                                   headers={'User-Agent': 'Mozilla/5.0 (local admissions monitor)'})
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError(f'Expected HTTP 200, received {response.status_code}')
        if config.get('api'):
            content = response.json().get('content')
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Official API did not return list HTML')
            return content.encode('utf-8')
        return response.content


@contextmanager
def output_lock(output):
    """An OS lock is released on exit/crash; keep its inode to avoid unlink races."""
    path = Path(str(output) + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    if not path.stat().st_size:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        raise RuntimeError('已有机会监测运行中，请勿重复启动。') from error
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == 'nt':
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_previous(output):
    if not Path(output).exists():
        return {'candidates': [], 'sources': {}, 'opportunity_checks': {}}
    value = json.loads(Path(output).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not isinstance(value.get('candidates'), list) or not isinstance(value.get('sources'), dict):
        raise ValueError('监测文件格式错误，保留原文件；请先检查或另选输出路径。')
    return value


def run_once(configs, output, opportunities=None, *, fetcher=fetch_source, pdf_fetcher=None, now=None, interval_hours=6, lock=True):
    """Refresh atomically. lock=False is reserved for a caller holding output_lock."""
    with output_lock(output) if lock else nullcontext():
        return _run(configs, output, opportunities or [], fetcher, now, interval_hours, pdf_fetcher)


def _run(configs, output, opportunities, fetcher, now, interval_hours, pdf_fetcher):
    previous = read_previous(output)
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')
    rows = {row['url']: copy.deepcopy(row) for row in previous['candidates']}
    sources = copy.deepcopy(previous['sources'])
    active = {cfg['school'] + '/' + cfg['dept'] for cfg in configs}
    for key, source in sources.items():
        if key not in active:
            source['status'] = 'removed'
    new_count = baseline_count = 0
    for cfg in configs:
        key = cfg['school'] + '/' + cfg['dept']
        old = sources.get(key, {})
        source = dict(old, url=cfg['url'], unit=cfg.get('name', key), last_attempt=timestamp, new_count=0)
        baseline = not old.get('last_success') or old.get('url') != cfg['url']
        if old.get('url') and old['url'] != cfg['url']:
            source.update(last_success=None, count=0)
        try:
            notices = parse_list(fetcher(cfg), cfg)
            if not notices:
                raise ValueError('未解析出通知，可能是栏目变化或访问受限；保留上次候选。')
            found = [row for row in notices if activity_title(row['title'])]
            current_urls = {row['url'] for row in found}
            for row in rows.values():
                if row['source'] == cfg['url']:
                    row['seen_in_latest_list'] = row['url'] in current_urls
            for candidate in found:
                old_row = rows.get(candidate['url'], {})
                is_new = not old_row
                candidate.update(first_seen=old_row.get('first_seen', timestamp), last_seen=timestamp,
                                 seen_in_latest_list=True, source_state='ok',
                                 discovery_status=old_row.get('discovery_status', 'initial_snapshot' if baseline else 'discovered_later'))
                # Parse output is always unreviewed; title years are not admission years.
                rows[candidate['url']] = candidate
                if is_new and baseline:
                    baseline_count += 1
                elif is_new:
                    new_count += 1
                    source['new_count'] += 1
            source.update(status='ok', error=None, last_success=timestamp, count=len(found))
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            source.update(status='error', error=str(error)[:500])
            source.setdefault('last_success', None)
            source.setdefault('count', 0)
        sources[key] = source
    for row in rows.values():
        source = sources.get(row['school'] + '/' + row['dept'], {})
        row['source_state'] = source.get('status', 'removed') if row['source'] == source.get('url') else 'removed'
    checks = {}
    for opportunity in opportunities:
        if opportunity.get('source_state') not in ('verified', 'checked'):
            continue
        key = opportunity['id']
        old = previous.get('opportunity_checks', {}).get(key, {})
        expected = opportunity.get('source_sha256') or None
        check = dict(old, url=opportunity['source_url'], last_attempt=timestamp, expected_hash=expected)
        try:
            raw = fetcher({'url': opportunity['source_url']})
            digest = hashlib.sha256(raw.encode('utf-8') if isinstance(raw, str) else raw).hexdigest()
            same_content = False
            documents = opportunity.get('source_documents', [])
            if documents:
                from crawler.opportunity_extract import embedded_pdf_urls, pdf_source_version
                from crawler.opportunity_review import fetch_pdf
                urls = embedded_pdf_urls(raw, opportunity['source_url'])
                if set(urls) != {doc['url'] for doc in documents}:
                    check.update(status='changed', hash=digest, last_success=timestamp, error=None,
                                 document_change='PDF链接列表变化，须重新核验')
                    checks[key] = check
                    continue
                versions = [dict(url=doc['url'], sha256=hashlib.sha256((pdf_fetcher or fetch_pdf)(doc['url'], opportunity['source_url'])).hexdigest()) for doc in documents]
                content = pdf_source_version(raw, opportunity['source_url'], versions)
                same_content = content == opportunity.get('source_content_sha256')
                check.update(content_sha256=content, source_documents=versions)
            elif opportunity.get('source_content_sha256'):
                from crawler.opportunity_extract import document
                content = document(raw, opportunity['source_url'])['content_sha256']
                same_content = content == opportunity['source_content_sha256']
                check['content_sha256'] = content
            check.update(status='unbased' if not expected else 'unchanged' if same_content or (not documents and expected == digest) else 'changed',
                         hash=digest, last_success=timestamp, error=None)
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            check.update(status='error', error=str(error)[:500])
            check.setdefault('last_success', None)
        checks[key] = check
    completed = now or datetime.now(timezone.utc)
    errors = sum(sources[key]['status'] == 'error' for key in active)
    summary = dict(source_count=len(active), sources_ok=len(active) - errors, sources_error=errors,
                   candidate_count=len(rows), new_count=new_count, baseline_count=baseline_count,
                   changed_count=sum(check['status'] == 'changed' for check in checks.values()),
                   opportunity_errors=sum(check['status'] == 'error' for check in checks.values()))
    result = dict(version=1, checked_at=timestamp, completed_at=completed.isoformat(timespec='seconds'),
                  next_check_at=(completed + timedelta(hours=interval_hours)).isoformat(timespec='seconds'),
                  interval_hours=interval_hours,
                  status='error' if active and errors == len(active) else 'partial' if errors or summary['opportunity_errors'] else 'ok',
                  candidates=sorted(rows.values(), key=lambda row: (row['first_seen'], row['url']), reverse=True),
                  sources=sources, opportunity_checks=checks, summary=summary)
    atomic_json(output, result)
    return result

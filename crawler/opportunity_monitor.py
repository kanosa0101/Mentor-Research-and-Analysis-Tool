"""Discover official activity links without promoting them to reviewed opportunities."""
import copy
import hashlib
import html
import json
import os
import tempfile
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

from scripts.monitor_notices import parse_list, notice_hints

ACTIVITIES = ('冬令营', '冬季培训班', '冬季研修', '冬季研学', '冬季训练营', '夏令营', '预推免', '推免预报名', '暑期研修', '暑期研学', '暑期学校', '科研实践', '科研实习', '科研训练', '学术开放日', '春闱计划', '科创计划', '深瞳计划', '创新实践', '暑期科学营')
EXCLUDED = ('中学生', '中小学', '青少年', '奥林匹克', '出国', '境外', '访学', '海外', '名单', '公示', '考核结果', '录取结果', '复试成绩', '入营公告', '入营通知', '活动总结', '成功举办', '圆满落幕')


def activity_title(title):
    if title.strip() in (*ACTIVITIES, '科技创新实践课程', '夏令营报名', '冬令营报名'):
        return False
    recommendation = any(word in title for word in ('推免', '推荐免试')) and any(word in title for word in ('报名', '招收', '接收'))
    return (any(word in title for word in ACTIVITIES) or recommendation) and not any(word in title for word in EXCLUDED)


def fetch_source(config, timeout=25):
    """Read publicly configured GET/POST sources, with TLS checks and no cache fallback."""
    with requests.Session() as session:
        session.trust_env = False
        response = session.request('POST' if config.get('api') else 'GET',
                                   config.get('api') or config['url'],
                                   data=None if config.get('api_format') == 'cibr_articles' else config.get('post'),
                                   json=config.get('post') if config.get('api_format') == 'cibr_articles' else None, timeout=timeout,
                                   headers={'User-Agent': 'Mozilla/5.0 (local admissions monitor)'})
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError(f'Expected HTTP 200, received {response.status_code}')
        if config.get('api'):
            if config.get('api_format') == 'cibr_articles':
                return cibr_list(response.json())
            content = response.json().get('content')
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Official API did not return list HTML')
            return content.encode('utf-8')
        return response.content


def cibr_list(payload):
    """Adapt the public CIBR training endpoint; its internal type is not a cohort."""
    result_map = payload.get('retMap') if isinstance(payload, dict) else None
    rows = result_map.get('articleList') if isinstance(result_map, dict) else None
    if not isinstance(payload, dict) or payload.get('code') != 'success' or not isinstance(rows, list):
        raise ValueError('CIBR官方API未返回有效公告列表')
    import re
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not re.fullmatch('[a-f0-9]{32}', row['id']) or not isinstance(row.get('title'), str):
            raise ValueError('CIBR官方公告字段无效')
        result.append('<li><a href="https://cibr.ac.cn/detail/cibrPersonneladmissions/' + row['id'] + '">' +
                      html.escape(row['title']) + '</a><span class="date">' + html.escape(str(row.get('createTime', ''))[:10]) + '</span></li>')
    return ('<ul>' + ''.join(result) + '</ul>').encode()


def direct_notice(raw, config):
    from crawler.opportunity_extract import document, compact
    required, title = config.get('required_text'), config.get('title')
    if not isinstance(required, str) or not required.strip() or not isinstance(title, str) or not title.strip():
        raise ValueError('单页招募来源须配置title和required_text')
    text = document(raw, config['url'])['text']
    if compact(required) not in compact(text):
        raise ValueError('官方单页未匹配已登记招募原文，保留旧记录等待复核')
    return [dict(id=hashlib.sha256(config['url'].encode()).hexdigest()[:16], school=config['school'],
                 dept=config['dept'], unit=config.get('name', config['school']), title=title,
                 url=config['url'], source=config['url'], publication_date=None, **notice_hints(title))]


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


def source_key(config):
    return config.get('source_id') or config['school'] + '/' + config['dept']


def source_interval(config, opportunities, default=6):
    current = any(o.get('cycle') == 'current' and o.get('school_id') == config['school'] and o.get('dept_id') == config['dept'] for o in opportunities)
    hours = config.get('interval_hours', 1 if config.get('priority') == 'current' or current else 24 if config.get('priority') == 'historical' else default)
    if not isinstance(hours, (int, float)) or not 1 <= hours <= 168:
        raise ValueError('来源检查间隔须为1至168小时')
    return hours


def due(source, now):
    try:
        return datetime.fromisoformat(source['next_check_at']) <= now
    except (KeyError, ValueError, TypeError):
        return True


class DomainThrottle:
    """A run is sequential; limit repeated requests to the same official host."""
    def __init__(self, fetcher, seconds=1, clock=time.monotonic, sleep=time.sleep):
        self.fetcher, self.seconds, self.clock, self.sleep = fetcher, seconds, clock, sleep
        self.last = {}

    def __call__(self, config):
        self.wait(config.get('api') or config['url'])
        return self.fetcher(config)

    def wait(self, url):
        host = urlsplit(url).hostname
        delay = self.seconds - (self.clock() - self.last.get(host, -self.seconds))
        if delay > 0:
            self.sleep(delay)
        self.last[host] = self.clock()


def run_once(configs, output, opportunities=None, *, fetcher=fetch_source, pdf_fetcher=None, docx_fetcher=None, now=None, interval_hours=6, lock=True, scheduled=False, domain_interval=0):
    """Refresh atomically. lock=False is reserved for a caller holding output_lock."""
    with output_lock(output) if lock else nullcontext():
        return _run(configs, output, opportunities or [], DomainThrottle(fetcher, domain_interval), now, interval_hours, pdf_fetcher, scheduled, docx_fetcher)


def _run(configs, output, opportunities, fetcher, now, interval_hours, pdf_fetcher, scheduled, docx_fetcher):
    previous = read_previous(output)
    moment = now or datetime.now(timezone.utc)
    timestamp = moment.isoformat(timespec='seconds')
    rows = {row['url']: copy.deepcopy(row) for row in previous['candidates']}
    sources = copy.deepcopy(previous['sources'])
    active = {source_key(cfg) for cfg in configs}
    if len(active) != len(configs):
        raise ValueError('来源标识重复；同院系多个栏目须分别配置source_id')
    for key, source in sources.items():
        if key not in active:
            source['status'] = 'removed'
    new_count = baseline_count = attempted = skipped = 0
    for cfg in configs:
        key = source_key(cfg)
        old = sources.get(key, {})
        hours = source_interval(cfg, opportunities, interval_hours)
        if scheduled and old.get('url') == cfg['url'] and not due(old, moment):
            skipped += 1
            continue
        attempted += 1
        source = dict(old, url=cfg['url'], unit=cfg.get('name', key), last_attempt=timestamp, new_count=0)
        baseline = not old.get('last_success') or old.get('url') != cfg['url']
        if old.get('url') and old['url'] != cfg['url']:
            source.update(last_success=None, count=0)
        try:
            raw = fetcher(cfg)
            notices = direct_notice(raw, cfg) if cfg.get('mode') == 'direct_page' else parse_list(raw, cfg)
            if not notices:
                raise ValueError('未解析出通知，可能是栏目变化或访问受限；保留上次候选。')
            if not baseline and old.get('parsed_count', 0) >= 10 and len(notices) < old['parsed_count'] * .25:
                raise ValueError('栏目解析数量下降超过75%；保留上次候选并等待核验选择器或栏目分页。')
            found = notices if cfg.get('mode') == 'direct_page' else [row for row in notices if activity_title(row['title'])]
            current_urls = {row['url'] for row in found}
            for row in rows.values():
                if row['source'] == cfg['url']:
                    row['seen_in_latest_list'] = row['url'] in current_urls
            for candidate in found:
                old_row = rows.get(candidate['url'], {})
                is_new = not old_row
                candidate.update(first_seen=old_row.get('first_seen', timestamp), last_seen=timestamp,
                                 seen_in_latest_list=True, source_state='ok',
                                 monitor_source_id=key,
                                 discovery_status=old_row.get('discovery_status', 'initial_snapshot' if baseline else 'discovered_later'))
                # Routing hint is not proof of the organizer and never passes public admission.
                candidate['content_scope_hint'] = cfg.get('content_scope_hint', 'pending')
                # Parse output is always unreviewed; title years are not admission years.
                rows[candidate['url']] = candidate
                if is_new and baseline:
                    baseline_count += 1
                elif is_new:
                    new_count += 1
                    source['new_count'] += 1
            source.update(status='ok', error=None, last_success=timestamp, count=len(found), parsed_count=len(notices), consecutive_failures=0)
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            source.update(status='error', error=str(error)[:500])
            source.setdefault('last_success', None)
            source.setdefault('count', 0)
            source['consecutive_failures'] = old.get('consecutive_failures', 0) + 1
        delay = min(48, hours * 2 ** min(source.get('consecutive_failures', 0), 5))
        source.update(interval_hours=hours, next_check_at=(moment + timedelta(hours=delay)).isoformat(timespec='seconds'))
        sources[key] = source
    for row in rows.values():
        source = sources.get(row.get('monitor_source_id', row['school'] + '/' + row['dept']), {})
        row['source_state'] = source.get('status', 'removed') if row['source'] == source.get('url') else 'removed'
    checks = {}
    for opportunity in opportunities:
        if opportunity.get('source_state') not in ('verified', 'checked'):
            continue
        key = opportunity['id']
        old = previous.get('opportunity_checks', {}).get(key, {})
        if scheduled and old.get('url') == opportunity['source_url'] and not due(old, moment):
            checks[key] = old
            continue
        expected = opportunity.get('source_sha256') or None
        check = dict(old, url=opportunity['source_url'], last_attempt=timestamp, expected_hash=expected)
        try:
            raw = fetcher({'url': opportunity['source_url']})
            digest = hashlib.sha256(raw.encode('utf-8') if isinstance(raw, str) else raw).hexdigest()
            same_content = False
            documents = opportunity.get('source_documents', [])
            source_attachments = opportunity.get('source_attachments', [])
            if source_attachments:
                from crawler import opportunity_attachments as attachments
                attachments.validate_links(source_attachments, raw, opportunity['source_url'])
                def load_docx(url, source_url):
                    fetcher.wait(url)
                    return (docx_fetcher or attachments.fetch_docx)(url, source_url)
                verified = attachments.verify(source_attachments, opportunity['source_url'], load_docx)
                check['source_attachments'] = [dict(url=a['url'], sha256=a['sha256']) for a in verified]
            if documents:
                from crawler.opportunity_extract import embedded_pdf_urls, pdf_source_version
                from crawler.opportunity_review import fetch_pdf
                urls = embedded_pdf_urls(raw, opportunity['source_url'])
                if set(urls) != {doc['url'] for doc in documents}:
                    check.update(status='changed', hash=digest, last_success=timestamp, error=None,
                                 document_change='PDF链接列表变化，须重新核验')
                    checks[key] = check
                    check['next_check_at'] = (moment + timedelta(hours=1 if opportunity.get('cycle') == 'current' else 24)).isoformat(timespec='seconds')
                    continue
                versions = []
                for doc in documents:
                    fetcher.wait(doc['url'])
                    versions.append(dict(url=doc['url'], sha256=hashlib.sha256((pdf_fetcher or fetch_pdf)(doc['url'], opportunity['source_url'])).hexdigest()))
                content = pdf_source_version(raw, opportunity['source_url'], versions)
                if source_attachments:
                    content = attachments.source_version(content, source_attachments)
                same_content = content == opportunity.get('source_content_sha256')
                check.update(content_sha256=content, source_documents=versions)
            elif opportunity.get('source_content_sha256'):
                from crawler.opportunity_extract import document
                content = document(raw, opportunity['source_url'])['content_sha256']
                if source_attachments:
                    content = attachments.source_version(content, source_attachments)
                same_content = content == opportunity['source_content_sha256']
                check['content_sha256'] = content
            check.update(status='unbased' if not expected else 'unchanged' if same_content or (not documents and expected == digest) else 'changed',
                         hash=digest, last_success=timestamp, error=None)
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            check.update(status='error', error=str(error)[:500])
            from crawler.opportunity_attachments import AttachmentChanged
            if isinstance(error, AttachmentChanged):
                check.update(status='changed', hash=digest, last_success=timestamp, document_change=str(error))
            check.setdefault('last_success', None)
        check['consecutive_failures'] = old.get('consecutive_failures', 0) + 1 if check['status'] == 'error' else 0
        hours = 1 if opportunity.get('cycle') == 'current' else 24
        check['next_check_at'] = (moment + timedelta(hours=min(48, hours * 2 ** min(check['consecutive_failures'], 5)))).isoformat(timespec='seconds')
        checks[key] = check
    completed = now or datetime.now(timezone.utc)
    errors = sum(sources[key]['status'] == 'error' for key in active)
    summary = dict(source_count=len(active), sources_ok=len(active) - errors, sources_error=errors,
                   candidate_count=len(rows), new_count=new_count, baseline_count=baseline_count,
                   changed_count=sum(check['status'] == 'changed' for check in checks.values()),
                   opportunity_errors=sum(check['status'] == 'error' for check in checks.values()))
    summary.update(sources_attempted=attempted, sources_skipped=skipped,
                   overdue_sources=sum(due(sources[key], completed) for key in active))
    next_checks = [datetime.fromisoformat(s['next_check_at']) for s in [*(sources[k] for k in active), *checks.values()] if s.get('next_check_at')]
    result = dict(version=1, checked_at=timestamp, completed_at=completed.isoformat(timespec='seconds'),
                  last_fetch_at=max((s.get('last_attempt', '') for s in [*(sources[k] for k in active), *checks.values()]), default=None),
                  next_check_at=(min(next_checks) if scheduled and next_checks else completed + timedelta(hours=interval_hours)).isoformat(timespec='seconds'),
                  interval_hours=interval_hours,
                  status='error' if active and errors == len(active) else 'partial' if errors or summary['opportunity_errors'] else 'ok',
                  candidates=sorted(rows.values(), key=lambda row: (row['first_seen'], row['url']), reverse=True),
                  sources=sources, opportunity_checks=checks, summary=summary)
    atomic_json(output, result)
    return result

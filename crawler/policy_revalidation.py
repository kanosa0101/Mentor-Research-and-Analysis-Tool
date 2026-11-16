"""Reconfirm an unchanged, previously reviewed policy against fresh official evidence.

This does not rewrite policy facts or the human review date. A changed version,
unbound attachment, unreadable source, or missing quotation stays in the queue.
"""
import copy
import hashlib
import io
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin

import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader

from crawler import admissions_util
from crawler.legacy_refresh import fetch_source, write_yaml
from crawler.opportunity_monitor import atomic_json, output_lock

METHOD = 'unchanged-reviewed-policy-v1'
CST = timezone(timedelta(hours=8))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def policy_digest(policy):
    return digest({key: value for key, value in policy.items() if key != 'revalidation'})


def evidence_items(policy):
    for key, value in policy.get('fields', {}).items():
        yield 'fields.' + key, value
    if policy.get('applies_if'):
        yield 'applies_if', policy['applies_if']
    for index, event in enumerate(policy.get('events', [])):
        yield 'events.' + str(index), event
    for action in policy.get('material_actions', []):
        yield 'material_actions.' + action['id'] + '.instruction', action['instruction']
        if action.get('applies_if'):
            yield 'material_actions.' + action['id'] + '.applies_if', action['applies_if']


def validate_revalidation(value):
    keys = {'method', 'checked_at', 'policy_sha256', 'source_hashes', 'source_configs_sha256', 'evidence_count'}
    if not isinstance(value, dict) or set(value) != keys or value['method'] != METHOD:
        raise ValueError('政策自动再确认结构错误')
    timestamp = datetime.fromisoformat(value['checked_at'])
    if timestamp.tzinfo is None or timestamp.astimezone(CST).date() > datetime.now(CST).date():
        raise ValueError('政策自动再确认时间须有时区且不在未来')
    for key in ('policy_sha256', 'source_configs_sha256'):
        if not isinstance(value[key], str) or not re.fullmatch('[a-f0-9]{64}', value[key]):
            raise ValueError('政策自动再确认指纹错误')
    if (not isinstance(value['source_hashes'], dict) or not value['source_hashes'] or
            any(not isinstance(k, str) or not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}', v)
                for k, v in value['source_hashes'].items()) or
            type(value['evidence_count']) is not int or value['evidence_count'] < 1):
        raise ValueError('政策自动再确认缺少来源及逐项证据')


def valid_revalidation(policy, sources=None):
    value = policy.get('revalidation')
    try:
        validate_revalidation(value)
        return (value['policy_sha256'] == policy_digest(policy)
                and value['source_hashes'] == policy['review_hashes']
                and value['evidence_count'] == sum(1 for _ in evidence_items(policy))
                and (sources is None or value['source_configs_sha256'] ==
                     digest({sid: sources[sid] for sid in policy['review_hashes']})))
    except (ValueError, TypeError, KeyError):
        return False


def public_policy(policy, sources):
    """Only validated attestations enter browser payloads; facts remain unchanged."""
    result = copy.deepcopy(policy)
    if 'revalidation' in result and not valid_revalidation(result, sources):
        result.pop('revalidation')
        result['revalidation_invalid'] = True
    return result


def confirmation_date(policy, sources=None):
    if valid_revalidation(policy, sources):
        return datetime.fromisoformat(policy['revalidation']['checked_at']).astimezone(CST).date().isoformat()
    return ''


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def quote_match(quote, text):
    body, value = compact(text), compact(quote)
    if value and value in body:
        return 'contiguous'
    # Some reviewed evidence explicitly joins separate original paragraphs.
    # Retain every paragraph, preserve order, and never skip a missing fragment.
    parts = [compact(line) for line in quote.splitlines() if compact(line)]
    if len(parts) < 2 or any(len(part) < 3 for part in parts):
        return ''
    start = 0
    for part in parts:
        found = body.find(part, start)
        if found < 0:
            return ''
        start = found + len(part)
    return 'ordered_paragraphs'


def document(raw, source):
    if len(raw) > 20_000_000:
        raise ValueError('来源超过20MB上限，未自动再确认')
    if source['format'] == 'pdf':
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or len(reader.pages) > 100:
            raise ValueError('PDF加密或超过100页，未自动再确认')
        pages = [page.extract_text() or '' for page in reader.pages]
        if not ''.join(pages).strip():
            raise ValueError('PDF无可读取正文，不能代替OCR核验')
        return '\n'.join(pages), []
    if source['format'] in ('docx', 'doc', 'xlsx'):
        from crawler.opportunity_attachments import parse_office
        return parse_office(raw, source['format'])['text'], []
    if source['format'] == 'json':
        value = json.loads(raw)
        for key in source['selector'].split('/')[1:]:
            key = key.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
        if source.get('json_content') == 'structured':
            return json.dumps(value, ensure_ascii=False), []
        node = BeautifulSoup(value, 'html.parser')
    else:
        node = BeautifulSoup(raw, 'html.parser').select_one(source['selector'])
    if node is None:
        raise ValueError('未取得登记正文')
    for child in node.select('script,style'):
        child.decompose()
    attachments = [urljoin(source['url'], tag.get('href') or tag.get('src') or tag.get('data'))
                   for tag in node.select('a[href],iframe[src],object[data],embed[src]')
                   if re.search(r'\.(?:pdf|docx?|xlsx?|zip)(?:[?#]|$)|download\.jsp|/file/(?:common/)?download/',
                                unquote(tag.get('href') or tag.get('src') or tag.get('data')), re.I)]
    return node.get_text(' ', strip=True), list(dict.fromkeys(attachments))


def verify(policy, sources, fetched, stamp):
    reasons, located = [], []
    refs = policy['review_hashes']
    known_urls = {sources[sid]['url'] for sid in refs}
    for sid, expected in refs.items():
        result = fetched[sid]
        if result['status'] != 'ok':
            reasons.append({'kind': 'source_error', 'source_id': sid, 'message': result['error']})
        elif result['hash'] != expected:
            reasons.append({'kind': 'source_changed', 'source_id': sid, 'message': '当前原文或附件指纹与原核验版本不同'})
        else:
            for url in result['attachments']:
                if url not in known_urls:
                    reasons.append({'kind': 'unbound_attachment', 'source_id': sid, 'url': url,
                                    'message': '正文包含未绑定核验指纹的附件，不能自动延续原事实'})
    for path, item in evidence_items(policy):
        candidates = [sid for sid in item.get('source_ids', [policy['source_id']]) if fetched[sid]['status'] == 'ok']
        matches = {sid: quote_match(item['quote'], fetched[sid]['text']) for sid in candidates}
        matches = {sid: mode for sid, mode in matches.items() if mode}
        if not matches:
            if candidates:
                reasons.append({'kind': 'missing_quote', 'field': path, 'message': '原证据片段未在当前已登记来源中定位'})
        else:
            located.append({'field': path, 'source_ids': list(matches), 'match_modes': matches, 'locator': item['locator']})
    if reasons:
        return None, reasons, located
    value = dict(method=METHOD, checked_at=stamp, policy_sha256=policy_digest(policy),
                 source_hashes=copy.deepcopy(refs),
                 source_configs_sha256=digest({sid: sources[sid] for sid in refs}), evidence_count=len(located))
    validate_revalidation(value)
    return value, [], located


def run(root, *, limit=20, workers=4, timeout=15, force=False, policy_ids=(), fetcher=None, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    stamp, day = now.isoformat(timespec='seconds'), now.astimezone(CST).date().isoformat()
    cache = root / 'cache/policy_revalidation'
    state_path = cache / 'state.json'
    source_fetcher = fetcher or (lambda source: fetch_source(source, timeout))
    with output_lock(state_path):
        data_path = root / 'data/admissions.yaml'
        data = yaml.safe_load(data_path.read_text(encoding='utf-8'))
        initial = digest(data)
        checks_path = root / 'data/admissions_checks.json'
        checks = json.loads(checks_path.read_text(encoding='utf-8')) if checks_path.exists() else {}
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'version': 1, 'policies': {}}
        records = state['policies']

        def observation_signature(policy):
            return digest({'sources': {sid: data['sources'][sid] for sid in policy['review_hashes']},
                           'checks': {sid: {key: checks.get(sid, {}).get(key) for key in ('status', 'hash')}
                                      for sid in policy['review_hashes']}})

        def due(policy):
            if policy_ids and policy['id'] not in policy_ids:
                return False
            old = records.get(policy['id'], {})
            if force or old.get('policy_sha256') not in (None, policy_digest(policy)):
                return True
            if old.get('observation_signature') not in (None, observation_signature(policy)):
                return True
            next_attempt = old.get('next_attempt')
            if next_attempt:
                return now >= datetime.fromisoformat(next_attempt)
            if any(checks.get(sid, {}).get('status') != 'ok' or checks.get(sid, {}).get('hash') != expected
                   for sid, expected in policy['review_hashes'].items()):
                return True
            confirmed = confirmation_date(policy, data['sources']) or policy['reviewed_at']
            return (now.astimezone(CST).date() - datetime.fromisoformat(confirmed).date()).days >= 14

        selected = sorted((p for p in data['policies'] if due(p)),
                          key=lambda p: (records.get(p['id'], {}).get('next_attempt', ''),
                                         confirmation_date(p, data['sources']) or p['reviewed_at'], p['id']))[:limit]
        source_ids = sorted({sid for policy in selected for sid in policy['review_hashes']})

        def fetch_one(sid):
            source = data['sources'][sid]
            try:
                raw = source_fetcher(source)
                raw_hash = hashlib.sha256(raw).hexdigest()
                body, attachments = document(raw, source)
                content_hash = admissions_util.fingerprint(raw, source)
                folder = cache / 'evidence'
                folder.mkdir(parents=True, exist_ok=True)
                (folder / (raw_hash + '.body')).write_bytes(raw)
                return sid, dict(status='ok', hash=content_hash, raw_sha256=raw_hash, text=body, attachments=attachments)
            except Exception as error:
                return sid, dict(status='error', error=str(error)[:500])

        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = dict(pool.map(fetch_one, source_ids))
        for sid, result in fetched.items():
            check = dict(checks.get(sid, {}), last_attempt=day, cached=False)
            if result['status'] == 'ok':
                check.update(status='ok', hash=result['hash'], last_success=day, error=None)
            else:
                check.update(status='error', error=result['error'])
            checks[sid] = check
        rows = []
        for policy in selected:
            value, reasons, located = verify(policy, data['sources'], fetched, stamp)
            previous = records.get(policy['id'], {})
            # A failed real attempt invalidates the old automatic attestation.
            policy.pop('revalidation', None)
            if value:
                policy['revalidation'] = value
            status = 'confirmed' if value else 'retry' if any(r['kind'] == 'source_error' for r in reasons) else 'review_required'
            failures = 0 if value else previous.get('failures', 0) + 1
            hours = 14 * 24 if value else min(48, 2 ** min(failures, 6)) if status == 'retry' else 24
            row = dict(policy_id=policy['id'], title=policy['title'], status=status, first_seen=previous.get('first_seen', stamp),
                       last_attempt=stamp, next_attempt=(now + timedelta(hours=hours)).isoformat(timespec='seconds'),
                       failures=failures, policy_sha256=policy_digest(policy), human_reviewed_at=None if policy.get('review_method') == 'automatic_evidence' else policy['reviewed_at'],
                       observation_signature=observation_signature(policy),
                       source_urls={sid: data['sources'][sid]['url'] for sid in policy['review_hashes']},
                       source_results={sid: {k: v for k, v in fetched[sid].items() if k not in ('text', 'attachments')}
                                       for sid in policy['review_hashes']},
                       reasons=reasons, evidence=located)
            if value:
                row['last_success'] = stamp
            else:
                row['pending_since'] = (previous.get('pending_since') or previous.get('last_attempt') or stamp
                                        if previous.get('status') not in (None, 'confirmed') else stamp)
                if previous.get('last_success'):
                    row['last_success'] = previous['last_success']
            records[policy['id']] = row
            rows.append(row)
        # Another editor or publisher wins; do not replace a changed source file.
        with output_lock(data_path):
            current = yaml.safe_load(data_path.read_text(encoding='utf-8'))
            if digest(current) != initial:
                raise ValueError('政策目录在复核期间发生修改，未覆盖；下轮重新核验')
            if selected:
                write_yaml(data_path, data)
                admissions_util.validate_checks(checks, data['sources'])
                atomic_json(checks_path, checks)
            if selected or not state_path.exists():
                atomic_json(state_path, state)
        report = dict(version=1, checked_at=stamp, attempted=len(rows), sources_attempted=len(source_ids),
                      confirmed=sum(r['status'] == 'confirmed' for r in rows),
                      retry=sum(r['status'] == 'retry' for r in rows),
                      review_required=sum(r['status'] == 'review_required' for r in rows), results=rows)
        atomic_json(cache / 'latest.json', report)
        return report

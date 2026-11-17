"""Maintainer-only review queue; discovery never publishes an application claim.

sync creates editable item/quotes fields, preserving them on every refresh.
publish requires a reviewer, an explicitly acknowledged current source hash and
matching source quotations. These checks bind the human review to evidence;
they cannot establish that the human interpretation is correct.
"""
import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from crawler import opportunity_util as opportunities
from crawler import opportunity_extract as extraction
from crawler import opportunity_attachments as attachments
from crawler.opportunity_monitor import atomic_json, output_lock


def read_queue(path):
    if not Path(path).exists():
        return {'version': 1, 'drafts': []}
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('drafts'), list):
        raise ValueError('核验队列结构错误，未覆盖原文件')
    if len({d['id'] for d in data['drafts']}) != len(data['drafts']):
        raise ValueError('核验队列 ID 重复')
    return data


def triage(draft):
    value = draft.get('triage', {})
    if value.get('source_sha256') and value['source_sha256'] != draft.get('fetch', {}).get('sha256'):
        return dict(classification='unknown', reason='分流后原文版本变化，须重新核对适用范围')
    if value:
        return value
    from crawler.review_preflight import effective
    automatic = effective(draft)
    return automatic if automatic.get('classification') in ('historical', 'irrelevant') else {}


def apply_triage(queue_path, audit):
    """Explicit maintainer audit classification, separate from publishable claims."""
    rows = audit.get('candidates', [])
    if not isinstance(rows, list):
        raise ValueError('分流审计须包含candidates列表')
    with output_lock(queue_path):
        queue = read_queue(queue_path)
        by_id = {d['id']: d for d in queue['drafts']}
        by_url = {d['source_url']: d for d in queue['drafts']}
        updates = []
        for row in rows:
            if row.get('classification') not in ('current', 'historical', 'irrelevant', 'blocked', 'unknown') or not isinstance(row.get('reason'), str) or not row['reason'].strip():
                raise ValueError('每条分流须有有效分类和理由')
            draft = by_id.get(row.get('id')) or by_url.get(row.get('source_url'))
            if draft is None:
                continue
            if row.get('source_url') and row['source_url'] != draft['source_url']:
                raise ValueError('分流条目标识与官方来源不一致')
            if row.get('content_sha256') and row['content_sha256'] != draft.get('fetch', {}).get('content_sha256'):
                raise ValueError('分流审计与当前正文版本不一致，请重新核对后应用')
            if row.get('source_sha256') and row['source_sha256'] != draft.get('fetch', {}).get('sha256'):
                raise ValueError('分流审计与当前原文版本不一致，请重新核对后应用')
            updates.append((draft, dict(classification=row['classification'], reason=row['reason'][:2000],
                reviewed_at=audit.get('checked_at'), source_sha256=draft.get('fetch', {}).get('sha256'),
                evidence_basis=row.get('evidence_basis', ''))))
        for draft, value in updates:
            draft['triage'] = value
        atomic_json(queue_path, queue)
        return len(updates)


def institution(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password:
        raise ValueError('来源必须是公开 HTTP(S) 地址')
    host = (parsed.hostname or '').lower()
    for suffix in ('.edu.cn', '.ac.cn', '.cas.cn'):
        if host.endswith(suffix) and host[:-len(suffix)]:
            return host[:-len(suffix)].split('.')[-1] + suffix if suffix != '.cas.cn' else 'cas.cn'
    raise ValueError('来源不属于受支持的官方教育或科研域名')


def check_source(draft, configs):
    if draft['listing_url'] not in {c['url'] for c in configs}:
        raise ValueError('原栏目已不在官方来源配置中，请先核对配置')
    if institution(draft['source_url']) != institution(draft['listing_url']):
        raise ValueError('公告与官方栏目不属于同一机构域名，请人工核对来源')


def fetch_source(config):
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(config['url'], timeout=25, headers={'User-Agent': 'Mozilla/5.0 (admissions review)'})
        response.raise_for_status()
        if response.status_code != 200 or institution(response.url) != institution(config['url']):
            raise ValueError('原文未返回 200 或跳转至其他机构域名')
        return response.content


def fetch_pdf(url, source_url):
    """Bounded official PDF GET, preserving TLS verification and same-institution hops."""
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(5):
            if urlsplit(url).scheme != 'https' or institution(url) != institution(source_url):
                raise ValueError('PDF必须使用同机构HTTPS官方链接')
            with session.get(url, timeout=25, stream=True, allow_redirects=False,
                             headers={'User-Agent': 'Mozilla/5.0 (admissions review)', 'Referer': source_url}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers.get('Location', ''))
                    continue
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('PDF未返回HTTP 200')
                if int(response.headers.get('Content-Length', '0')) > extraction.MAX_PDF_BYTES:
                    raise ValueError('PDF超出12MB上限')
                chunks, total = [], 0
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > extraction.MAX_PDF_BYTES:
                        raise ValueError('PDF超出12MB上限')
                    chunks.append(chunk)
                raw = b''.join(chunks)
                if not raw.startswith(b'%PDF-'):
                    raise ValueError('PDF链接返回的不是PDF文件')
                return raw
        raise ValueError('PDF重定向次数过多')


def complete_evidence_mode(draft):
    fetched, reviewed = draft.get('fetch', {}), draft.get('review', {})
    return (fetched.get('evidence_mode') == 'complete' or isinstance(fetched.get('complete_document'), dict) or
            reviewed.get('evidence_mode') == 'complete' or
            reviewed.get('reviewer', '').startswith('自动证据核验/'))


def fetch_evidence(draft, queue_path, fetcher, now=None, pdf_fetcher=fetch_pdf, docx_fetcher=None, complete=False):
    timestamp = (now or datetime.now(timezone.utc)).isoformat(timespec='seconds')
    previous = draft.get('fetch', {})
    complete = complete or complete_evidence_mode(draft)
    if complete:
        previous = dict(previous, evidence_mode='complete')
    html_received = False
    try:
        raw = fetcher({'url': draft['source_url']})
        raw = raw.encode('utf-8') if isinstance(raw, str) else raw
        if not raw or not isinstance(raw, bytes):
            raise ValueError('未取得正文')
        digest = hashlib.sha256(raw).hexdigest()
        folder = Path(queue_path).parent / 'opportunity_evidence'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (digest + '.html')
        path.write_bytes(raw)
        html_received = True
        if previous.get('sha256') != digest:
            previous = dict(previous, content_sha256=None)
            previous.pop('complete_document', None)
        previous = dict(previous, sha256=digest, evidence_file=str(path.resolve()), html_fetched_at=timestamp)
        if complete:
            from crawler import automatic_evidence
            doc = automatic_evidence.collect(raw, draft['source_url'], pdf_fetcher=pdf_fetcher,
                docx_fetcher=docx_fetcher or attachments.fetch_docx, folder=folder, wait=getattr(fetcher, 'wait', None))
            draft['fetch'] = dict(status='ok', checked_at=timestamp, sha256=digest, evidence_mode='complete',
                content_sha256=doc['content_sha256'], evidence_file=str(path.resolve()),
                complete_document=doc, error=None)
            return raw
        attachment_records = draft['item'].get('source_attachments', [])
        attachments.validate_links(attachment_records, raw, draft['source_url'])
        def saved_docx(url, source_url):
            if hasattr(fetcher, 'wait'):
                fetcher.wait(url)
            content = (docx_fetcher or attachments.fetch_docx)(url, source_url)
            (folder / (hashlib.sha256(content).hexdigest() + '.docx')).write_bytes(content)
            return content
        verified_attachments = attachments.verify(attachment_records, draft['source_url'], saved_docx)
        pdf_urls = extraction.embedded_pdf_urls(raw, draft['source_url'])
        try:
            if pdf_urls:
                raise ValueError('正文包含PDF，须共同核验')
            extracted = extraction.extract(raw, draft['source_url'], draft['item'].get('title', ''), opportunities.today())
        except ValueError:
            if not pdf_urls:
                raise
            extraction.document(raw, draft['source_url'], require_article=False)
            if len(pdf_urls) > 5:
                raise ValueError('正文嵌入超过5个PDF，需人工核对范围')
            previous['pdf_urls'] = pdf_urls
            pdfs = []
            for url in pdf_urls:
                if institution(url) != institution(draft['source_url']):
                    raise ValueError('嵌入PDF不是同机构官方链接')
                pdf_raw = pdf_fetcher(url, draft['source_url'])
                parsed = extraction.pdf_document(pdf_raw, url, draft['item'].get('title', ''), opportunities.today())
                pdf_hash = hashlib.sha256(pdf_raw).hexdigest()
                pdf_path = folder / (pdf_hash + '.pdf')
                pdf_path.write_bytes(pdf_raw)
                pdfs.append(dict(url=url, sha256=pdf_hash, evidence_file=str(pdf_path.resolve()), **parsed))
            draft['fetch'] = dict(status='pdf_review', checked_at=timestamp, sha256=digest,
                                  content_sha256=attachments.source_version(extraction.pdf_source_version(raw, draft['source_url'], pdfs), attachment_records),
                                  evidence_file=str(path.resolve()), pdfs=pdfs, attachments=verified_attachments, error=None)
            if len(pdfs) == 1:
                for key in ('suggestions', 'field_evidence', 'classification'):
                    draft[key] = copy.deepcopy(pdfs[0].get(key, {} if key != 'classification' else 'pending_review'))
            else:
                draft.update(suggestions={}, field_evidence={}, classification='pending_review')
            draft['warnings'] = ['正文包含PDF，须确认每个PDF版本及逐字段页码证据后发布；规则建议不代表已核验。'] + [warning for pdf in pdfs for warning in pdf.get('warnings', [])]
            return raw
        draft['fetch'] = dict(status='ok', checked_at=timestamp, sha256=digest,
                              content_sha256=attachments.source_version(extracted['content_sha256'], attachment_records),
                              evidence_file=str(path.resolve()), attachments=verified_attachments, error=None)
        draft.update(extracted)
        return raw
    except (OSError, ValueError, requests.RequestException) as error:
        # Failure to interpret or download an attachment does not mean the HTML
        # URL is dead. Preserve its current bytes for source-bound triage only.
        content_error = html_received and str(error) != '返回的是访问验证或错误页面，不是公告正文'
        draft['fetch'] = dict(previous, status='evidence_error' if content_error else 'error',
                              checked_at=timestamp, error=str(error)[:500],
                              error_kind='evidence' if content_error else 'transport',
                              error_code=getattr(error, 'code', 'incomplete_evidence' if content_error else 'source_unavailable'),
                              evidence_retryable=bool(content_error and getattr(error, 'retryable', isinstance(error, requests.RequestException))),
                              consecutive_failures=previous.get('consecutive_failures', 0) + 1)
        return None


def evidence_error(fetch):
    """Read old mixed-state records without treating their HTML as a dead URL."""
    return fetch.get('status') == 'evidence_error' or (fetch.get('status') == 'error' and fetch.get('error_kind') == 'evidence')


def source_error(fetch):
    return fetch.get('status') == 'error' and not evidence_error(fetch)


def replaced_sources(draft):
    """Only a complete recorded migration chain can retire an old candidate URL."""
    chain = draft.get('source_replacements') or []
    if not isinstance(chain, list) or not chain or not isinstance(chain[-1], dict) or chain[-1].get('new_url') != draft.get('source_url'):
        return set()
    previous, originals = None, set()
    for row in chain:
        if (not isinstance(row, dict) or not row.get('original_url') or not row.get('new_url') or
            previous is not None and previous != row['original_url'] or
            any(not isinstance(row.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', row[key]) for key in ('old_sha', 'new_sha'))):
            return set()
        try:
            if datetime.fromisoformat(row['adopted_at']).tzinfo is None:
                return set()
        except (KeyError, TypeError, ValueError):
            return set()
        originals.add(row['original_url'])
        previous = row['new_url']
    return originals


def sync(monitoring, queue_path, configs, *, fetcher=fetch_source, pdf_fetcher=fetch_pdf, refresh=False, now=None):
    """Fetch new/failed/24h-old evidence, preserving human fields; refresh bypasses age."""
    with output_lock(queue_path):
        now = now or datetime.now(timezone.utc)
        queue = read_queue(queue_path)
        drafts = {d['source_url']: d for d in queue['drafts']}
        migrated = {url: d for d in drafts.values() for url in replaced_sources(d)}
        counts = dict(total=0, new=0, fetched=0, reused=0, source_errors=0, needs_pdf_review=0)
        for candidate in monitoring['candidates']:
            url = candidate['url']
            replaced = migrated.get(url)
            if replaced and (candidate['school'], candidate['dept'], extraction.compact(candidate['title'])) == (
                replaced['item']['school_id'], replaced['item']['dept_id'], extraction.compact(replaced['item']['title'])):
                counts['retired_candidates'] = counts.get('retired_candidates', 0) + 1
                continue
            if url not in drafts:
                item = {k: '' for k in opportunities.TEXT}
                item.update({k: None for k in opportunities.YEARS})
                item.update({k: [] for k in opportunities.LISTS})
                key = hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]
                if any(d['id'] == key for d in drafts.values()):
                    # An old URL can later host a different announcement. Preserve
                    # the migrated record ID while giving the new title its own ID.
                    key = hashlib.sha256((url + '\n' + candidate['title']).encode('utf-8')).hexdigest()[:20]
                item.update(id='activity-' + key, title=candidate['title'], source_url=url,
                            school_id=candidate['school'], dept_id=candidate['dept'], unit=candidate['unit'])
                drafts[url] = dict(id=key, source_url=url, listing_url=candidate['source'],
                                   first_seen=candidate['first_seen'], item=item, quotes=[])
                counts['new'] += 1
            elif candidate['source'] != drafts[url]['listing_url']:
                relisted = dict(drafts[url], listing_url=candidate['source'])
                try:
                    check_source(relisted, configs)
                    drafts[url]['listing_url'] = candidate['source']
                except ValueError:
                    pass  # An untrusted replacement cannot erase the previous provenance.
            drafts[url]['last_seen'] = candidate['last_seen']
            drafts[url]['content_scope_hint'] = candidate.get('content_scope_hint', 'pending')
        for draft in drafts.values():
            try:
                check_source(draft, configs)
                evidence = draft.get('fetch', {})
                try:
                    age = (now - datetime.fromisoformat(evidence['checked_at'])).total_seconds()
                except (KeyError, ValueError, TypeError):
                    age = -1
                pdf_files_exist = all(Path(p.get('evidence_file', '')).is_file() for p in evidence.get('pdfs', []))
                interval = 604800 if triage(draft).get('classification') in ('historical', 'irrelevant') else 86400
                if not refresh and source_error(evidence) and 0 <= age < min(172800, 3600 * 2 ** min(evidence.get('consecutive_failures', 1), 6)):
                    counts['reused'] += 1
                elif not refresh and evidence_error(evidence) and 0 <= age < interval and Path(evidence.get('evidence_file', '')).is_file():
                    counts['reused'] += 1
                elif not refresh and evidence.get('status') in ('ok', 'pdf_review') and 0 <= age < interval and Path(evidence.get('evidence_file', '')).is_file() and pdf_files_exist:
                    counts['reused'] += 1
                    if evidence.get('status') == 'ok' and not draft.get('field_evidence') and not complete_evidence_mode(draft):
                        extracted = extraction.extract(Path(evidence['evidence_file']).read_bytes(), draft['source_url'], draft['item'].get('title', ''), opportunities.today())
                        draft.update(extracted)
                        draft['fetch']['content_sha256'] = extracted['content_sha256']
                else:
                    counts['fetched'] += 1
                    fetch_evidence(draft, queue_path, fetcher, now, pdf_fetcher)
            except ValueError as error:
                draft['fetch'] = dict(draft.get('fetch', {}), status='error', error=str(error), error_kind='transport')
            if draft.get('fetch', {}).get('status') == 'pdf_review':
                counts['needs_pdf_review'] += status(draft) != 'published'
            elif evidence_error(draft.get('fetch', {})):
                counts['needs_evidence_review'] = counts.get('needs_evidence_review', 0) + 1
            elif draft.get('fetch', {}).get('status') != 'ok':
                counts['source_errors'] += 1
        queue['drafts'] = list(drafts.values())
        counts['total'] = len(drafts)
        queue['summary'] = counts
        queue['synced_at'] = now.isoformat(timespec='seconds')
        atomic_json(queue_path, queue)
        return queue


def item_hash(item):
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def status(draft):
    evidence = draft.get('fetch', {})
    review = draft.get('review')
    if evidence_error(evidence):
        return 'needs_evidence_review'
    if evidence.get('status') == 'pdf_review' and not (review or {}).get('source_documents'):
        return 'needs_pdf_review'
    if evidence.get('status') not in ('ok', 'pdf_review'):
        return 'source_error'
    if review and (((review.get('source_documents') or complete_evidence_mode(draft)) and review.get('content_sha256') != evidence.get('content_sha256')) or
                   review['source_sha256'] != evidence['sha256'] and (not review.get('content_sha256') or review['content_sha256'] != evidence.get('content_sha256'))):
        return 'source_changed'
    if review and review['item_sha256'] == item_hash(draft['item']) and review['quotes'] == draft.get('quotes') and review.get('field_evidence', {}) == draft.get('reviewed_fields', {}):
        return 'published'
    return 'pending_review'


def accept(queue_path, draft_id, fields=None, replace=False, expected_revision=None):
    """Explicitly copy supported suggestions into a draft; never publish or infer blanks."""
    with output_lock(queue_path):
        queue = read_queue(queue_path)
        draft = next((d for d in queue['drafts'] if d['id'] == draft_id), None)
        if draft is None or draft.get('fetch', {}).get('status') not in ('ok', 'pdf_review'):
            raise ValueError('草稿不存在或原文获取失败，不能采纳')
        if expected_revision is not None and item_hash(draft) != expected_revision:
            raise ValueError('草稿已被其他操作更新，请重新打开后核验')
        proposed = draft.get('suggestions', {})
        supported = set(proposed) & (opportunities.TEXT | opportunities.YEARS | opportunities.LISTS)
        selected = set(fields) if fields else supported
        if not selected <= supported:
            raise ValueError('字段没有明确建议或不属于活动字段；月份与附件只作证据，不推断截止日')
        accepted = []
        draft.setdefault('reviewed_fields', {})
        for field in selected:
            if draft['item'].get(field) and not replace:
                continue
            draft['item'][field] = copy.deepcopy(proposed[field])
            draft['reviewed_fields'][field] = copy.deepcopy(draft['field_evidence'][field])
            quote = draft['field_evidence'][field]['quote']
            if quote and quote not in draft['quotes']:
                draft['quotes'].append(quote)
            accepted.append(field)
        if accepted:
            draft['manual_edit'] = dict(at=datetime.now(timezone.utc).isoformat(timespec='seconds'), action='accept')
        atomic_json(queue_path, queue)
        return sorted(accepted)


def validate_field_evidence(draft, item, text):
    """Bind critical claims to source excerpts; manual paraphrases retain explicit mapping."""
    normalize = extraction.compact
    mappings = draft.get('reviewed_fields', {})
    quotes = draft.get('quotes', [])
    window = item.get('application_window')
    if window:
        quote = normalize(window.get('quote', ''))
        if not quote or quote not in normalize(text):
            raise ValueError('申请窗口须有当前官方正文中的原文摘录')
        if window['mode'] == 'rolling' and not re.search(r'(?:全年|长期|常年|滚动).{0,80}(?:接受|接收|招收|招募|招聘|申请|报名|开放)|(?:接受|接收|招收|招募|招聘|申请|报名|开放).{0,80}(?:全年|长期|常年|滚动)', quote):
            raise ValueError('滚动申请须有长期接受申请或招募的明确原文')
        if window['mode'] == 'month':
            year, month = map(int, window['end_month'].split('-'))
            if not re.search(rf'{year}(?:年|[-/])0?{month}(?:月|\b)', quote) or not re.search(r'报名|受理|申请', quote):
                raise ValueError('月精度截止缺少对应受理年月原文')
            mapped = mappings.get('registration_start', {})
            if item.get('registration_start') and not re.search(r'报名|受理|开始|启动', normalize(mapped.get('quote', ''))):
                if '即日起' not in quote or '即日起' not in mapped.get('locator', ''):
                    raise ValueError('以发布日期作为开始日须单独映射即日起依据')
    critical = ('deadline', 'registration_start', 'event_start', 'event_end', 'eligibility', 'materials')
    for field in critical:
        value = item.get(field)
        if not value:
            continue
        mapped = mappings.get(field, {})
        quote = mapped.get('quote', '') if isinstance(mapped, dict) else ''
        field_text = text
        if isinstance(mapped, dict) and mapped.get('source_url') != item.get('source_url'):
            for attachment in item.get('source_attachments', []):
                evidence = attachment['field_evidence'].get(field, {})
                if attachment['url'] == mapped.get('source_url') and normalize(quote) == normalize(evidence.get('quote', '')):
                    field_text = evidence['quote']  # Already re-fetched and verified before publication.
                    break
        if quote and normalize(quote) in normalize(field_text):
            if field == 'registration_start' and value == item.get('published_at') and not re.search(r'报名|受理|开始|启动', normalize(quote)):
                if '即日起' not in normalize(text) or '即日起' not in mapped.get('locator', ''):
                    raise ValueError('以发布日期作为开始日须单独映射即日起依据')
            # A reviewer may paraphrase conditions, but dates must be present in evidence.
            if field in ('eligibility', 'materials'):
                continue
            dates = extraction.explicit_date_values(quote, with_time=field == 'deadline')
            comparable = datetime.fromisoformat(value).isoformat() if 'T' in str(value) else value
            if comparable in dates:
                continue
        if field in ('eligibility', 'materials'):
            if all(any(normalize(part) in normalize(q) for q in quotes) for part in value):
                continue
        else:
            labels = {'deadline': r'(?:报名|申请|受理).*(?:截止|截至|至)',
                      'registration_start': r'(?:报名|受理).*(?:开始|启动)',
                      'event_start': r'活动时间|营期|举办时间', 'event_end': r'活动时间|营期|举办时间'}
            dates = {value for q in quotes if re.search(labels[field], normalize(q)) for value in extraction.explicit_date_values(q, with_time=field == 'deadline')}
            comparable = datetime.fromisoformat(value).isoformat() if 'T' in str(value) else value
            if comparable in dates:
                continue
        raise ValueError(f'{field} 缺少对应原文证据；请填写 reviewed_fields.{field}.quote 后核验')


def pdf_review_evidence(draft, acknowledged_pdf_hashes):
    """Require each PDF version and quote/page mapping; no OCR or inferred consent."""
    pdfs = draft['fetch']['pdfs']
    if set(acknowledged_pdf_hashes or []) != {pdf['sha256'] for pdf in pdfs}:
        raise ValueError('PDF发布门禁：须显式确认全部当前PDF SHA，版本变化后重新核验')
    if any(pdf['text_status'] != 'readable' for pdf in pdfs):
        raise ValueError('PDF发布门禁：扫描、加密或未确认正文的PDF不能发布')
    mappings = draft.get('reviewed_fields', {})
    for field in ('deadline', 'registration_start', 'event_start', 'event_end', 'eligibility', 'materials'):
        if draft['item'].get(field) and field not in mappings:
            raise ValueError(f'PDF发布门禁：{field}须提供逐字段页码证据')
    documents = []
    for pdf in pdfs:
        fields = {}
        for field, evidence in mappings.items():
            if evidence.get('source_url') != pdf['url']:
                continue
            pages = evidence.get('pages', [])
            if not pages or any(type(page) is not int or not 1 <= page <= pdf['page_count'] for page in pages) or pages != sorted(set(pages)):
                raise ValueError(f'PDF发布门禁：{field}页码错误')
            text = '\n'.join(page['text'] for page in pdf['pages'] if page['page'] in pages)
            if not evidence.get('quote') or extraction.compact(evidence['quote']) not in extraction.compact(text):
                raise ValueError(f'PDF发布门禁：{field}摘录不在指定页码')
            fields[field] = dict(quote=evidence['quote'], pages=pages)
        if not fields:
            raise ValueError('PDF发布门禁：每个PDF均须保留页码核验依据')
        checked_day = datetime.fromisoformat(draft['fetch']['checked_at']).astimezone(timezone(timedelta(hours=8))).date().isoformat()
        documents.append(dict(url=pdf['url'], sha256=pdf['sha256'], page_count=pdf['page_count'],
                              checked_at=checked_day, field_evidence=fields))
    if set(mappings) != {field for doc in documents for field in doc['field_evidence']}:
        raise ValueError('PDF发布门禁：字段来源不属于当前PDF')
    return documents, '\n'.join(page['text'] for pdf in pdfs for page in pdf['pages'])


def publish(queue_path, draft_id, root, configs, *, acknowledged_hash, reviewer, note, fetcher=fetch_source,
            pdf_fetcher=fetch_pdf, acknowledged_pdf_hashes=None, expected_revision=None, docx_fetcher=None,
            acknowledged_content_hash=None, complete=False):
    """Recheck source, validate one item, atomically replace the catalog with audit.

catalog.review_log is the authoritative audit if a crash interrupts the later
queue-status write. A repeated publication updates the same ID, never appends a
second item. External edits should not run concurrently with this command.
"""
    if not reviewer.strip() or not note.strip():
        raise ValueError('发布必须填写核验人及核验说明')
    catalog_path = Path(root) / 'data/opportunities.json'
    with output_lock(queue_path), output_lock(catalog_path):
        queue = read_queue(queue_path)
        draft = next((d for d in queue['drafts'] if d['id'] == draft_id), None)
        if draft is None:
            raise ValueError('未找到草稿')
        if expected_revision is not None and item_hash(draft) != expected_revision:
            raise ValueError('草稿已被其他操作更新，请重新打开后核验')
        check_source(draft, configs)
        complete = complete or complete_evidence_mode(draft)
        acknowledged_fetch = copy.deepcopy(draft.get('fetch', {}))
        raw = fetch_evidence(draft, queue_path, fetcher, pdf_fetcher=pdf_fetcher, docx_fetcher=docx_fetcher, complete=complete)
        atomic_json(queue_path, queue)
        if raw is None:
            raise ValueError('原文当前获取失败，未发布')
        documents = []
        if complete:
            from crawler import automatic_evidence
            if acknowledged_fetch.get('content_sha256') != draft['fetch']['content_sha256']:
                raise ValueError('正文或附件组合版本变化，须重新核验后发布')
            source_text = draft['fetch']['complete_document']['text']
            documents, source_attachments = automatic_evidence.metadata(draft['fetch']['complete_document'], opportunities.today().isoformat())
        elif draft['fetch']['status'] == 'pdf_review':
            documents, source_text = pdf_review_evidence(draft, acknowledged_pdf_hashes)
        else:
            source_text = extraction.document(raw, draft['source_url'])['text']
        digest = draft['fetch']['sha256']
        content_confirmed = False
        if acknowledged_content_hash is not None:
            content_confirmed = (isinstance(acknowledged_content_hash, str) and
                                 re.fullmatch(r'[a-f0-9]{64}', acknowledged_content_hash) and
                                 acknowledged_fetch.get('status') == draft['fetch']['status'] == 'ok' and
                                 acknowledged_fetch.get('sha256') == acknowledged_hash and
                                 acknowledged_fetch.get('content_sha256') == acknowledged_content_hash == draft['fetch']['content_sha256'])
            if not content_confirmed:
                raise ValueError('正文、链接或附件组合 SHA 与显式确认的既有证据不一致，未发布')
        if acknowledged_hash != digest and not content_confirmed:
            raise ValueError('原文与已核对 SHA 不一致，请重新核验；未发布')
        quotes = draft.get('quotes', [])
        normalize = lambda text: ''.join(text.split())
        text = normalize(source_text)
        if not isinstance(quotes, list) or not quotes or any(not isinstance(q, str) or not q.strip() or normalize(q) not in text for q in quotes):
            raise ValueError('请提供可在当前原文中匹配的核验摘录 quotes，未发布')
        item = copy.deepcopy(draft['item'])
        if item.get('source_url') != draft['source_url']:
            raise ValueError('活动来源与草稿取证地址不一致，未发布')
        day = opportunities.today().isoformat()
        item.update(source_state='verified', source_sha256=digest, source_content_sha256=draft['fetch']['content_sha256'],
                    checked_at=day, verified_at=day)
        if documents:
            item['source_documents'] = documents
        else:
            item.pop('source_documents', None)
        if complete:
            if source_attachments:
                item['source_attachments'] = source_attachments
            else:
                item.pop('source_attachments', None)
        opportunities.validate(item)
        opportunities.validate_classification(item, source_text, require_publishable=True)
        opportunities.validate_mentor_links(root, item, source_text)
        validate_field_evidence(draft, item, source_text)
        catalog = opportunities.load(root)
        existing = next((i for i in catalog['opportunities'] if i['id'] == item['id']), None)
        if existing and existing['source_url'] != item['source_url']:
            raise ValueError('活动 ID 已被其他来源使用，未发布')
        if any(i['source_url'] == item['source_url'] and i['id'] != item['id'] for i in catalog['opportunities']):
            raise ValueError('该来源已存在其他活动 ID，请沿用原 ID，未发布')
        review = dict(draft_id=draft_id, opportunity_id=item['id'], reviewer=reviewer.strip(), note=note.strip(),
                      reviewed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                      source_url=draft['source_url'], listing_url=draft['listing_url'], first_seen=draft['first_seen'],
                      source_sha256=digest, content_sha256=draft['fetch']['content_sha256'],
                      item_sha256=item_hash(item), quotes=copy.deepcopy(quotes),
                      content_classification=copy.deepcopy(item['content_classification']),
                      field_evidence=copy.deepcopy(draft.get('reviewed_fields', {})))
        if complete:
            review['evidence_mode'] = 'complete'
        if documents:
            review['source_documents'] = copy.deepcopy(documents)
        if item.get('source_attachments'):
            review['source_attachments'] = copy.deepcopy(item['source_attachments'])
        if content_confirmed:
            review['version_confirmation'] = dict(mode='explicit_normalized_content',
                acknowledged_raw_sha256=acknowledged_hash, current_raw_sha256=digest,
                content_sha256=acknowledged_content_hash,
                basis='维护者显式确认此前正文、链接和全部已核验附件的组合版本；实时取证一致')
        review['published_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
        catalog['opportunities'] = [item if i['id'] == item['id'] else i for i in catalog['opportunities']]
        if existing is None:
            catalog['opportunities'].append(item)
        catalog['checked_at'] = day
        catalog.setdefault('review_log', []).append(review)
        atomic_json(catalog_path, catalog)
        draft.update(item=item, review=review)
        atomic_json(queue_path, queue)
        return item


def renew(queue_path, root):
    """Refresh only previously reviewed, unchanged facts; keep manual review dates."""
    catalog_path = Path(root) / 'data/opportunities.json'
    with output_lock(queue_path), output_lock(catalog_path):
        queue = read_queue(queue_path)
        catalog = opportunities.load(root)
        by_id = {item['id']: item for item in catalog['opportunities']}
        renewed = []
        for draft in queue['drafts']:
            review = draft.get('review', {})
            evidence = draft.get('fetch', {})
            item = by_id.get(draft['item']['id'])
            if status(draft) != 'published' or not review.get('content_sha256') or review['content_sha256'] != evidence.get('content_sha256'):
                continue
            if item is None or item_hash(item) != review['item_sha256']:
                continue
            try:
                checked = datetime.fromisoformat(evidence['checked_at'])
                age = (datetime.now(timezone.utc)-checked).total_seconds()
            except (KeyError, ValueError, TypeError):
                continue
            if not 0 <= age < 86400:
                continue
            day = checked.astimezone(timezone(timedelta(hours=8))).date().isoformat()
            if item['source_sha256'] == evidence['sha256'] and item['checked_at'] == day and item.get('source_content_sha256') == evidence['content_sha256']:
                continue
            item.update(source_sha256=evidence['sha256'], source_content_sha256=evidence['content_sha256'], checked_at=day)
            if item.get('source_documents'):
                for document in item['source_documents']:
                    document['checked_at'] = day
                review['source_documents'] = copy.deepcopy(item['source_documents'])
            draft['item'] = copy.deepcopy(item)
            review.update(source_sha256=evidence['sha256'], item_sha256=item_hash(item), last_source_check_at=evidence['checked_at'])
            catalog.setdefault('review_log', []).append(dict(operation='unchanged_source_recheck', opportunity_id=item['id'],
                checked_at=evidence['checked_at'], source_sha256=evidence['sha256'], content_sha256=evidence['content_sha256'],
                manual_reviewed_at=review['reviewed_at']))
            renewed.append(item['id'])
        if renewed:
            atomic_json(catalog_path, catalog)
            atomic_json(queue_path, queue)
        return renewed

"""Local maintainer views over the public opportunity review queue."""
import copy
import difflib
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from crawler import opportunity_extract as extract, opportunity_review as review, opportunity_util as util
from crawler.pipeline_metrics import summarize as pipeline_metrics

LABELS = {'pending_review': '待核验', 'needs_pdf_review': '待核验PDF', 'source_error': '来源获取失败',
          'source_changed': '来源已变化', 'published': '已发布'}
MANAGED = {'source_url', 'source_sha256', 'source_content_sha256', 'source_documents', 'source_state', 'checked_at', 'verified_at'}
EDITABLE = (util.TEXT | util.YEARS | util.LISTS) - MANAGED


class Dashboard:
    def __init__(self, root, queue=None, config=None):
        self.root = Path(root).resolve()
        self.queue = Path(queue) if queue else self.root / 'cache/opportunity_review.json'
        self.config = Path(config) if config else self.root / 'sites/opportunities.yaml'

    def configs(self):
        return yaml.safe_load(self.config.read_text(encoding='utf-8'))['targets']

    def find(self, draft_id):
        draft = next((d for d in review.read_queue(self.queue)['drafts'] if d['id'] == draft_id), None)
        if draft is None:
            raise ValueError('未找到草稿，请刷新队列')
        return draft

    def evidence(self, digest, suffix):
        if not re.fullmatch(r'[a-f0-9]{64}', digest or '') or suffix not in ('.html', '.pdf'):
            raise ValueError('证据版本无效')
        folder = self.queue.parent / 'opportunity_evidence'
        path = folder / (digest + suffix)
        if folder.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError('证据位置无效')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('本机证据文件与记录版本不一致，请重新抓取')
        return raw

    def blockers(self, draft):
        errors = []
        fetch = draft.get('fetch', {})
        if fetch.get('status') not in ('ok', 'pdf_review'):
            return ['官方原文未成功取得，请重新抓取；不能使用旧缓存发布。']
        try:
            review.check_source(draft, self.configs())
            raw = self.evidence(fetch.get('sha256'), '.html')
            item = copy.deepcopy(draft['item'])
            item.update(verified_at=util.today().isoformat(), checked_at=util.today().isoformat(), source_state='verified')
            util.validate(item)
            if fetch['status'] == 'pdf_review':
                _, text = review.pdf_review_evidence(draft, [p['sha256'] for p in fetch['pdfs']])
            else:
                text = extract.document(raw, draft['source_url'])['text']
            quotes = draft.get('quotes', [])
            if not quotes or any(not isinstance(q, str) or not q.strip() or extract.compact(q) not in extract.compact(text) for q in quotes):
                errors.append('核验摘录为空或未匹配当前原文，请检查逐字段引用及总摘录。')
            review.validate_field_evidence(draft, item, text)
        except (ValueError, OSError, KeyError, TypeError) as error:
            errors.append(str(error) if isinstance(error, ValueError) else '证据或配置暂不可读取，请重新抓取或检查本机配置。')
        return errors

    def summary(self, draft):
        item, suggestions = draft['item'], draft.get('suggestions', {})
        status = review.status(draft)
        deadline = item.get('deadline') or suggestions.get('deadline') or ''
        day = util.today()
        try:
            waiting = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(draft['first_seen'])).days)
        except (ValueError, KeyError, TypeError):
            waiting = 0
        triage = review.triage(draft)
        historical = item.get('cycle') == 'historical' or draft.get('classification') == 'historical' or triage.get('classification') == 'historical'
        year = item.get('graduation_year') or suggestions.get('graduation_year')
        # A title year never becomes an applicant graduation year.
        target_year = day.year + (2 if day.month >= 9 else 1)
        current = not historical and (year == target_year or draft.get('classification') == 'current_pending_review' or triage.get('classification') == 'current')
        urgent = bool(deadline and day.isoformat() <= deadline[:10] <= (day + timedelta(days=30)).isoformat())
        priority = 5 if triage.get('classification') == 'irrelevant' else 0 if current and urgent else 1 if current else 2 if status in ('source_error', 'source_changed') else 4 if historical or status == 'published' else 3
        missing = [name for key,name in [('kind','活动类型'),('cycle','申请轮次'),('evidence','核验摘要')] if not item.get(key)]
        reasons = ['官方来源获取失败，需重新抓取'] if status == 'source_error' else ['官方原文或PDF版本变化，须重新核验'] if status == 'source_changed' else []
        if missing:
            reasons.append('待补齐：' + '、'.join(missing))
        if status == 'needs_pdf_review':
            reasons.append('待确认PDF版本及逐字段页码')
        return dict(id=draft['id'], title=item.get('title', ''), unit=item.get('unit', ''), status=status,
                    status_label=LABELS[status], deadline=deadline, graduation_year=year,
                    current_cycle=current, historical=historical, waiting_days=waiting, priority=priority,
                    triage=triage,
                    first_seen=draft.get('first_seen'), checked_at=draft.get('fetch', {}).get('checked_at'), blocking_reasons=reasons)

    def listing(self):
        queue = review.read_queue(self.queue)
        rows = [self.summary(d) for d in queue['drafts']]
        rows.sort(key=lambda r: (r['priority'], r['deadline'] or '9999', -r['waiting_days'], r['id']))
        return dict(drafts=rows, labels=LABELS, checked_at=util.today().isoformat(),
                    metrics=pipeline_metrics(self.root, queue),
                    note='优先级仅用于维护排序；当前轮次线索和规则建议不等于已核验报名机会。')

    def detail(self, draft_id):
        d = self.find(draft_id)
        fetch = d.get('fetch', {})
        text, difference, evidence_error = '', '', ''
        try:
            raw = self.evidence(fetch.get('sha256'), '.html')
            text = extract.document(raw, d['source_url'], require_article=False)['text']
            old_hash = d.get('review', {}).get('source_sha256')
            if old_hash and old_hash != fetch.get('sha256'):
                old = extract.document(self.evidence(old_hash, '.html'), d['source_url'], require_article=False)['text']
                difference = '\n'.join(difflib.unified_diff(old.splitlines(), text.splitlines(), fromfile='上次核验正文', tofile='当前正文', lineterm=''))
                if not difference:
                    difference = '页面字节版本发生变化，提取正文相同；仍由发布门禁核对链接与PDF版本。'
        except (OSError, ValueError, KeyError):
            evidence_error = '当前本机HTML证据不可用或版本不符，请重新抓取。'
        published = next((i for i in util.load(self.root)['opportunities'] if i['id'] == d['item']['id']), None)
        changes = [dict(field=k, before=(published or {}).get(k), after=v) for k,v in d['item'].items()
                   if k not in MANAGED and (published or {}).get(k) != v]
        pdfs = [{k:p.get(k) for k in ('url', 'sha256', 'page_count', 'text_status', 'pages')} for p in fetch.get('pdfs', [])]
        old_documents = d.get('review', {}).get('source_documents', [])
        for pdf in pdfs:
            old = next((p for p in old_documents if p['url'] == pdf['url']), None)
            if old and old['sha256'] != pdf['sha256']:
                try:
                    previous = extract.pdf_document(self.evidence(old['sha256'], '.pdf'), old['url'])
                    before = '\n'.join(p['text'] for p in previous['pages'])
                    after = '\n'.join(p['text'] for p in pdf['pages'])
                    pdf['difference'] = '\n'.join(difflib.unified_diff(before.splitlines(), after.splitlines(), fromfile='上次核验PDF', tofile='当前PDF', lineterm='')) or 'PDF字节版本变化，提取文本相同；仍须确认新版本。'
                except (OSError, ValueError, KeyError, TypeError):
                    pdf['difference'] = '旧PDF文本证据不可读取，请直接核对当前官方文件；不能认定为未变化。'
        return dict(**self.summary(d), revision=review.item_hash(d), item=d['item'], source_url=d['source_url'],
                    ai_suggestions=d.get('ai_suggestions'),
                    listing_url=d['listing_url'], suggestions=d.get('suggestions', {}), field_evidence=d.get('field_evidence', {}),
                    reviewed_fields=d.get('reviewed_fields', {}), quotes=d.get('quotes', []), warnings=d.get('warnings', []),
                    source_sha256=fetch.get('sha256'), content_sha256=fetch.get('content_sha256'),
                    source_text=text, source_difference=difference, field_changes=changes, pdfs=pdfs,
                    previous_documents=[{k:p[k] for k in ('url', 'sha256')} for p in old_documents],
                    blockers=self.blockers(d) + ([evidence_error] if evidence_error else []),
                    fetch_error=fetch.get('error'), editable_fields=sorted(EDITABLE),
                    suggested_fields=sorted(set(d.get('suggestions', {})) & EDITABLE))

    def mutate(self, draft_id, action, body):
        revision = body.get('revision')
        if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{64}', revision):
            raise ValueError('缺少草稿版本，请重新打开草稿')
        if action == 'accept':
            fields = body.get('fields')
            if not isinstance(fields, list) or not fields or any(not isinstance(f, str) or f not in EDITABLE for f in fields):
                raise ValueError('请明确勾选要采纳的字段')
            review.accept(self.queue, draft_id, fields, body.get('replace') is True, expected_revision=revision)
        elif action == 'publish':
            if body.get('confirmed') is not True:
                raise ValueError('须明确确认已逐项核对当前原文和证据页码')
            if any(not isinstance(body.get(field), str) or not body[field].strip() for field in ('reviewer', 'note')):
                raise ValueError('请填写核验人和核验说明')
            review.publish(self.queue, draft_id, self.root, self.configs(), acknowledged_hash=body.get('sha256'),
                           acknowledged_pdf_hashes=body.get('pdf_sha256'), reviewer=body.get('reviewer', ''),
                           note=body.get('note', ''), expected_revision=revision,
                           fetcher=review.fetch_source, pdf_fetcher=review.fetch_pdf)
        elif action in ('save', 'refresh'):
            with review.output_lock(self.queue):
                queue = review.read_queue(self.queue)
                draft = next((d for d in queue['drafts'] if d['id'] == draft_id), None)
                if draft is None or review.item_hash(draft) != revision:
                    raise ValueError('草稿已被其他操作更新，请重新打开后核验')
                if action == 'refresh':
                    review.check_source(draft, self.configs())
                    review.fetch_evidence(draft, self.queue, review.fetch_source)
                else:
                    patch = body.get('item', {})
                    if not isinstance(patch, dict) or set(patch) - EDITABLE:
                        raise ValueError('只能编辑公开申请字段；来源和核验状态由发布流程维护')
                    for key,value in patch.items():
                        if key in util.TEXT and not isinstance(value, str) or key in util.YEARS and value is not None and (type(value) is not int or not 2000 <= value <= 2100) or key in util.LISTS and (not isinstance(value, list) or any(not isinstance(v, str) for v in value)):
                            raise ValueError(f'{key}字段格式错误')
                    quotes, mappings = body.get('quotes', []), body.get('reviewed_fields', {})
                    if not isinstance(quotes, list) or any(not isinstance(v, str) or not v.strip() for v in quotes) or not isinstance(mappings, dict) or set(mappings)-EDITABLE:
                        raise ValueError('核验摘录格式错误')
                    for field,evidence in mappings.items():
                        if not isinstance(evidence, dict) or set(evidence)-{'quote','source_url','pages','locator','precision','content_sha256'} or not isinstance(evidence.get('quote'), str) or not isinstance(evidence.get('source_url'), str):
                            raise ValueError(f'{field}证据格式错误')
                        if 'pages' in evidence and (not isinstance(evidence['pages'], list) or any(type(p) is not int or not 1<=p<=100 for p in evidence['pages'])):
                            raise ValueError(f'{field}页码格式错误')
                    draft['item'].update(copy.deepcopy(patch))
                    draft.update(quotes=quotes, reviewed_fields=mappings)
                review.atomic_json(self.queue, queue)
        else:
            raise ValueError('不支持的核验操作')
        return self.detail(draft_id)

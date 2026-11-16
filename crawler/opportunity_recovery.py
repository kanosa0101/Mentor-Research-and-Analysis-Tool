"""Recover broken announcement links through registered official parent columns.

Discovery is not publication. Only an untouched draft with byte-backed, identical
old and new article meaning can move automatically; all facts use normal review.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
import yaml
from bs4 import BeautifulSoup

from crawler import opportunity_extract as extraction
from crawler import opportunity_review as review
from crawler import source_discovery as discovery
from crawler.opportunity_monitor import atomic_json, output_lock

IDENTITY = {'id', 'title', 'school_id', 'dept_id', 'unit', 'source_url'}


class _RequestBudgetExhausted(ValueError):
    pass


def read(root):
    path = Path(root) / 'cache/opportunity-recovery.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(version=1, records={})


def _title(draft):
    return draft.get('item', {}).get('title', '')


def _parents(root, configs, draft):
    item = draft['item']
    parents = []
    for seed in discovery.seeds(root, configs):
        if (seed.get('school') != item.get('school_id') or seed.get('dept', '') != item.get('dept_id', '')
                or seed.get('mode') == 'direct_page' or seed.get('content_scope_hint') == 'mentor_recruitment'):
            continue
        try:
            url = discovery.canonical(seed['url'], draft['source_url'])
        except ValueError:
            continue
        if urlsplit(url).scheme == 'https' and url != draft['source_url']:
            parents.append(url)
    return sorted(set(parents), key=lambda url: (url != draft['listing_url'], url))


def _old_document(root, draft):
    evidence = draft.get('fetch', {})
    digest = evidence.get('sha256', '')
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        return None
    # Resolve by content hash under this run's root, never an arbitrary stored path.
    path = Path(root) / 'cache/opportunity_evidence' / (digest + '.html')
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        return None
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        return None
    try:
        return raw, extraction.document(raw, draft['source_url'])
    except ValueError:
        return None


def _manual_reason(draft, old, new, url):
    if (draft.get('review') or draft.get('manual_edit') or draft.get('quotes') or draft.get('reviewed_fields')
            or any(draft.get(key) for key in ('notes', 'note', 'manual_notes'))
            or any(value for key, value in draft['item'].items() if key not in IDENTITY)):
        return '已有发布或人工字段；替代来源仅保留候选，不能覆盖事实'
    if not old:
        return '没有可校验的旧公告正文，不能证明同一则公告迁移'
    document = extraction.document(new, url)
    if old[1]['content_sha256'] != document['content_sha256']:
        return '旧新正文、标题或报名链接不完全一致，需核对变更及申请对象'
    for raw in (old[0], new):
        soup = BeautifulSoup(raw, 'html.parser')
        body = next((soup.select_one(s) for s in extraction.BODY_SELECTORS if soup.select_one(s)), soup.body or soup)
        if (body.select_one('img,iframe,object,embed') or extraction.embedded_pdf_urls(raw, url)
                or any(re.search(r'\.(?:pdf|docx?|xlsx?|zip)(?:$|[?#])', a.get('href', ''), re.I) for a in body.select('a[href]'))):
            return '正文含图片或附件，须共同核验完整申请证据后迁移'
    return ''


def _adopt(root, original, candidate, raw, now):
    queue_path = root / 'cache/opportunity_review.json'
    config_path = root / 'sites/opportunities.yaml'
    with output_lock(queue_path), output_lock(config_path):
        queue = review.read_queue(queue_path)
        draft = next((d for d in queue['drafts'] if d['id'] == original['id']), None)
        if not draft or review.item_hash(draft) != review.item_hash(original):
            raise ValueError('草稿在核验期间变化，本轮未迁移')
        configs = yaml.safe_load(config_path.read_text(encoding='utf-8'))['targets']
        if candidate['parent_url'] not in _parents(root, configs, draft):
            raise ValueError('父栏目登记或院系身份变化，本轮未迁移')
        if any(d['source_url'] == candidate['new_url'] for d in queue['drafts'] if d['id'] != draft['id']):
            raise ValueError('新地址已有独立草稿，保留两者供核对，未合并')
        reason = _manual_reason(draft, _old_document(root, draft), raw, candidate['new_url'])
        if reason:
            raise ValueError(reason)
        replacement = dict(candidate, adopted_at=now.isoformat())
        draft['source_url'] = candidate['new_url']
        draft['item']['source_url'] = candidate['new_url']
        draft['listing_url'] = candidate['parent_url']
        if review.fetch_evidence(draft, queue_path, lambda _: raw, now) is None:
            raise ValueError('替代正文未通过既有提取门禁，未迁移')
        draft.setdefault('source_replacements', []).append(replacement)
        atomic_json(queue_path, queue)


def run(root, *, limit=1, request_budget=16, fetcher=None, now=None):
    """Bounded resumable scan; never retry the dead article itself or publish facts."""
    # Parent/article discovery and revalidation each allow up to four HTTP requests.
    if not 1 <= limit <= 4 or not 1 <= request_budget <= 16:
        raise ValueError('每轮最多4条公告、16个官方页面请求')
    root = Path(root); now = now or datetime.now(timezone.utc)
    configs = yaml.safe_load((root / 'sites/opportunities.yaml').read_text(encoding='utf-8'))['targets']
    queue = review.read_queue(root / 'cache/opportunity_review.json')
    path = root / 'cache/opportunity-recovery.json'
    calls = 0

    def reserve():
        nonlocal calls
        if calls >= request_budget:
            raise _RequestBudgetExhausted('本轮官方来源请求预算已用完，下轮从当前父入口重新核验')
        calls += 1

    def fetch(url, parent):
        if fetcher:
            reserve()
            return fetcher(url, parent)
        # Redirect hops also consume budget; a moved column cannot multiply HTTP work.
        return discovery.fetch_html(url, parent, before_request=reserve)

    with output_lock(path):
        data = read(root); records = data['records']
        pending = [d for d in queue['drafts'] if review.source_error(d.get('fetch', {}))
                   and review.triage(d).get('classification') not in ('historical', 'irrelevant')]
        pending.sort(key=lambda d: (not bool(re.search(r'2028|2027.*冬令营', _title(d))),
                                   records.get(d['id'], {}).get('checked_at', ''), d['id']))
        attempted = adopted = 0
        for draft in pending:
            previous = records.get(draft['id'], {})
            if previous.get('next_check_at', '') > now.isoformat():
                continue
            if attempted >= limit or calls >= request_budget:
                break
            attempted += 1
            result = dict(id=draft['id'], original_url=draft['source_url'], title=_title(draft),
                          checked_at=now.isoformat(), next_check_at=(now + timedelta(hours=24)).isoformat(),
                          status='not_found', candidates=[], errors=[])
            if len(_title(draft)) < 8 or not re.search(r'20\d{2}|报名|申请|招募|招收', _title(draft)):
                result.update(status='not_announcement', reason='缺少具体年度和申请公告标题，疑似栏目，等待正文分类，暂不重复抓取',
                              next_check_at=(now + timedelta(days=7)).isoformat())
                records[draft['id']] = result
                continue
            parents = _parents(root, configs, draft)
            cursor = int(previous.get('parent_cursor', 0)) % max(1, len(parents))
            ordered = parents[cursor:] + parents[:cursor]
            visited = 0
            for parent in ordered[:2]:
                visited += 1
                try:
                    parent_raw = fetch(parent, parent)
                    matches = [r for r in discovery.links(parent_raw, parent)
                               if extraction.compact(r['title']) == extraction.compact(_title(draft))
                               and r['url'] != draft['source_url'] and urlsplit(r['url']).scheme == 'https']
                    if len(matches) > 1:
                        result.update(status='manual_required', reason='同一父栏目出现多个同名公告，无法确认唯一替代来源')
                        break
                    if not matches:
                        continue
                    url = matches[0]['url']
                    raw = fetch(url, parent)
                    doc = extraction.document(raw, url)
                    if extraction.compact(_title(draft)) not in extraction.compact(doc['text']):
                        raise ValueError('父栏目标题未在替代正文中完整出现')
                    candidate = dict(original_url=draft['source_url'], new_url=url, parent_url=parent,
                                     title=_title(draft), old_sha=draft.get('fetch', {}).get('sha256', ''),
                                     new_sha=hashlib.sha256(raw).hexdigest(), parent_sha=hashlib.sha256(parent_raw).hexdigest(),
                                     content_sha256=doc['content_sha256'], checked_at=now.isoformat())
                    result['candidates'].append(candidate)
                    reason = ('' if parent in {c['url'] for c in configs} else '替代父入口尚未接入活动监测，须先独立核准栏目')
                    reason = reason or _manual_reason(draft, _old_document(root, draft), raw, url)
                    if reason:
                        result.update(status='manual_required', reason=reason)
                        break
                    # Both the parent link and complete article must still agree immediately before adoption.
                    verified_parent = fetch(parent, parent)
                    if not any(r['url'] == url and extraction.compact(r['title']) == extraction.compact(_title(draft))
                               for r in discovery.links(verified_parent, parent)):
                        raise ValueError('父栏目链接在接续前变化，未迁移')
                    verified_raw = fetch(url, parent)
                    if extraction.document(verified_raw, url)['content_sha256'] != doc['content_sha256']:
                        raise ValueError('替代正文在接续前变化，未迁移')
                    candidate.update(new_sha=hashlib.sha256(verified_raw).hexdigest(), parent_sha=hashlib.sha256(verified_parent).hexdigest())
                    _adopt(root, draft, candidate, verified_raw, now)
                    result.update(status='adopted', reason='同院系父链、精确标题和旧新正文一致，空白草稿已接续取证，仍须既有发布核验')
                    adopted += 1
                    break
                except _RequestBudgetExhausted as error:
                    # Do not skip an unfinished parent after an earlier column
                    # consumed part of the budget. Re-fetch all evidence next time.
                    visited -= 1
                    result.update(status='budget_wait', reason=str(error))
                    result['errors'].append(dict(url=parent, error=str(error)))
                    break
                except (requests.RequestException, OSError, ValueError) as error:
                    result['errors'].append(dict(url=parent, error=str(error)[:400]))
            result['parent_cursor'] = (cursor + visited) % max(1, len(parents))
            result['parent_count'] = len(parents)
            if result['status'] == 'not_found':
                result['reason'] = '当前可信父入口未找到可核验的同名替代公告；不改来源、不推断申请条件'
            records[draft['id']] = result
        current_queue = review.read_queue(root / 'cache/opportunity_review.json')
        active = {d['id']: d['source_url'] for d in current_queue['drafts'] if review.source_error(d.get('fetch', {}))
                  and review.triage(d).get('classification') not in ('historical', 'irrelevant')}
        for record in records.values():
            record['active'] = active.get(record['id']) == record['original_url']
        active_records = [r for r in records.values() if r['active'] and r['status'] != 'adopted']
        data.update(checked_at=now.isoformat(), summary=dict(failed_drafts=len(active), attempted=attempted,
                    requests=calls, request_budget=request_budget, adopted=adopted,
                    manual_required=sum(r['status'] == 'manual_required' for r in active_records),
                    not_announcement=sum(r['status'] == 'not_announcement' for r in active_records),
                    budget_wait=sum(r['status'] == 'budget_wait' for r in active_records),
                    unresolved=sum(r['status'] == 'not_found' for r in active_records)))
        atomic_json(path, data)
        return data

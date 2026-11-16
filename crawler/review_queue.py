"""Evidence-bound maintenance priority and persistent, deduplicated SLA alerts."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from crawler import opportunity_extract as extract, opportunity_review as review
from crawler.review_preflight import effective as preflight
from crawler.opportunity_monitor import atomic_json, output_lock

CST = timezone(timedelta(hours=8))
LABELS = {0: '紧急', 1: '高', 2: '普通', 3: '低', 4: '已处理'}
SLA_HOURS = {0: 2, 1: 12, 2: 24, 3: 72, 4: None}


def moment(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def evidence_fields(draft, root):
    """Do not promote an AI/date suggestion to an urgent deadline without its HTML."""
    fetch = draft.get('fetch', {})
    if root is None or (fetch.get('status') != 'ok' and not review.evidence_error(fetch)):
        return {}
    digest = draft['fetch'].get('sha256', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        return {}
    path = Path(root) / 'cache/opportunity_evidence' / (digest + '.html')
    try:
        if path.is_symlink() or path.parent.is_symlink():
            return {}
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            return {}
        result = extract.extract(raw, draft['source_url'], draft.get('item', {}).get('title', ''))
        deadline = result.get('suggestions', {}).get('deadline')
        candidate = draft.get('item', {}).get('deadline') or draft.get('suggestions', {}).get('deadline')
        return dict(deadline=deadline if deadline and (not candidate or candidate == deadline) else None,
                    graduation_year=result.get('suggestions', {}).get('graduation_year'))
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def evaluate(draft, now=None, root=None):
    now = now or datetime.now(timezone.utc)
    item, fetch = draft.get('item', {}), draft.get('fetch', {})
    state = review.status(draft)
    triage = review.triage(draft).get('classification')
    first = moment(draft.get('first_seen')) or now
    opened = first
    day = now.astimezone(CST).date()
    target_year = day.year + (2 if day.month >= 9 else 1)
    reasons = []
    historical = triage in ('historical', 'irrelevant') or (item.get('cycle') == 'historical' and bool(draft.get('review')))
    if state == 'published':
        try:
            due_review = datetime.combine(date.fromisoformat(item['verified_at']) + timedelta(days=31),
                                          datetime.min.time(), tzinfo=CST)
            if due_review <= now and not historical:
                state, opened = 'verification_due', due_review
        except (ValueError, KeyError, TypeError):
            state = 'verification_due'
    if state == 'source_changed':
        opened = moment(fetch.get('checked_at')) or now
    fields = {} if historical or state == 'published' else evidence_fields(draft, root)
    hint = preflight(draft).get('priority_hint')
    current_hint = hint in ('target_cohort', 'current_winter')
    deadline = item.get('deadline') if state == 'published' else fields.get('deadline')
    days = None
    if deadline:
        days = (date.fromisoformat(deadline[:10]) - now.astimezone(CST).date()).days
    if historical or state == 'published':
        priority = 4
        reasons.append('已发布或已按官方证据归入历史/非报名，不占用当前审核SLA')
    elif days is not None and 0 <= days <= 3:
        priority = 0
        reasons.append('官方正文明确截止在3天内，需优先核验')
    elif state in ('source_changed', 'source_error', 'verification_due'):
        priority = 1
        reasons.append({'source_changed': '已发布原文变化，当前摘要需要复核',
                        'source_error': '官方来源不可读，须恢复取证或确认来源',
                        'verification_due': '内容核验已超过30天，须重新复核'}[state])
    elif days is not None and days < 0:
        priority = 3
        reasons.append('正文报名截止已过，优先分流历史；不表示已核验发布')
    elif hint == 'past_activity_evidence':
        priority = 3
        reasons.append('官方标题与页面日期属于往年，完整图文证据仍待核验；当前机会优先')
    elif (days is not None and 0 <= days <= 14) or triage == 'current' or fields.get('graduation_year') == target_year or current_hint:
        priority = 1
        reasons.append('正文明确当前准备届别、当前冬令营、已核实当前轮次或官方截止在14天内')
    else:
        priority = 2
        reasons.append('新机会或适用轮次待确认；不根据活动年份推断毕业届别')
    automatic = draft.get('automatic_review', {})
    reasons.extend(str(v)[:300] for v in automatic.get('reasons', [])[:5])
    fingerprint = hashlib.sha256(json.dumps([draft.get('source_url'), fetch.get('content_sha256') or fetch.get('sha256'),
        state == 'source_error', state == 'verification_due'], ensure_ascii=False).encode()).hexdigest()[:24]
    if root is not None:
        previous = read_alerts(root).get('records', {}).get(draft['id'])
        # Correcting a legacy evidence failure is not a newly discovered issue.
        # Keep its waiting clock and notification generation for the same bytes.
        if previous and previous.get('active') and review.evidence_error(fetch):
            legacy = hashlib.sha256(json.dumps([draft.get('source_url'), fetch.get('content_sha256') or fetch.get('sha256'),
                True, False], ensure_ascii=False).encode()).hexdigest()[:24]
            if previous.get('fingerprint') == legacy:
                fingerprint = legacy
        if previous and previous.get('active') and previous.get('fingerprint') == fingerprint:
            opened = moment(previous.get('opened_at')) or opened
    hours = SLA_HOURS[priority]
    due = opened + timedelta(hours=hours) if hours is not None else None
    return dict(id=draft['id'], title=item.get('title', ''), priority=priority, priority_label=LABELS[priority],
        reasons=reasons, deadline=deadline, deadline_verified=bool(deadline), sla_hours=hours,
        opened_at=opened.isoformat(), due_at=due.isoformat() if due else None,
        overdue=bool(due and due <= now), state=state, fingerprint=fingerprint,
        current_cycle_priority=bool(current_hint or triage == 'current' or fields.get('graduation_year') == target_year),
        automatic_state=automatic.get('state'), next_attempt_at=automatic.get('next_attempt_at'))


def ordered(queue, now=None, root=None):
    rows = [evaluate(d, now, root) for d in queue.get('drafts', [])]
    return sorted(rows, key=lambda r: (r['priority'], not r['current_cycle_priority'], not r['overdue'], r['deadline'] or '9999', r['opened_at'], r['id']))


def read_alerts(root):
    path = Path(root) / 'cache/review-alerts.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(version=1, records={}, active=[], events=[], summary={})


def refresh_alerts(root, queue=None, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    queue = queue if queue is not None else review.read_queue(root / 'cache/opportunity_review.json')
    path = root / 'cache/review-alerts.json'
    with output_lock(path):
        previous = read_alerts(root)
        records, events = previous.get('records', {}), previous.get('events', [])
        drafts = {d['id']: d for d in queue['drafts']}
        active, seen = [], set()
        for row in ordered(queue, now, root):
            ident = row['id']; seen.add(ident); old = records.get(ident)
            pending = row['priority'] < 4
            new_generation = bool(old and (not old['active'] or old['fingerprint'] != row['fingerprint']))
            generation = (old.get('generation', 1) if old else 1) + int(pending and new_generation)
            if pending and old and old['active'] and old['fingerprint'] == row['fingerprint']:
                row['opened_at'] = old['opened_at']
            elif pending and old:
                detected_times = [moment(drafts[ident].get('fetch', {}).get('checked_at')),
                                  moment(drafts[ident].get('manual_edit', {}).get('at'))]
                detected = max((d for d in detected_times if d), default=None)
                row['opened_at'] = min(now, detected or now).isoformat()
                events.append(dict(id=f'{ident}:{generation}:reopened', kind='reopened', draft_id=ident, at=now.isoformat(),
                                   reason='官方版本/来源状态变化或已解决条目重新进入审核'))
            if pending:
                row['due_at'] = (moment(row['opened_at']) + timedelta(hours=row['sla_hours'])).isoformat()
                row['overdue'] = moment(row['due_at']) <= now
                if row['overdue'] and not (old and old['active'] and old['fingerprint'] == row['fingerprint'] and old.get('overdue_notified')):
                    events.append(dict(id=f'{ident}:{generation}:overdue', kind='overdue', draft_id=ident,
                                       at=now.isoformat(), priority=row['priority'], title=row['title'], due_at=row['due_at']))
                active.append(row)
            elif old and old['active']:
                events.append(dict(id=f'{ident}:{generation}:resolved', kind='resolved', draft_id=ident, at=now.isoformat(),
                                   reason='已发布、已核验续检或已分流历史/非报名'))
            notified = pending and (row['overdue'] or bool(old and old['active'] and
                old['fingerprint'] == row['fingerprint'] and old.get('overdue_notified')))
            records[ident] = dict(fingerprint=row['fingerprint'], opened_at=row['opened_at'], active=pending,
                                  generation=generation, overdue_notified=notified)
        for ident in set(records) - seen:
            if records[ident]['active']:
                events.append(dict(id=f"{ident}:{records[ident]['generation']}:resolved", kind='resolved', draft_id=ident,
                                   at=now.isoformat(), reason='条目已从核验队列移除'))
                records[ident]['active'] = False
        active.sort(key=lambda r: (r['priority'], not r['overdue'], r['due_at'], r['id']))
        result = dict(version=1, checked_at=now.isoformat(), active=active, events=events[-500:], records=records,
                      summary=dict(active=len(active), overdue=sum(r['overdue'] for r in active), urgent=sum(r['priority'] == 0 for r in active)),
                      audience='maintainer', note='维护者审核时限提醒，不是申请截止承诺，也未向普通申请订阅者发送。')
        atomic_json(path, result)
        return result

"""Public policy/profile maintenance backlog; never read applicant account files."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.opportunity_monitor import atomic_json

INTAKE_REASONS = {
    'ai_budget_wait': '新政策：AI额度等待', 'unsupported_attachment': '新政策：附件格式待处理',
    'incomplete_evidence': '新政策：完整证据缺失', 'existing_policy_conflict': '新政策：既有范围冲突',
    'source_changed': '新政策：原文版本变化', 'historical_window': '新政策：历史报名窗口',
    'incomplete_fields': '新政策：关键条件缺失', 'ambiguous_scope': '新政策：适用范围待核对',
    'ai_review': '新政策：AI结果待核对', 'network_error': '新政策：来源或网络错误',
    'manual_review': '新政策：需人工核验', 'eligible': '新政策：通过核验待发布',
}


def moment(value):
    try:
        value = datetime.fromisoformat(value)
        return value if value.tzinfo else None
    except (TypeError, ValueError):
        return None


def refresh(root, now=None):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    active, available, failures, incomplete = [], {}, {}, []
    for category, path, key in (
        ('policy', 'cache/policy_revalidation/state.json', 'policies'),
        ('mentor', 'cache/mentor_quality/state.json', 'records'),
        ('policy_intake', 'cache/policy_intake/state.json', 'records'),
    ):
        source = root / path
        available[category] = source.is_file()
        if not source.is_file():
            failures[category] = 'MissingState'
            continue
        try:
            records = json.loads(source.read_text(encoding='utf-8'))[key]
            if not isinstance(records, dict):
                raise ValueError('Invalid public maintenance records')
            for ident, row in records.items():
                is_intake = category == 'policy_intake'
                if is_intake and row.get('status') in ('published', 'historical'):
                    continue
                pending_since = row.get('pending_since') or (row.get('first_seen') if is_intake else None)
                opened = moment(pending_since)
                due = opened + timedelta(hours=24) if opened else None
                reasons = row.get('reasons') or ([row['reason']] if row.get('reason') else [])
                reasons = [v if isinstance(v, str) else v.get('message') or v.get('detail') or v.get('kind', '') for v in reasons]
                status = row.get('status', 'unknown')
                timing_issue = None
                if status in ('confirmed', 'resolved'):
                    scheduled = moment(row.get('next_attempt') or row.get('next_check_at'))
                    if scheduled:
                        # Hourly maintenance has two full scheduling opportunities
                        # before a missed recheck is reported as stalled.
                        due = scheduled + timedelta(hours=2)
                        if due > now:
                            continue
                        opened = None
                        status = 'maintenance_overdue'
                        reasons = ['计划复检已超过两小时调度容差，尚无新的执行结果']
                    else:
                        timing_issue = '缺少有效的下次复检时间，无法判断维护是否持续运行'
                elif not opened or opened > now:
                    timing_issue = '缺少有效的首次待处理时间，无法判断处理时限'
                if timing_issue:
                    incomplete.append(dict(id=category + ':' + ident, reason=timing_issue))
                    status, opened, due = 'unknown', None, None
                    reasons = reasons + [timing_issue]
                # Retries update their timestamps; they must not reset alert delivery.
                fingerprint = hashlib.sha256(json.dumps(
                    [category, ident, due.isoformat() if status == 'maintenance_overdue' else pending_since, row.get('policy_sha256')],
                    ensure_ascii=False).encode()).hexdigest()[:24]
                urls = row.get('source_urls', {})
                urls = list(urls.values()) if isinstance(urls, dict) else []
                if is_intake:
                    urls.extend(row[key] for key in ('source_url', 'listing_url') if row.get(key))
                evidence = row.get('evidence')
                if isinstance(evidence, dict) and evidence.get('source_url'):
                    urls.append(evidence['source_url'])
                elif isinstance(evidence, list):
                    urls.extend(v['url'] for v in evidence if isinstance(v, dict) and v.get('url'))
                reason_code = row.get('reason_code') or ('manual_review' if is_intake else 'policy_review' if category == 'policy' else 'unclassified')
                action = row.get('next_action') or ('retry' if status == 'retry' else 'manual_review')
                active.append(dict(id=category + ':' + ident, category=category,
                    title=row.get('title') or ident, status=status, reasons=reasons,
                    reason_code=reason_code,
                    category_label=row.get('category_label') or (INTAKE_REASONS.get(reason_code, '新政策核验') if is_intake else '政策证据与版本' if category == 'policy' else '等待原因分类'),
                    next_action=action,
                    action_label=row.get('action_label') or (action if is_intake and row.get('next_action') else '按计划重试' if status == 'retry' else '核对原文与处理规则'),
                    replacement=row.get('replacement'),
                    opened_at=opened.isoformat() if opened else None,
                    due_at=due.isoformat() if due else None, overdue=bool(due and due <= now),
                    next_attempt_at=row.get('next_attempt_at') or row.get('next_attempt') or row.get('next_check_at'),
                    last_attempt_at=row.get('last_attempt') or row.get('checked_at'),
                    source_urls=list(dict.fromkeys(urls)), priority=1 if due and due <= now else 2, fingerprint=fingerprint))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            failures[category] = type(error).__name__
    active.sort(key=lambda r: (r['priority'], r['due_at'] or '', r['id']))
    result = dict(checked_at=now.isoformat(timespec='seconds'), available=available,
        failures=failures, incomplete=incomplete, active=active,
        breakdown=dict(reasons=dict(Counter(r['reason_code'] for r in active)),
            actions=dict(Counter(r['next_action'] for r in active)),
            never_attempted=sum(not r['last_attempt_at'] for r in active)),
        summary=dict(active=len(active), overdue=sum(r['overdue'] for r in active),
            policies=sum(r['category'] == 'policy' for r in active),
            new_policies=sum(r['category'] == 'policy_intake' for r in active),
            mentors=sum(r['category'] == 'mentor' for r in active)),
        audience='maintainer', note='24小时为待处理维护时限；计划复检另容许两小时调度延迟。均不是申请截止，也不向申请用户发送。')
    atomic_json(root / 'cache/quality-alerts.json', result)
    return result

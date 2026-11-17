"""Public policy/profile maintenance backlog; never read applicant account files."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.opportunity_monitor import atomic_json

INTAKE_REASONS = {
    'awaiting_evidence': '新政策：已发现待核验',
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


def field_gaps(root, now):
    path = root / 'cache/mentor_quality/field-gaps.json'
    labels = {'email': '公开邮箱', 'research_direction_raw': '研究方向', 'supervisor': '招生资格', 'title': '职称'}
    counts = {key: Counter() for key in ('by_field', 'by_unit', 'by_status', 'by_reason', 'optional_by_field', 'secondary_email_by_reason')}
    entries = []
    records = json.loads(path.read_text(encoding='utf-8'))['records']
    if not isinstance(records, dict):
        raise ValueError('Invalid mentor field records')
    for ident, row in records.items():
        renewal = row.get('secondary_email') or {}
        if renewal.get('status') in ('retry','waiting_source'):
            code=renewal.get('reason_code','secondary_email_unconfirmed')
            counts['secondary_email_by_reason'][code]+=1
            opened=renewal.get('failed_since') or renewal.get('checked_at')
            next_at=renewal.get('next_check_at')
            scheduled=moment(next_at)
            overdue=bool(scheduled and scheduled+timedelta(hours=2)<=now)
            due=scheduled+timedelta(hours=2) if overdue else None
            source=(renewal.get('registration') or {}).get('source')
            entries.append(dict(id='mentor_email_recheck:'+ident,category='mentor',title=row.get('name') or ident,
                status='maintenance_overdue' if overdue else renewal['status'],reason_code=code,category_label='二级来源邮箱复核',
                reasons=[renewal.get('reason','当前来源尚未重新确认旧邮箱')],next_action='retry_secondary_email',action_label='按计划重新核验官方来源',
                opened_at=opened,due_at=due.isoformat() if due else None,overdue=overdue,priority=1 if overdue else 2,
                next_attempt_at=next_at,last_attempt_at=renewal.get('checked_at'),source_urls=[source] if source else [],
                fingerprint=hashlib.sha256(json.dumps(['secondary_email',ident,opened]).encode()).hexdigest()[:24]))
        fields = {}
        for key, value in row['fields'].items():
            if value.get('status') == 'resolved':
                continue
            if key == 'homepage' or value.get('optional'):
                counts['optional_by_field'][key] += 1
            else:
                fields[key] = value
        if not fields:
            continue
        for key, value in fields.items():
            counts['by_field'][key] += 1
            counts['by_unit'][row.get('unit', '')] += 1
            counts['by_status'][value.get('status', 'unknown')] += 1
            counts['by_reason'][value.get('reason_code', 'unknown')] += 1
        checked = [v for v in fields.values() if moment(v.get('checked_at'))]
        pending = [v for v in checked if v.get('status') != 'waiting_source']
        clocks = [moment(v.get('pending_since') or v.get('first_seen')) for v in pending]
        opened = min(clocks) if clocks and all(clocks) else None
        opened = opened if opened and opened <= now else None
        due = opened + timedelta(hours=24) if opened else None
        status = ('manual_review' if any(v.get('status') == 'manual_review' for v in pending) else
                  'pending' if pending else 'waiting_source' if checked else 'queued')
        scheduled = [moment(v.get('next_check_at')) for v in checked if v.get('status') == 'waiting_source']
        scheduled = [value for value in scheduled if value]
        if not pending and scheduled and min(scheduled) + timedelta(hours=2) <= now:
            status, due = 'maintenance_overdue', min(scheduled) + timedelta(hours=2)
        next_times = [v['next_check_at'] for v in fields.values() if moment(v.get('next_check_at'))]
        attempted = [v['checked_at'] for v in fields.values() if moment(v.get('checked_at'))]
        entries.append(dict(id='mentor_fields:' + ident, category='mentor_fields', title=row.get('name') or ident,
            status=status, fields=list(fields), field_labels=[labels.get(key, key) for key in fields],
            reasons=[labels.get(key, key) + '：' + v.get('reason', v.get('reason_code', '待核验')) for key, v in fields.items()],
            reason_code='mentor_field_gap', category_label='导师公开资料缺口',
            next_action='review_fields' if pending else 'check_queued_fields' if not checked else 'wait_for_source',
            action_label='核验缺失字段与官方出处' if pending else '按来源轮转进行首次核验' if not checked else '等待官方资料更新，按计划复查',
            discovered_at=min((v.get('first_seen') for v in fields.values() if moment(v.get('first_seen'))), default=None),
            opened_at=opened.isoformat() if opened else None, due_at=due.isoformat() if due else None,
            overdue=bool(due and due <= now), priority=1 if due and due <= now else 2 if pending else 3,
            next_attempt_at=min(next_times) if next_times else None, last_attempt_at=max(attempted) if attempted else None,
            source_urls=list(dict.fromkeys(v['source_url'] for v in fields.values() if v.get('source_url'))),
            fingerprint=hashlib.sha256(json.dumps([ident, sorted((k, v.get('pending_since') or v.get('first_seen')) for k, v in fields.items())]).encode()).hexdigest()[:24]))
    return entries, {key: dict(value) for key, value in counts.items()}


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
    available['mentor_fields'] = (root / 'cache/mentor_quality/field-gaps.json').is_file()
    field_breakdown = {}
    try:
        if not available['mentor_fields']:
            failures['mentor_fields'] = 'MissingState'
        else:
            fields, field_breakdown = field_gaps(root, now)
            active.extend(fields)
            incomplete.extend(dict(id=r['id'], reason='缺少有效的首次待处理时间，无法判断处理时限')
                              for r in fields if r['status'] in ('pending', 'manual_review') and not r['opened_at'])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        failures['mentor_fields'] = type(error).__name__
    active.sort(key=lambda r: (r['priority'], r['due_at'] or '', r['id']))
    result = dict(checked_at=now.isoformat(timespec='seconds'), available=available,
        failures=failures, incomplete=incomplete, active=active, mentor_field_breakdown=field_breakdown,
        breakdown=dict(reasons=dict(Counter(r['reason_code'] for r in active)),
            actions=dict(Counter(r['next_action'] for r in active)),
            never_attempted=sum(not r['last_attempt_at'] for r in active)),
        summary=dict(active=len(active), overdue=sum(r['overdue'] for r in active),
            policies=sum(r['category'] == 'policy' for r in active),
            new_policies=sum(r['category'] == 'policy_intake' for r in active),
            mentors=sum(r['category'] == 'mentor' for r in active),
            mentor_field_gaps=sum(r['category'] == 'mentor_fields' for r in active),
            missing_fields=sum(field_breakdown.get('by_field', {}).values())),
        audience='maintainer', note='24小时为新政策及已核验问题的处理时限。独立个人或课题组主页为选填项。导师尚未核验的字段库存与等待官方补充不计此时限。计划复检另容许两小时调度延迟。均不是申请截止，也不向申请用户发送。')
    atomic_json(root / 'cache/quality-alerts.json', result)
    return result

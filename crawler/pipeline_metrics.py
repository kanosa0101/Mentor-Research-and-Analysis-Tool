"""Read-only public maintenance metrics; never read private applicant records."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from crawler import opportunity_review as review


def load(root, name):
    path = Path(root) / name
    try:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (ValueError, OSError):
        return {'unavailable': True}


def seconds(start, end):
    try:
        return max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
    except (ValueError, TypeError):
        return None


def summarize(root, queue=None, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec='seconds')
    queue = queue if queue is not None else load(root, 'cache/opportunity_review.json')
    drafts = queue.get('drafts', [])
    pending = [d for d in drafts if review.status(d) != 'published' and review.triage(d).get('classification') not in ('historical', 'irrelevant')]
    waits = [s for d in pending if (s := seconds(d.get('first_seen'), stamp)) is not None]
    published = [s for d in drafts if (s := seconds(d.get('first_seen'), d.get('review', {}).get('reviewed_at'))) is not None]
    publication = [s for d in drafts if (s := seconds(d.get('review', {}).get('reviewed_at'), d.get('review', {}).get('published_at'))) is not None]
    live = load(root, 'cache/opportunities_live.json')
    sources = [s for s in live.get('sources', {}).values() if s.get('status') != 'removed']
    return dict(checked_at=stamp, queue_count=len(drafts), pending_active=len(pending),
        review_states=dict(Counter(review.status(d) for d in drafts)),
        triage_states=dict(Counter(review.triage(d).get('classification', 'unknown') for d in drafts)),
        oldest_pending_seconds=max(waits, default=None), published_samples=len(published),
        pending_over_24h=sum(s >= 86400 for s in waits), review_to_publish_max_seconds=max(publication, default=None),
        discovery_to_review_max_seconds=max(published, default=None),
        source_count=len(sources), source_errors=sum(s.get('status') == 'error' for s in sources),
        source_overdue=sum(s.get('status') != 'removed' and s.get('next_check_at', stamp) < stamp for s in sources),
        monitoring=live.get('summary', {}), last_notification_delivery=load(root, 'var/push/last_delivery.json'),
        maintenance_alerts=load(root, 'cache/maintenance-alerts.json'),
        note='等待时长从本系统首次发现计起，不是官网发布到发现的延迟；旧记录缺少时间时不估算。')

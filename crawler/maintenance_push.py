"""Opt-in maintainer alerts, isolated from applicant subscriptions and records."""
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from crawler import push_util
from crawler.opportunity_monitor import atomic_json, output_lock


def paths(root):
    folder = Path(root) / 'var/review-notifications'
    return folder / 'subscriptions.json', folder / 'last-delivery.json'


def read(path):
    return json.loads(path.read_text(encoding='utf8')) if path.exists() else {}


def settings(root):
    cfg = push_util.config(root)
    return dict(enabled=bool(cfg.get('public_key') and (Path(root) / 'var/push/vapid.pem').is_file()),
                public_key=cfg.get('public_key'), last_delivery=read(paths(root)[1]),
                audience='maintainer', requires_explicit_subscription=True)


def subscribe(root, body):
    if not settings(root)['enabled']:
        raise ValueError('维护推送服务未配置，可继续使用工作台内提醒')
    subscription = body.get('subscription')
    push_util.validate_subscription(subscription)
    token = body.get('token') or secrets.token_urlsafe(32)
    if not isinstance(token, str) or not 32 <= len(token) <= 100:
        raise ValueError('订阅凭据格式错误')
    path, _ = paths(root)
    with output_lock(path):
        data = read(path)
        old = next((s for s in data.values() if s['subscription']['endpoint'] == subscription['endpoint']), None)
        digest = hashlib.sha256(token.encode()).hexdigest()
        if old and not secrets.compare_digest(old['token_hash'], digest):
            raise ValueError('订阅凭据不匹配，请先在浏览器取消旧订阅')
        if not old and len(data) >= 20:
            raise ValueError('维护者订阅数量已达上限')
        ident = old['id'] if old else secrets.token_hex(16)
        data[ident] = dict(old or {}, id=ident, subscription=subscription, token_hash=digest,
                           deliveries=(old or {}).get('deliveries', {}))
        atomic_json(path, data)
    return dict(id=ident, token=token)


def owned(data, body):
    ident, token = body.get('id'), body.get('token')
    if not isinstance(ident, str) or not isinstance(token, str):
        raise ValueError('维护订阅凭据缺失')
    row = data.get(ident)
    if not row or not secrets.compare_digest(row['token_hash'], hashlib.sha256(token.encode()).hexdigest()):
        raise ValueError('维护订阅凭据不匹配')
    return row


def unsubscribe(root, body):
    path, _ = paths(root)
    with output_lock(path):
        data = read(path)
        if (isinstance(body.get('id'), str) and isinstance(body.get('token'), str)
                and 32 <= len(body['token']) <= 100 and body['id'] not in data):
            return dict(removed=True)
        row = owned(data, body)
        del data[row['id']]
        atomic_json(path, data)
    return dict(removed=True)


def test_notification(root, body, sender=None):
    path, _ = paths(root)
    with output_lock(path):
        row = owned(read(path), body)
    sender = sender or (lambda sub, payload: push_util.send(root, sub, payload))
    try:
        code = sender(row['subscription'], dict(title='维护提醒已连接', body='这是你主动请求的测试通知。',
                      url='/review.html', tag='maintainer-test'))
    except Exception:
        raise ValueError('维护推送暂未送达发送服务，请稍后重试') from None
    if not 200 <= code < 300:
        raise ValueError('推送服务未接受测试通知')
    return dict(accepted=True, note='服务接受不等于浏览器已经展示')


def dispatch(root, alerts, sender=None):
    path, report_path = paths(root)
    result = dict(attempted_at=datetime.now(timezone.utc).isoformat(), sent=0, failed=0, expired=0, retry_exhausted=0,
                  audience='maintainer', disabled=not settings(root)['enabled'])
    if result['disabled']:
        return result
    rows = [r for r in alerts.get('active', []) if r.get('overdue')]
    pending = {hashlib.sha256((r['id'] + '|' + r['fingerprint'] + '|' + r['due_at']).encode()).hexdigest(): r
               for r in rows}
    sender = sender or (lambda sub, payload: push_util.send(root, sub, payload))
    # One dispatcher per store; subscription edits use a separate short-lived lock.
    with output_lock(path.with_name('dispatch')):
        with output_lock(path):
            subscribers = list(read(path).values())
        for sub in subscribers:
            with output_lock(path):
                current = read(path).get(sub['id'])
                if current is None:
                    continue
                result['retry_exhausted'] += sum(not current['deliveries'].get(k, {}).get('sent')
                    and current['deliveries'].get(k, {}).get('attempts', 0) >= 5 for k in pending)
                remaining = {k:r for k,r in pending.items() if not current['deliveries'].get(k, {}).get('sent')
                             and current['deliveries'].get(k, {}).get('attempts', 0) < 5}
            if not remaining:
                continue
            first = min(remaining.values(), key=lambda r: (r['priority'], r['due_at']))
            code = 0
            try:
                code = sender(current['subscription'], dict(title=f"{len(remaining)}条审核任务已超时",
                    body='打开维护工作台核对证据、处理阻断；此提醒不发送给申请用户。',
                    url=('/review.html#quality-panel' if first.get('category') in ('policy', 'mentor') else
                         '/review.html?draft=' + quote(first['id'], safe='')), tag='maintainer-overdue'))
            except Exception as error:
                code = getattr(getattr(error, 'response', None), 'status_code', 0)
            with output_lock(path):
                data = read(path)
                if sub['id'] not in data:
                    continue
                if code in (404, 410):
                    del data[sub['id']]
                    result['expired'] += 1
                else:
                    success = 200 <= code < 300
                    deliveries = data[sub['id']]['deliveries']
                    for key in remaining:
                        deliveries[key] = dict(attempts=deliveries.get(key, {}).get('attempts', 0) + 1, sent=success)
                    # Resolved generations do not need delivery history indefinitely.
                    data[sub['id']]['deliveries'] = {k:v for k,v in deliveries.items() if k in pending}
                    result['sent' if success else 'failed'] += 1
                atomic_json(path, data)
    result['completed_at'] = datetime.now(timezone.utc).isoformat()
    atomic_json(report_path, result)
    return result

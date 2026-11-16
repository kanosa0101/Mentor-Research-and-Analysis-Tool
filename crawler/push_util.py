"""Opt-in public opportunity alerts. Private application data never enters this store."""
import base64
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from crawler import opportunity_util

FIELDS = ('title', 'eligibility', 'materials', 'deadline', 'deadline_note', 'registration_start',
          'application_url', 'application_method', 'contact', 'research_directions', 'application_window')


def semantic(value):
    """Ignore display whitespace and ordering of independent requirements only."""
    if isinstance(value, str):
        return re.sub(r'\s+', ' ', value).strip()
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((semantic(v) for v in value), key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True))
    return value


def config(root):
    path = Path(root) / 'var/push/config.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


@contextmanager
def database(root):
    folder = Path(root) / 'var/push'
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'alerts.sqlite', timeout=15)
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE IF NOT EXISTS subscriptions (
        id TEXT PRIMARY KEY, endpoint TEXT UNIQUE, body TEXT, filters TEXT, token TEXT, start_id INTEGER);
      CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, key TEXT UNIQUE, body TEXT);
      CREATE TABLE IF NOT EXISTS deliveries (subscriber TEXT, event INTEGER, attempts INTEGER DEFAULT 0,
        sent INTEGER DEFAULT 0, PRIMARY KEY(subscriber,event));
      CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, body TEXT);
    ''')
    try:
        with db:
            yield db
    finally:
        db.close()


def validate_subscription(body):
    if not isinstance(body, dict) or set(body) - {'endpoint', 'keys', 'expirationTime'}:
        raise ValueError('浏览器订阅结构错误')
    url = urlsplit(body.get('endpoint', ''))
    host = url.hostname or ''
    allowed = host in ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com') or host.endswith('.notify.windows.com')
    if url.scheme != 'https' or not allowed or url.port not in (None, 443) or url.username or url.password or url.fragment:
        raise ValueError('不支持此浏览器推送服务地址')
    if len(body['endpoint']) > 4096 or set(body.get('keys', {})) != {'auth', 'p256dh'}:
        raise ValueError('浏览器订阅密钥错误')
    for name, size in (('auth', 16), ('p256dh', 65)):
        value = body['keys'][name]
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError('浏览器订阅密钥错误')
        try:
            decoded = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        except ValueError as error:
            raise ValueError('浏览器订阅密钥错误') from error
        if len(decoded) != size or name == 'p256dh' and decoded[0] != 4:
            raise ValueError('浏览器订阅密钥错误')


def subscribe(root, body):
    subscription = body.get('subscription')
    validate_subscription(subscription)
    filters = body.get('filters', {})
    if not isinstance(filters, dict) or set(filters) != {'school', 'kind', 'year', 'query', 'discoveries'} or any(
            not isinstance(filters[k], str) or len(filters[k]) > 200 for k in ('school', 'kind', 'year', 'query')) or type(filters['discoveries']) is not bool:
        raise ValueError('订阅条件错误')
    token = body.get('token') or secrets.token_urlsafe(32)
    if not isinstance(token, str) or not 32 <= len(token) <= 100:
        raise ValueError('订阅凭据错误')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with database(root) as db:
        old = db.execute('SELECT * FROM subscriptions WHERE endpoint=?', (subscription['endpoint'],)).fetchone()
        if not old and db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0] >= 10000:
            raise ValueError('当前订阅数量已达上限')
        if old and not secrets.compare_digest(old['token'], digest):
            raise ValueError('订阅凭据不匹配，请在浏览器取消后重新订阅')
        sid = old['id'] if old else secrets.token_hex(16)
        start = old['start_id'] if old else db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
        db.execute('INSERT OR REPLACE INTO subscriptions VALUES (?,?,?,?,?,?)',
                   (sid, subscription['endpoint'], json.dumps(subscription), json.dumps(filters), digest, start))
    return {'id': sid, 'token': token}


def owned(db, body):
    if not isinstance(body.get('id'), str) or not isinstance(body.get('token'), str):
        raise ValueError('订阅凭据缺失')
    row = db.execute('SELECT * FROM subscriptions WHERE id=?', (body['id'],)).fetchone()
    if not row or not secrets.compare_digest(row['token'], hashlib.sha256(body['token'].encode()).hexdigest()):
        raise ValueError('订阅凭据无效')
    return row


def unsubscribe(root, body):
    with database(root) as db:
        row = owned(db, body)
        db.execute('DELETE FROM subscriptions WHERE id=?', (row['id'],))
        db.execute('DELETE FROM deliveries WHERE subscriber=?', (row['id'],))


def recent(root):
    if not (Path(root) / 'var/push/alerts.sqlite').exists():
        return []
    db=sqlite3.connect('file:'+(Path(root)/'var/push/alerts.sqlite').as_posix()+'?mode=ro',uri=True)
    try:
        allowed = {item['id'] for item in opportunity_util.public_catalog(opportunity_util.load(root))['opportunities']}
        return [event for row in db.execute('SELECT body FROM events ORDER BY id DESC LIMIT 200')
                if (event := json.loads(row[0])).get('opportunity_id') in allowed][:50]
    finally:
        db.close()


def record(root, catalog, monitoring=None, day=None):
    """First scan is a baseline. Later public changes and explicit deadlines become events."""
    day = day or opportunity_util.today()
    added = 0
    reviews = {r.get('opportunity_id'):r for r in catalog.get('review_log', [])}
    with database(root) as db:
        initial = db.execute("SELECT 1 FROM snapshots WHERE key='initialized'").fetchone() is None
        # Existing installations baseline the scope migration once; reclassification is not a launch.
        scope_baseline = db.execute("SELECT 1 FROM snapshots WHERE key='content_scope_v1'").fetchone() is None
        def event(key, kind, title, item, changes=None):
            nonlocal added
            body = dict(id=key, kind=kind, title=title, opportunity_id=item.get('id'),
                        school=item.get('school_name', ''), activity_kind=item.get('kind', ''),
                        graduation_year=item.get('graduation_year'),
                        summary='；'.join(item.get('eligibility', [])),
                        search_text=' '.join([item.get('title', ''), item.get('unit', ''), *item.get('eligibility', []),
                                             *[' '.join(r.get(k, '') for k in ('department','direction','contact','email')) for r in item.get('research_directions', [])]]),
                        changes=changes or [], source_url=item['source_url'],
                        timeline={k:reviews.get(item.get('id'), {}).get(k) for k in ('first_seen','reviewed_at','published_at')},
                        url='/opportunities.html?id='+item['id'] if kind != 'discovered' else '/opportunities.html?candidate='+item['id']+'#monitor-candidates',
                        created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            body['content_scope'] = opportunity_util.content_scope(item)
            added += db.execute('INSERT OR IGNORE INTO events(key,body) VALUES (?,?)', (key, json.dumps(body, ensure_ascii=False))).rowcount
        for item in catalog['opportunities']:
            activity = opportunity_util.content_scope(item) == 'institutional_activity'
            key = 'item:' + item['id']
            previous = db.execute('SELECT body FROM snapshots WHERE key=?', (key,)).fetchone()
            snapshot = {k: item.get(k) for k in (*FIELDS, 'source_state', 'cycle')}
            changed = [k for k in FIELDS if previous and semantic(json.loads(previous['body']).get(k)) != semantic(snapshot[k])]
            if not initial and not scope_baseline and activity and item['cycle'] == 'current' and item['source_state'] == 'verified':
                fingerprint = hashlib.sha256(json.dumps(semantic(snapshot), sort_keys=True).encode()).hexdigest()[:20]
                if not previous or json.loads(previous['body']).get('source_state') != 'verified' or json.loads(previous['body']).get('cycle') != 'current':
                    event('published:'+item['id']+':'+fingerprint, 'published', '已核验机会：'+item['title'], item)
                elif changed:
                    event('changed:'+item['id']+':'+fingerprint, 'changed', '申请信息有变化：'+item['title'], item, changed)
            db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?)', (key, json.dumps(snapshot)))
            if not initial and not scope_baseline and activity and opportunity_util.state(item, day) == 'open' and item.get('deadline'):
                days = (datetime.fromisoformat(item['deadline'][:10]).date() - day).days
                if days in (0, 1, 3):
                    event(f'deadline:{item["id"]}:{item["deadline"]}:{days}', 'deadline',
                          ('今天截止：' if days == 0 else f'{days}天后截止：')+item['title'], item)
        for candidate in (monitoring or {}).get('candidates', []):
            key = 'candidate:' + candidate['url']
            previous = db.execute('SELECT 1 FROM snapshots WHERE key=?', (key,)).fetchone()
            published = candidate.get('publication_date')
            if (not initial and not scope_baseline and not previous and
                opportunity_util.content_scope(candidate) == 'institutional_activity' and
                candidate.get('discovery_status') == 'discovered_later' and published and
                0 <= (day-datetime.fromisoformat(published).date()).days <= 30):
                school = next((o['school_name'] for o in catalog['opportunities'] if o['school_id'] == candidate['school']), candidate['unit'])
                kind = next((key for word,key in (('冬令营','winter_camp'),('夏令营','summer_camp'),('推免','recommend'),('科创计划','research_program')) if word in candidate['title']), '')
                item = dict(id=candidate['id'], title=candidate['title'], unit=candidate['unit'], source_url=candidate['url'], school_name=school, kind=kind)
                event(key, 'discovered', '待核验公告：'+candidate['title'], item)
            db.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?)', (key, '{}'))
        db.execute("INSERT OR IGNORE INTO snapshots VALUES ('initialized','{}')")
        db.execute("INSERT OR IGNORE INTO snapshots VALUES ('content_scope_v1','{}')")
    return added


def matches(event, filters):
    if event['kind'] == 'discovered' and not filters['discoveries']:
        return False
    return (not filters['school'] or filters['school'] in event['school']+' '+event['search_text']) and (
        not filters['kind'] or filters['kind'] == event['activity_kind']) and (
        not filters['year'] or (not event['graduation_year'] if filters['year'] == 'unknown'
                                else str(event['graduation_year']) == filters['year'])) and (
        not filters['query'] or filters['query'].lower() in event['search_text'].lower())


def send(root, subscription, payload):
    import requests
    from pywebpush import webpush
    from py_vapid import Vapid
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    cfg = config(root)
    origin = urlsplit(cfg['origin'])
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('', '/'):
        raise ValueError('通知服务 HTTPS 地址错误')
    # py-vapid's subject URL regex rejects valid ports; validate the origin here.
    key = load_pem_private_key((Path(root) / 'var/push/vapid.pem').read_bytes(), password=None)
    vapid = Vapid(private_key=key, conf={'no-strict': True})
    with requests.Session() as session:
        session.trust_env = False
        response = webpush(subscription_info=subscription, data=json.dumps(payload, ensure_ascii=False),
                           vapid_private_key=vapid,
                           vapid_claims={'sub': cfg['origin']}, ttl=3600, timeout=15, requests_session=session)
    return response.status_code


def dispatch(root, sender=None):
    sender = sender or (lambda subscription, payload: send(root, subscription, payload))
    result = dict(sent=0, failed=0, expired=0, attempted_at=datetime.now(timezone.utc).isoformat(timespec='seconds'), max_successful_event_age_seconds=None, max_publish_to_send_seconds=None)
    allowed = {item['id'] for item in opportunity_util.public_catalog(opportunity_util.load(root))['opportunities']}
    with database(root) as db:
        subscribers = db.execute('SELECT * FROM subscriptions').fetchall()
    for sub in subscribers:
        with database(root) as db:
            rows = db.execute('SELECT e.*,COALESCE(d.attempts,0) AS attempts FROM events e LEFT JOIN deliveries d ON d.event=e.id AND d.subscriber=? WHERE e.id>? AND COALESCE(d.sent,0)=0 AND COALESCE(d.attempts,0)<5 ORDER BY e.id LIMIT 100', (sub['id'],sub['start_id'])).fetchall()
        for row in rows:
            event = json.loads(row['body'])
            with database(root) as db:
                if not db.execute('SELECT 1 FROM subscriptions WHERE id=?',(sub['id'],)).fetchone():break
                if event.get('opportunity_id') not in allowed or not matches(event,json.loads(sub['filters'])):
                    db.execute('INSERT OR REPLACE INTO deliveries VALUES (?,?,0,1)',(sub['id'],row['id']))
                    continue
            code = 0
            try:
                code = sender(json.loads(sub['body']), {'title': event['title'], 'body': '打开官方来源，核对条件、材料与时间。', 'url': event['url'], 'tag': event['id']})
            except Exception as error:
                code = getattr(getattr(error, 'response', None), 'status_code', 0)
            with database(root) as db:
                if code in (404,410):
                    db.execute('DELETE FROM subscriptions WHERE id=?',(sub['id'],))
                    db.execute('DELETE FROM deliveries WHERE subscriber=?',(sub['id'],))
                    result['expired'] += 1
                    break
                success = 200 <= code < 300
                if db.execute('SELECT 1 FROM subscriptions WHERE id=?',(sub['id'],)).fetchone():
                    db.execute('INSERT OR REPLACE INTO deliveries VALUES (?,?,?,?)',(sub['id'],row['id'],row['attempts']+1,int(success)))
                result['sent' if success else 'failed'] += 1
                if success:
                    try:
                        age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(event['created_at'])).total_seconds()))
                        result['max_successful_event_age_seconds'] = max(result['max_successful_event_age_seconds'] or 0, age)
                        published_at = event.get('timeline', {}).get('published_at')
                        if published_at:
                            elapsed = max(0, int((datetime.now(timezone.utc)-datetime.fromisoformat(published_at)).total_seconds()))
                            result['max_publish_to_send_seconds'] = max(result['max_publish_to_send_seconds'] or 0, elapsed)
                    except (KeyError, ValueError, TypeError):
                        pass
    result['completed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return result


def test_notification(root, body):
    with database(root) as db:
        sub = owned(db, body)
    code = send(root, json.loads(sub['body']), {'title': '导师库通知已连接', 'body': '这是你主动请求的测试通知。', 'url': '/opportunities.html', 'tag': 'connection-test'})
    if not 200 <= code < 300:
        raise ValueError('推送服务未接受测试通知')
    return {'accepted': True}

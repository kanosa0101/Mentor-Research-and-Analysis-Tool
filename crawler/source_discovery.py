"""Discover bounded official columns; verified columns may enter monitoring, never publication."""
import hashlib
import ipaddress
import json
import os
import posixpath
import re
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
import yaml
from bs4 import BeautifulSoup

from crawler.opportunity_monitor import activity_title, atomic_json, output_lock
from crawler.opportunity_review import institution

MAX_BYTES = 2 * 1024 * 1024
COLUMN = re.compile(r'招生|招募|研究生教育|人才培养|培养招生|夏令营|冬令营|暑期学校|科研实践|科研实习|科创计划')
EXCLUDED = re.compile(r'登录|注册|搜索|检索|结果|公示|名单|回顾|总结|中小学|中学生|本科招生|出国|海外|(?<![a-z0-9])(?:login|logout|search|signin)(?![a-z0-9])', re.I)
ARTICLE_PATH = re.compile(r'/(?:info/[^/]+/[^/]+\.(?:htm|html)|(?:20\d{2})/(?:\d{2}|\d{4})/|ShowArticle/news/|article/\d+|[^/]*c\d+a\d+/page\.htm)|/t20\d{6}_|/20\d{6,}\.html', re.I)
ARTICLE_BODY = '.wp_articlecontent, #vsb_content, #vsb_content_2, .TRS_Editor, .v_news_content'
CONTENT_REASONS = {
    '这是单条公告正文，不能用正文或页脚链接充当持续更新栏目': 'announcement_not_column',
    '未解析到独立活动公告链接；不能把导航或API外壳当成可用栏目': 'no_activity_links',
}


def column_link(link):
    # Short announcement titles and article footers are not source columns.
    if (ARTICLE_PATH.search(urlsplit(link['url']).path) or
            re.search(r'20\d{2}|关于|举办|开展|报名通知|招生简章|本科生?(?:招生|培养|教育)|博士招生|境外|留学', link['title']) or
            re.search(r'/(?:bkszs|bkzs|bkspy|undergraduate|undergrad)(?:/|\.)', urlsplit(link['url']).path, re.I)):
        return False
    return bool(COLUMN.search(link['title']) or link['title'] in ('通知公告', '学院公告', '招生公告', '公告通知', '新闻公告', '新闻动态'))


def boundary(url):
    value = institution(url)
    host = urlsplit(url).hostname.lower()
    # Distinct CAS institutes are not an interchangeable institutional trust boundary.
    return '.'.join(host.split('.')[-3:]) if value == 'cas.cn' else value


def canonical(url, parent=None):
    parsed = urlsplit(urljoin(parent or '', url))
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 80, 443) or '\\' in url or len(url) > 1500):
        raise ValueError('来源地址须为无凭据、标准端口的官方HTTP(S)链接')
    path = posixpath.normpath(parsed.path or '/')
    if parsed.path.endswith('/') and path != '/':
        path += '/'
    result = urlunsplit((parsed.scheme, parsed.netloc.lower(), path, parsed.query, ''))
    if parent and boundary(result) != boundary(parent):
        raise ValueError('发现链接跨机构，须另行人工核对来源')
    boundary(result)
    if re.search(r'\.(?:pdf|docx?|xlsx?|zip|jpg|png|gif|mp4)(?:$|[?])', result, re.I):
        raise ValueError('非HTML来源需要专用解析，不作为新栏目接入')
    return result


def fetch_html(url, parent_url=None, *, before_request=None, accepted_types=('text/html', 'application/xhtml+xml')):
    initial = canonical(url, parent_url)
    current = initial
    with requests.Session() as session:
        session.trust_env = False
        for _ in range(4):
            parsed = urlsplit(current)
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError('来源解析到非公网地址，拒绝抓取')
            if before_request:
                before_request()
            with session.get(current, timeout=(6, 12), stream=True, allow_redirects=False,
                             headers={'User-Agent': 'Mozilla/5.0 (official admissions source discovery)'}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    current = canonical(response.headers.get('Location', ''), current)
                    if boundary(current) != boundary(initial):
                        raise ValueError('来源跨机构跳转，未抓取目标')
                    if urlsplit(initial).scheme == 'https' and urlsplit(current).scheme != 'https':
                        raise ValueError('官方HTTPS来源降级为HTTP，未抓取目标')
                    continue
                response.raise_for_status()
                if response.status_code != 200 or response.headers.get('Content-Type', '').split(';',1)[0].strip().lower() not in accepted_types:
                    raise ValueError('来源未返回可核对的HTML栏目')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError('来源超过2MB检查上限')
                    chunks.append(chunk)
                return b''.join(chunks)
        raise ValueError('来源跳转次数过多')


def links(raw, url):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError('来源正文无效或超出大小上限')
    soup = BeautifulSoup(raw, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    if re.search(r'访问验证|安全验证|验证码|Access Denied|Just a moment|403 Forbidden|404 Not Found', title, re.I):
        raise ValueError('返回的是访问验证页，不是官方栏目')
    result = {}
    for anchor in soup.select('a[href]')[:1500]:
        label = ' '.join(anchor.get_text(' ', strip=True).split())
        if (not label or len(label) > 240 or EXCLUDED.search(label + ' ' + anchor['href'])
                or re.search(r'/(?:bkzs|undergraduate|undergrad)/', anchor['href'], re.I)):
            continue
        try:
            target = canonical(anchor['href'], url)
        except ValueError:
            continue
        if target != canonical(url):
            result.setdefault(target, dict(url=target, title=label))
    return list(result.values())


def inspect(raw, url):
    soup = BeautifulSoup(raw, 'html.parser')
    if ARTICLE_PATH.search(urlsplit(url).path) or soup.select_one(ARTICLE_BODY):
        raise ValueError('这是单条公告正文，不能用正文或页脚链接充当持续更新栏目')
    rows = links(raw, url)
    activities = [r for r in rows if activity_title(r['title']) and len(r['title']) >= 8 and
                  not column_link(r) and (ARTICLE_PATH.search(urlsplit(r['url']).path) or
                  re.search(r'20\d{2}|报名|招募|招收|接收|申请|通知', r['title']))]
    if not activities:
        raise ValueError('未解析到独立活动公告链接；不能把导航或API外壳当成可用栏目')
    canonical_rows = sorted((r['url'], r['title']) for r in rows)
    return dict(parsed_count=len(rows), activity_count=len(activities), evidence=activities[:10],
                source_sha256=hashlib.sha256(raw).hexdigest(),
                content_sha256=hashlib.sha256(json.dumps(canonical_rows, ensure_ascii=False).encode()).hexdigest())


def read(root):
    path = Path(root) / 'cache/source-discovery.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(version=1, candidates=[], seeds={})


def seeds(root, configs):
    result = {c['url']: dict(c) for c in configs if c.get('url')}
    root = Path(root)
    entries, admissions = root / 'data/admissions_entries.yaml', root / 'data/admissions.yaml'
    if entries.exists() and admissions.exists():
        sources = yaml.safe_load(admissions.read_text(encoding='utf-8')).get('sources', {})
        for entry in yaml.safe_load(entries.read_text(encoding='utf-8')).get('entries', []):
            source = sources.get(entry.get('source_id'), {})
            if source.get('url') and source.get('format') == 'html':
                result.setdefault(source['url'], dict(url=source['url'], school=entry['school'], dept=entry.get('dept', ''),
                                                       name=source.get('label') or entry.get('note') or entry['school']))
    # Department homepages are already maintained identities, independent of policy completeness.
    for path in sorted((root / 'sites').glob('*/*.yaml')):
        unit = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        if not unit.get('base_url') or not unit.get('school') or not unit.get('dept'):
            continue
        try:
            parsed = urlsplit(canonical(unit['base_url']))
            # Prefer a TLS-verified view of the same registered host; failure is retained, never downgraded.
            url = urlunsplit(('https', parsed.netloc, parsed.path, parsed.query, ''))
        except ValueError:
            continue
        result.setdefault(url, dict(url=url, school=unit['school'], dept=unit['dept'],
            name=unit.get('dept_name') or unit['dept'], seed_kind='registered_department',
            declared_url=unit['base_url']))
    return list(result.values())


def run(root, *, configs=None, fetcher=None, now=None, max_seeds=6, max_candidates=12, refresh=False, auto_admit=False):
    root = Path(root); now = now or datetime.now(timezone.utc)
    if not 1 <= max_seeds <= 12 or not 1 <= max_candidates <= 24:
        raise ValueError('每轮最多12个入口、24个新栏目')
    configs = configs if configs is not None else yaml.safe_load((root / 'sites/opportunities.yaml').read_text(encoding='utf-8'))['targets']
    fetcher = fetcher or fetch_html
    path = root / 'cache/source-discovery.json'
    with output_lock(path):
        data = read(root); states = data.setdefault('seeds', {})
        known = {c['url'] for c in configs}; candidates = {c['id']: c for c in data['candidates']}
        # Legacy content findings are not broken URLs. Preserve discovery time
        # and retry them weekly, or sooner when their trusted parent changes.
        for candidate in candidates.values():
            code = CONTENT_REASONS.get(candidate.get('reason'))
            if candidate.get('status') == 'error' and code:
                candidate.update(status='not_column', reason_code=code, error_kind='content')
                checked = datetime.fromisoformat(candidate['checked_at'])
                candidate['next_check_at'] = (checked + timedelta(days=7)).isoformat()
        pool = seeds(root, configs)
        pool.sort(key=lambda c: (states.get(c['url'], {}).get('checked_at', ''), c['url']))
        due_pool = [seed for seed in pool if refresh or states.get(seed['url'], {}).get('next_check_at', '') <= now.isoformat()]
        per_seed = max(1, max_candidates // max(1, min(max_seeds, len(due_pool))))
        attempted, inspected, added = 0, 0, 0
        for seed in due_pool:
            prior = states.get(seed['url'], {})
            if attempted >= max_seeds or inspected >= max_candidates:
                break
            if not refresh and prior.get('next_check_at', '') > now.isoformat():
                continue
            attempted += 1
            state = dict(checked_at=now.isoformat(), next_check_at=(now + timedelta(hours=6)).isoformat(), status='ok')
            try:
                parent_url = canonical(seed['url'])
                raw = fetcher(parent_url, parent_url)
                parent_digest = hashlib.sha256(raw).hexdigest()
                proposed = [link for link in links(raw, parent_url) if link['url'] not in known and
                            column_link(link) and len(link['title']) <= 40]
                # Previously failing menu links must not monopolize the bounded scan.
                proposed.sort(key=lambda link: (hashlib.sha256(link['url'].encode()).hexdigest()[:20] in candidates,
                    candidates.get(hashlib.sha256(link['url'].encode()).hexdigest()[:20], {}).get('checked_at', ''),
                    0 if re.search(r'冬令营|夏令营|暑期学校|科研实践|科研实习', link['title']) else
                    1 if re.search(r'研究生|招生', link['title']) else
                    2 if re.search(r'人才培养|培养招生', link['title']) else 3, link['url']))
                seed_inspected = 0
                for link in proposed:
                    ident = hashlib.sha256(link['url'].encode()).hexdigest()[:20]
                    old = candidates.get(ident)
                    if old and old.get('status') in ('approved', 'rejected'):
                        continue
                    parent_changed = bool(old and old.get('status') == 'not_column' and old.get('parent_sha256') != parent_digest)
                    if old and not refresh and not parent_changed and old.get('next_check_at', '') > now.isoformat():
                        continue
                    if inspected >= max_candidates or seed_inspected >= per_seed:
                        state['next_check_at'] = now.isoformat()
                        break
                    inspected += 1
                    seed_inspected += 1
                    candidate = dict(old or {}, id=ident, url=link['url'], label=link['title'], kind='column',
                        school=seed.get('school', ''), dept='', unit=link['title'],
                        parent_url=parent_url, parent_label=seed.get('name', ''), parent_sha256=parent_digest,
                        first_seen=(old or {}).get('first_seen', now.isoformat()), checked_at=now.isoformat(),
                        next_check_at=(now + timedelta(hours=6)).isoformat())
                    try:
                        candidate.update(inspect(fetcher(link['url'], parent_url), link['url']), status='candidate',
                            reason_code='activity_links_confirmed', error_kind=None,
                            reason='同机构HTML栏目已解析活动链接；等待接入规则复核，不代表活动已核验')
                    except (requests.RequestException, OSError, ValueError) as error:
                        code = CONTENT_REASONS.get(str(error))
                        candidate.update(status='not_column' if code else 'error', reason=str(error)[:400],
                            reason_code=code or 'source_unavailable', error_kind='content' if code else 'transport')
                        if code:
                            candidate['next_check_at'] = (now + timedelta(days=7)).isoformat()
                    candidates[ident] = candidate; added += int(old is None)
            except (requests.RequestException, OSError, ValueError) as error:
                state.update(status='error', error=str(error)[:400])
            states[seed['url']] = state
        data.update(candidates=list(candidates.values()), checked_at=now.isoformat(),
                    summary=dict(seed_count=len(pool), seeds_attempted=attempted, candidates_checked=inspected,
                                 new_candidates=added, due_seeds_deferred=max(0, len(due_pool) - attempted),
                                 candidates_per_seed=per_seed,
                                 content_wait=sum(c['status'] == 'not_column' for c in candidates.values()),
                                 source_errors=sum(c['status'] == 'error' for c in candidates.values()),
                                 pending=sum(c['status'] == 'candidate' for c in candidates.values())))
        data['next_check_at'] = min((states.get(c['url'], {}).get('next_check_at', now.isoformat()) for c in pool), default=(now + timedelta(hours=6)).isoformat())
        data['status'] = 'partial' if any(s.get('status') == 'error' for s in states.values()) else 'ok'
        atomic_json(path, data)
    if auto_admit:
        admit_verified(root, max_candidates=min(max_candidates, 8), fetcher=fetcher, now=now)
        data = read(root)
    return data


def automatic_reason(root, candidate, configs):
    """An automatic source changes monitoring only, with an existing institutional trust chain."""
    if not column_link(dict(url=candidate['url'], title=candidate['label'])):
        return '不是明确的研究生或活动栏目；公告、个人招募及本科招生不自动接入'
    if re.search(r'港澳台|同等学力|非全日制|留学|专业目录|招生目录|报名系统|博士|奖学金', candidate['label']):
        return '这是特定学位、地区或目录服务，不能自动作为本科生院校活动来源'
    if any(urlsplit(candidate[key]).scheme != 'https' for key in ('url', 'parent_url')):
        return '自动接入只接受经TLS校验的官方HTTPS入口和栏目'
    parent = next((c for c in seeds(root, configs) if c['url'] == candidate['parent_url']), None)
    if not parent or not parent.get('school') or parent.get('school') != candidate.get('school'):
        return '父入口或学校身份不在当前可信登记中'
    if parent.get('mode') == 'direct_page' or parent.get('content_scope_hint') == 'mentor_recruitment':
        return '个人招募或单条公告不能扩展为机构栏目'
    if int(parent.get('discovery_depth', bool(parent.get('discovery_parent')))) >= 2:
        return '自动发现已到两层上限，需维护者确认后扩展'
    if not candidate.get('activity_count') or not candidate.get('content_sha256'):
        return '尚无可重复解析的独立活动公告'
    return ''


def admit_verified(root, *, max_candidates=4, fetcher=None, now=None):
    """Recheck the parent and column before bounded, idempotent monitoring admission."""
    if not 1 <= max_candidates <= 8:
        raise ValueError('每轮最多自动接入8个栏目')
    root = Path(root); now = now or datetime.now(timezone.utc)
    path = root / 'cache/source-discovery.json'
    config_path = root / 'sites/opportunities.yaml'
    configs = yaml.safe_load(config_path.read_text(encoding='utf-8'))['targets']
    candidates = sorted(read(root)['candidates'], key=lambda c: (c.get('automatic_admission', {}).get('checked_at', ''), c['id']))
    attempts, approved = 0, 0
    for candidate in candidates:
        if candidate.get('status') != 'candidate':
            continue
        prior = candidate.get('automatic_admission', {})
        if prior.get('next_check_at', '') > now.isoformat():
            continue
        reason = automatic_reason(root, candidate, configs)
        result = dict(checked_at=now.isoformat(), next_check_at=(now + timedelta(hours=6)).isoformat())
        if reason:
            result.update(state='manual_required', reason=reason)
        else:
            if attempts >= max_candidates:
                break
            attempts += 1
            try:
                decide(root, candidate['id'], 'approve', expected_sha256=candidate['source_sha256'],
                       fetcher=fetcher, now=now, automatic=True)
                approved += 1
                result.update(state='approved', reason='可信官方入口和栏目两次核对一致；仅接入监测，公告仍独立核验')
            except (requests.RequestException, OSError, ValueError, RuntimeError) as error:
                result.update(state='retry_pending', reason=str(error)[:400])
        with output_lock(path):
            data = read(root)
            current = next(c for c in data['candidates'] if c['id'] == candidate['id'])
            current['automatic_admission'] = result
            atomic_json(path, data)
    with output_lock(path):
        data = read(root)
        data['automatic_admission'] = dict(checked_at=now.isoformat(), attempted=attempts, approved=approved,
            pending=sum(c.get('automatic_admission', {}).get('state') == 'retry_pending' for c in data['candidates']),
            manual_required=sum(c.get('automatic_admission', {}).get('state') == 'manual_required' for c in data['candidates']))
        atomic_json(path, data)
    return data['automatic_admission']


def decide(root, candidate_id, action, *, expected_sha256=None, fetcher=None, now=None, automatic=False):
    if action not in ('approve', 'reject'):
        raise ValueError('请选择核准或拒绝来源')
    root = Path(root); now = now or datetime.now(timezone.utc); fetcher = fetcher or fetch_html
    path, config_path = root / 'cache/source-discovery.json', root / 'sites/opportunities.yaml'
    with output_lock(path), output_lock(config_path):
        data = read(root)
        candidate = next((c for c in data['candidates'] if c['id'] == candidate_id), None)
        if candidate is None:
            raise ValueError('来源候选不存在，请刷新')
        if action == 'reject':
            if candidate.get('status') == 'approved':
                raise ValueError('来源已接入，拒绝候选不能撤销监测配置')
            candidate.update(status='rejected', decided_at=now.isoformat(), reason='维护者明确拒绝接入')
            data.setdefault('summary', {})['pending'] = sum(c['status'] == 'candidate' for c in data['candidates'])
            atomic_json(path, data)
            return candidate
        if candidate.get('status') not in ('candidate', 'approved') or not expected_sha256 or candidate.get('source_sha256') != expected_sha256:
            raise ValueError('来源版本已变化或未完成验证，请刷新后核准')
        canonical(candidate['url'], candidate['parent_url'])
        parent_links = links(fetcher(candidate['parent_url'], candidate['parent_url']), candidate['parent_url'])
        if not any(link['url'] == candidate['url'] and link['title'] == candidate['label'] for link in parent_links):
            raise ValueError('父来源当前未链接同名栏目，请重新发现并核验')
        current = inspect(fetcher(candidate['url'], candidate['parent_url']), candidate['url'])
        if current['content_sha256'] != candidate.get('content_sha256'):
            raise ValueError('来源链接/内容在核准前变化，请重新发现并核验')
        original = config_path.read_bytes(); config = yaml.safe_load(original)
        # The parent must still belong to the maintained official seed registry.
        if candidate['parent_url'] not in {c['url'] for c in seeds(root, config['targets'])}:
            raise ValueError('父来源已不在可信入口中，未接入')
        if automatic:
            reason = automatic_reason(root, candidate, config['targets'])
            if reason:
                raise ValueError(reason)
        if candidate['url'] not in {c['url'] for c in config['targets']}:
            parent = next(c for c in seeds(root, config['targets']) if c['url'] == candidate['parent_url'])
            config['targets'].append(dict(source_id='discovered-' + candidate_id, school=candidate['school'], dept=candidate['dept'],
                name=candidate['label'], url=candidate['url'], selector='a[href]', title_selector='self',
                priority='normal', interval_hours=6, discovery_parent=candidate['parent_url'],
                discovery_depth=int(parent.get('discovery_depth', bool(parent.get('discovery_parent')))) + 1,
                source_note='可信入口与栏目当前链接复核一致；只用于发现线索，活动须独立核验发布。'))
            backup = root / 'cache/source-discovery-backups' / (hashlib.sha256(original).hexdigest() + '.yaml')
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                backup.write_bytes(original)
            fd, temporary = tempfile.mkstemp(prefix='.sources-', suffix='.yaml', dir=config_path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    yaml.safe_dump(config, output, allow_unicode=True, sort_keys=False)
                os.replace(temporary, config_path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        candidate.update(current, status='approved', decided_at=now.isoformat(),
            reason='规则核准，同机构栏目已接入；公告仍须独立核验发布' if automatic else '维护者核准，同机构栏目已接入；公告仍须独立核验发布')
        data.setdefault('summary', {})['pending'] = sum(c['status'] == 'candidate' for c in data['candidates'])
        atomic_json(path, data)
        return candidate

"""Classify mentor failures and discover bounded, identity-bound official replacements."""
import hashlib
import json
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from crawler.email_util import normalize_email

VERSION = 'official-directory-recovery-v2'
RULES = {
    'http_not_found': ('官方链接已失效', 'discover_official_source', '发现替代官方来源', 168),
    'http_forbidden': ('来源限制访问', 'discover_official_source', '检查官方替代入口', 168),
    'http_unexpected_status': ('来源未返回正文', 'discover_official_source', '核验返回状态并寻找官方正文入口', 168),
    'rate_limited': ('来源请求受限', 'retry', '退避后重试', 24),
    'network_timeout': ('网络暂时失败', 'retry', '退避后重试', 2),
    'server_error': ('官方服务暂时异常', 'retry', '退避后重试', 2),
    'tls_error': ('官方证书异常', 'discover_official_source', '核验其他官方入口', 168),
    'template_empty': ('个人信息未能解析', 'discover_official_source', '查找个人页或可读官方名册', 168),
    'directory_only': ('只有名册登记', 'discover_official_source', '核验名册并寻找个人页', 168),
    'parser_unsupported': ('解析器待适配', 'adapt_parser', '适配官方页面结构', 168),
    'identity_conflict': ('身份或职称需核对', 'manual_review', '保留冲突并等待官方依据', 168),
    'shared_contact': ('联系人归属不明', 'manual_review', '核对本人独立联系方式', 168),
    'roster_incomplete': ('名册数量不一致', 'manual_review', '核对完整官方名册', 168),
    'other': ('来源异常待定位', 'manual_review', '检查原文与处理记录', 24),
    'resolved': ('官方证据已恢复', 'none', '按周期复检', 168),
}


def signature(root, cfg):
    content = json.dumps([VERSION,cfg],sort_keys=True,ensure_ascii=False).encode()
    for folder in (root/'sites'/cfg['school'],root/'sites'):
        path=folder/(cfg.get('hook','')+'.py')
        if path.is_file():
            content += path.read_bytes();break
    return hashlib.sha256(content).hexdigest()


def classify(message='', kind='', *, original=None, cfg=None):
    # URL article identifiers can contain these digits; only status-shaped
    # tokens count as transport errors.
    status_text = re.sub(r'https?://\S+', '', message)
    has_status = lambda codes: bool(re.search(r'(?<![\w/])(?:' + codes + r')(?![\w/])', status_text))
    if kind == 'shared_public_contact':
        code = 'shared_contact'
    elif kind in ('unknown_detail_field', 'duplicate_public_registration') or re.search('姓名.*不符|身份.*匹配|同名.*候选|职称.*冲突|URL 为人工维护', message):
        code = 'identity_conflict'
    elif kind == 'roster_count_mismatch':
        code = 'roster_incomplete'
    elif has_status('404|410') or re.search(r'Not Found|\bGone\b', status_text, re.I):
        code = 'http_not_found'
    elif has_status('429') or re.search(r'Too Many', status_text, re.I):
        code = 'rate_limited'
    elif has_status('403|412') or re.search(r'Forbidden|Precondition', status_text, re.I):
        code = 'http_forbidden'
    elif has_status(r'5\d\d'):
        code = 'server_error'
    elif re.search(r'HTTP\s+\d{3}.*来源未返回可核对', status_text):
        code = 'http_unexpected_status'
    elif re.search(r'SSL|certificate|CERTIFICATE|证书', message):
        code = 'tls_error'
    elif re.search(r'timed? ?out|Timeout|Connection|连接|网络', message, re.I):
        code = 'network_timeout'
    elif re.search(r'parse_detail|解析器|No module named|没有可证明', message):
        code = 'parser_unsupported'
    elif original and cfg and (canonical(original['detail_url']) in seed_urls(cfg) or urlsplit(original['detail_url']).fragment):
        code = 'directory_only'
    elif re.search(r'未解析|空壳|姓名未出现|未识别|block not found', message, re.I):
        code = 'template_empty'
    else:
        code = 'other'
    label, action, action_label, hours = RULES[code]
    return dict(reason_code=code, category_label=label, next_action=action,
                action_label=action_label, retry_hours=hours)


def canonical(url):
    parts = urlsplit(url)
    return urlunsplit(('https' if parts.scheme == 'http' else parts.scheme,
                       parts.netloc.lower(), parts.path or '/', parts.query, ''))


def institution(host):
    host = (host or '').lower()
    if re.fullmatch(r'(?:[a-z0-9-]+\.)+(?:edu|ac|cas)\.cn', host):
        return '.'.join(host.split('.')[-3:])
    return None


def allowed(url, scope):
    try:
        value, parent = urlsplit(url), urlsplit(scope)
        return (value.scheme == 'https' and not value.username and not value.password and
                value.port in (None, 443) and institution(value.hostname) is not None and
                institution(value.hostname) == institution(parent.hostname))
    except ValueError:
        return False


def seed_urls(cfg):
    listing = cfg.get('list', {})
    seeds = list(cfg.get('profile_lookup_urls', []))
    if isinstance(listing, dict):
        seeds += [listing[k] for k in ('url',) if isinstance(listing.get(k), str)]
        seeds += listing.get('urls', []) + listing.get('faculty_channels', [])
        seeds += [x['url'] for x in listing.get('channels', []) if isinstance(x, dict) and x.get('url')]
    if cfg.get('base_url'):
        seeds.append(cfg['base_url'])
    return list(dict.fromkeys(canonical(s) for s in seeds if isinstance(s, str) and allowed(canonical(s), cfg.get('base_url') or s)))


def inline_rows(html):
    """Read literal JSON arrays; never execute source JavaScript."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'(?:var|let|const)\s+\w+\s*=\s*(\[\s*\{)', html):
        try:
            rows, _ = decoder.raw_decode(html[match.start(1):])
            if isinstance(rows, list) and len(rows) <= 2000 and all(isinstance(x, dict) for x in rows):
                yield from rows
        except (ValueError, TypeError):
            continue


def directory_fields(cfg, html, name):
    """A configured roster row is evidence only for that row, never a whole-page mailbox."""
    mode = cfg.get('profile_directory_format')
    matches = []
    if mode == 'vsb_json':
        for row in inline_rows(html):
            if (row.get('title') or row.get('showTitle')) != name or not isinstance(row.get('fields'), dict):
                continue
            fields = row['fields']; value = {'name': name}
            title = fields.get('zc', '')
            match = re.search(r'(?:特聘|长聘|准聘|预聘|助理|副)?(?:教授|研究员)|讲师|工程师', title)
            if match:value['title'] = match[0]
            qualifications = [label for token, label in [('博士生','博导'),('硕士生','硕导')] if token in title]
            if qualifications:value['supervisor'] = '、'.join(qualifications)
            if normalize_email(fields.get('yx')):value['email'] = normalize_email(fields['yx'])
            if fields.get('ggdd') or fields.get('bgdd'):value['office_address'] = fields.get('ggdd') or fields['bgdd']
            if fields.get('lxdh'):value['phone'] = fields['lxdh']
            abstract = BeautifulSoup(row.get('showAbstract', ''), 'html.parser').get_text(' ', strip=True)
            direction = re.search(r'研究方向(?:为|包括|[：:])?\s*(.+?)(?:。|办公|电子邮箱|$)', abstract)
            if direction and not direction[1].endswith(('...', '…')):value['research_direction_raw'] = direction[1]
            # A directory abstract may be truncated without an ellipsis. It does
            # not replace a previously collected complete biography.
            matches.append((value, row.get('url')))
    elif mode == 'faculty_table':
        columns = cfg.get('profile_table_columns', {})
        for tr in BeautifulSoup(html, 'html.parser').select('tr'):
            cells = tr.find_all('td', recursive=False)
            if not cells or not isinstance(columns.get('name'), int) or columns['name'] >= len(cells):continue
            if cells[columns['name']].get_text(strip=True) != name:continue
            value = {'name': name}
            for field, index in columns.items():
                if field == 'name' or not isinstance(index,int) or index >= len(cells):continue
                text = cells[index].get_text(' ', strip=True)
                if text:value[field] = text
            if value.get('email'):value['email'] = normalize_email(value['email'])
            anchor = cells[columns['name']].find('a', href=True)
            matches.append((value, anchor['href'] if anchor else None))
    unique = {json.dumps(value, sort_keys=True, ensure_ascii=False): (value, href) for value, href in matches}
    if len(unique) == 1:
        value, href = next(iter(unique.values()))
        value['_verified_roster_name'] = name
        return value, href
    return None, None


def identity(original, parsed, url):
    if parsed.get('name') != original['name']:
        return None
    old_email, new_email = normalize_email(original.get('email')), normalize_email(parsed.get('email'))
    if old_email and new_email and old_email.casefold() == new_email.casefold():
        return 'name_and_email'
    old, new = urlsplit(original['detail_url']), urlsplit(url)
    article = lambda path: re.search(r'/info/\d+/(\d+)\.htm$', path)
    a,b=article(old.path),article(new.path)
    if old.hostname == new.hostname and a and b and a[1] == b[1]:
        return 'same_official_article_id_and_name'
    if any(canonical(original.get(field, '')) == canonical(url) for field in ('homepage','profile_url') if original.get(field)):
        return 'registered_homepage_and_name'
    return None


def matches_name(label, name):
    label = re.sub(r'[（(][^）)]+[）)]','',label).strip()
    if label == name:
        return True
    suffix = label[len(name):].strip() if label.startswith(name) else ''
    return bool(suffix and re.fullmatch(r'(?:[、，, /]|副教授|教授|研究员|助理研究员|副研究员|讲师|博士生导师|硕士生导师|博导|硕导)+',suffix))


def named_link(html, directory_url, target, name):
    for anchor in BeautifulSoup(html,'html.parser').select('a[href]'):
        if matches_name(anchor.get_text(' ',strip=True),name) and canonical(urljoin(directory_url,anchor['href']))==canonical(target):
            return True
    return any((row.get('title') or row.get('showTitle'))==name and isinstance(row.get('url'),str) and
               canonical(urljoin(directory_url,row['url']))==canonical(target) for row in inline_rows(html))


def directory_index(root, cfg, sources, *, refresh=False):
    """Cache a bounded official directory walk once per unit, not once per teacher."""
    seeds = seed_urls(cfg)
    signature = hashlib.sha256(json.dumps([VERSION,cfg],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path = root / 'cache/mentor_quality/discovery' / (cfg['school']+'-'+cfg['dept']+'.json')
    previous = {}
    if path.exists() and not refresh:
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('signature') == signature and value.get('next_check_at','') > sources.stamp:
            sources.used.extend(e for e in value.get('evidence',[]) if e not in sources.used)
            return value
        if value.get('signature') == signature and value.get('frontier'):
            previous = value
    queue = previous.get('frontier') or [(s,0) for s in seeds]
    seen=set();visited=set(previous.get('visited',[]));links=previous.get('links',[])
    rosters=previous.get('rosters',[]);evidence=previous.get('evidence',[]);failures=[]
    while queue and len(seen)<16:
        url,depth=queue.pop(0)
        if url in seen or url in visited:continue
        seen.add(url);visited.add(url)
        try:
            raw,html=sources.read(url, official_scope=cfg.get('base_url') or url)
        except Exception as error:
            failures.append(dict(url=url,reason=str(error)[:300]));continue
        evidence.append(dict(url=url,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=sources.stamp))
        if cfg.get('profile_directory_format'):
            rosters.append(dict(url=url,sha256=hashlib.sha256(raw).hexdigest()))
        soup=BeautifulSoup(html,'html.parser')
        for a in soup.select('a[href]'):
            text=a.get_text(' ',strip=True);target=canonical(urljoin(url,a['href']))
            if not allowed(target,cfg.get('base_url') or url) or target==url:continue
            if 2 <= len(text) <= 60:
                links.append(dict(name=text,url=target,directory_url=url))
            paging=bool(re.fullmatch(r'\d+|下[一]?页|尾页|Next',text,re.I))
            faculty=bool(re.search(r'师资|教师名录|全体教师|教授|研究员|faculty|staff',text,re.I))
            if (paging or depth<2 and faculty) and target not in visited and len(queue)<200:
                queue.append((target,depth if paging else depth+1))
        for row in inline_rows(html):
            name,href=row.get('title') or row.get('showTitle'),row.get('url')
            if isinstance(name,str) and isinstance(href,str):
                target=canonical(urljoin(url,href))
                if allowed(target,cfg.get('base_url') or url):links.append(dict(name=name,url=target,directory_url=url))
    value=dict(version=1,signature=signature,checked_at=sources.stamp,
               next_check_at=(datetime.fromisoformat(sources.stamp)+timedelta(hours=24)).isoformat(timespec='seconds'),
               links=list({(v['name'],v['url']):v for v in links}.values()),rosters=rosters,evidence=evidence,failures=failures,
               pages_checked=len(seen),frontier=queue,visited=sorted(visited) if queue else [])
    from crawler.opportunity_monitor import atomic_json
    atomic_json(path,value)
    return value


def replacements(root, original, cfg, sources):
    index=directory_index(root,cfg,sources)
    candidates=[]
    for row in index['links']:
        if matches_name(row['name'],original['name']) and row['url']!=canonical(original['detail_url']):
            candidates.append(row)
    if len({r['url'] for r in candidates})>8:
        raise ValueError('同名官方候选过多，不能自动确认身份')
    return candidates,index

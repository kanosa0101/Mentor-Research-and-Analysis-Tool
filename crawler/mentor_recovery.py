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
    'identity_evidence_missing': ('身份依据尚不足', 'discover_official_source', '继续寻找可交叉核验的官方身份依据', 24),
    'identity_conflict': ('身份或职称需核对', 'manual_review', '保留冲突并等待官方依据', 168),
    'shared_contact': ('联系人归属不明', 'manual_review', '核对本人独立联系方式', 168),
    'roster_incomplete': ('名册数量不一致', 'manual_review', '核对完整官方名册', 168),
    'other': ('来源异常待定位', 'manual_review', '检查原文与处理记录', 24),
    'resolved': ('官方证据已恢复', 'none', '按周期复检', 168),
}


class DiscoveryBudgetExhausted(RuntimeError):
    pass


def signature(root, cfg):
    content = json.dumps([VERSION,cfg],sort_keys=True,ensure_ascii=False).encode()
    return hashlib.sha256(content+parser_source(root,cfg)).hexdigest()


def parser_source(root,cfg):
    content=b''
    for folder in (root/'sites'/cfg['school'],root/'sites'):
        path=folder/(cfg.get('hook','')+'.py')
        if path.is_file():
            content += path.read_bytes();break
    for name in cfg.get('parser_dependencies',[]):
        path=(root/'sites'/name).resolve()
        if path.is_relative_to((root/'sites').resolve()) and path.is_file():content+=path.read_bytes()
    return content


def classify(message='', kind='', *, original=None, cfg=None):
    # URL article identifiers can contain these digits; only status-shaped
    # tokens count as transport errors.
    status_text = re.sub(r'https?://\S+', '', message)
    has_status = lambda codes: bool(re.search(r'(?<![\w/])(?:' + codes + r')(?![\w/])', status_text))
    if kind == 'shared_public_contact':
        code = 'shared_contact'
    elif kind in ('unknown_detail_field', 'duplicate_public_registration'):
        code = 'identity_conflict'
    elif re.search('姓名.*不符|邮箱.*不一致|身份.*矛盾|职称.*冲突|URL 为人工维护', message):
        code = 'identity_conflict'
    elif re.search('未通过姓名与独立身份特征匹配|未通过姓名和邮箱双重身份匹配|同名官方候选过多|身份依据尚不足',message):
        code = 'identity_evidence_missing'
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


def directory_target(url,scope):
    """Decode one documented HIT gateway host, never guess a person's slug."""
    value=urlsplit(url)
    if (institution(urlsplit(scope).hostname)=='hit.edu.cn' and
            value.netloc=='homepage-hit-edu-cn.ivpn.hit.edu.cn:1080' and
            re.fullmatch(r'/[A-Za-z0-9_-]+',value.path) and not value.query):
        return 'https://homepage.hit.edu.cn'+value.path
    return canonical(url)


def content_types(url):
    value=urlsplit(url)
    if (value.scheme=='https' and value.netloc=='homepage.hit.edu.cn' and value.path=='/TeacherHome/teacherBody.do' and
            re.fullmatch(r'id=[a-f0-9]{32}&versionId=',value.query)):
        return ('text/json','application/json')
    return ('text/html','application/xhtml+xml')


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
    if (old.hostname in ('www.cs.hit.edu.cn','cs.hit.edu.cn') and old.path=='/jsml/list.htm' and
            new.hostname=='homepage.hit.edu.cn' and any(len(v)>=8 and v in parsed.get('_identity_bio','')
            for v in original.get('institutes',[]))):
        return 'official_named_link_and_same_research_centre'
    return None


def matches_name(label, name):
    label = re.sub(r'[（(][^）)]+[）)]','',label).strip()
    if label == name:
        return True
    suffix = label[len(name):].strip() if label.startswith(name) else ''
    return bool(suffix and re.fullmatch(r'(?:[、，, /]|副教授|教授|研究员|助理研究员|副研究员|讲师|博士生导师|硕士生导师|博导|硕导)+',suffix))


def named_link(html, directory_url, target, name):
    for anchor in BeautifulSoup(html,'html.parser').select('a[href]'):
        if matches_name(anchor.get_text(' ',strip=True),name) and directory_target(urljoin(directory_url,anchor['href']),directory_url)==canonical(target):
            return True
    return any((row.get('title') or row.get('showTitle'))==name and isinstance(row.get('url'),str) and
               canonical(urljoin(directory_url,row['url']))==canonical(target) for row in inline_rows(html))


def directory_index(root, cfg, sources, *, refresh=False, max_pages=16):
    """Cache a bounded official directory walk once per unit, not once per teacher."""
    seeds = seed_urls(cfg)
    signature = hashlib.sha256(json.dumps([VERSION,cfg],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    path = root / 'cache/mentor_quality/discovery' / (cfg['school']+'-'+cfg['dept']+'.json')
    previous = {}
    if path.exists():
        value = json.loads(path.read_text(encoding='utf-8'))
        if not refresh and value.get('signature') == signature and value.get('next_check_at','') > sources.stamp:
            sources.used.extend(e for e in value.get('evidence',[]) if e not in sources.used)
            return value
        if value.get('signature') == signature and value.get('frontier'):
            previous = value
    queue = previous.get('frontier') or [(s,0) for s in seeds]
    seen=set();visited=set(previous.get('visited',[]));links=previous.get('links',[])
    rosters=previous.get('rosters',[]);evidence=previous.get('evidence',[]);failures=[]
    while queue and len(seen)<max_pages:
        url,depth=queue.pop(0)
        if url in seen or url in visited:continue
        seen.add(url);visited.add(url)
        try:
            raw,html=sources.read(url, official_scope=cfg.get('base_url') or url)
        except DiscoveryBudgetExhausted:
            queue.insert(0,(url,depth));seen.remove(url);visited.remove(url)
            break
        except Exception as error:
            failures.append(dict(url=url,reason=str(error)[:300]));continue
        evidence.append(dict(url=url,sha256=hashlib.sha256(raw).hexdigest(),fetched_at=sources.stamp))
        if cfg.get('profile_directory_format'):
            rosters.append(dict(url=url,sha256=hashlib.sha256(raw).hexdigest()))
        soup=BeautifulSoup(html,'html.parser')
        for a in soup.select('a[href]'):
            text=a.get_text(' ',strip=True);target=directory_target(urljoin(url,a['href']),cfg.get('base_url') or url)
            if not allowed(target,cfg.get('base_url') or url) or target==url:continue
            if 2 <= len(text) <= 60:
                links.append(dict(name=text,url=target,directory_url=url))
            paging=bool(re.fullmatch(r'\d+|下[一]?页|尾页|Next',text,re.I))
            faculty=bool(len(text)<=24 and re.search(r'师资|教师名录|全体教师|教授|研究员|faculty|staff',text,re.I) and
                         not re.search(r'新闻|讲座|获奖|获批|报告|20\d{2}|/info/\d+/\d+\.htm',text+' '+target))
            if (paging or depth<2 and faculty) and target not in visited and len(queue)<200:
                queue.append((target,depth if paging else depth+1))
        for row in inline_rows(html):
            name,href=row.get('title') or row.get('showTitle'),row.get('url')
            if isinstance(name,str) and isinstance(href,str):
                target=canonical(urljoin(url,href))
                if allowed(target,cfg.get('base_url') or url):links.append(dict(name=name,url=target,directory_url=url))
    value=dict(version=1,signature=signature,checked_at=sources.stamp,
               next_check_at=(datetime.fromisoformat(sources.stamp)+timedelta(hours=1 if queue else 24)).isoformat(timespec='seconds'),
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


def collect_roster_candidates(root,cfg,index,sources):
    """Record strict official-directory differences for later identity review."""
    if not cfg.get('roster_discovery') or not cfg.get('list',{}).get('person_href'):
        return dict(candidates=0)
    from crawler import mentor_quality as quality
    from crawler.opportunity_monitor import atomic_json,output_lock
    path=root/'cache/mentor_quality/roster-candidates.json'
    folder=root/'data/professors'/cfg['school']/cfg['dept']
    people=[quality.load_yaml(p) for p in folder.glob('*.yaml')]
    known_urls={canonical(p['detail_url']) for p in people}
    rows=[row for row in index['links'] if re.fullmatch(r'[\u4e00-\u9fff·]{2,8}',row['name']) and
          re.search(cfg['list']['person_href'],row['url']) and row['url'] not in known_urls]
    with output_lock(path):
        state=json.loads(path.read_text(encoding='utf8')) if path.exists() else {'version':1,'records':{}}
        for row in rows:
            key=cfg['school']+'/'+cfg['dept']+'/'+hashlib.sha256(row['url'].encode()).hexdigest()[:16]
            if key in state['records']:continue
            conflict=any(p['name']==row['name'] for p in people) or len({r['url'] for r in rows if r['name']==row['name']})>1
            state['records'][key]=dict(id=key,unit=cfg['school']+'/'+cfg['dept'],name=row['name'],url=row['url'],
                directory_url=row['directory_url'],discovered_at=sources.stamp,status='identity_conflict' if conflict else 'pending',
                reason='存在同名登记，需核对替代来源；不按姓名合并' if conflict else '新官方目录登记，待核验本人身份与联系方式',
                evidence=index.get('evidence',[]))
        atomic_json(path,state)
    return dict(candidates=len(rows))


def refresh_directories(root, *, max_units=2, request_budget=16, fetcher=None, now=None):
    """Advance directory cursors independently of a broken profile's weekly cooldown.

    New links alone do not wake issues: the existing full identity/provenance gate
    must also validate a current profile, within the same transport budget.
    """
    from pathlib import Path
    from datetime import timezone
    from crawler import mentor_quality
    from crawler.opportunity_monitor import atomic_json, output_lock
    from crawler.source_discovery import fetch_html
    root=Path(root);now=now or datetime.now(timezone.utc);stamp=now.isoformat(timespec='seconds')
    state_path=root/'cache/mentor_quality/state.json'
    records=json.loads(state_path.read_text(encoding='utf-8')).get('records',{}) if state_path.exists() else {}
    candidates=[]
    for cfg_path in sorted((root/'sites').glob('*/*.yaml')):
        cfg=mentor_quality.load_yaml(cfg_path);unit=cfg['school']+'/'+cfg['dept']
        if not any((root/'data/professors'/unit).glob('*.yaml')):continue
        path=root/'cache/mentor_quality/discovery'/(unit.replace('/','-')+'.json')
        old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        due=old.get('next_check_at','')
        if old.get('frontier') and old.get('checked_at'):
            due=min(due or stamp,(datetime.fromisoformat(old['checked_at'])+timedelta(hours=1)).isoformat(timespec='seconds'))
        if due and due>stamp:continue
        candidates.append((0 if old.get('frontier') else 1,old.get('checked_at',''),unit,cfg,old))
    candidates.sort(key=lambda row:row[:3])
    used=0;results=[];wake=[]
    def before_request():
        nonlocal used
        if used>=request_budget:raise DiscoveryBudgetExhausted('本轮官方目录请求预算已用完，保留游标')
        used+=1
    for _,_,unit,cfg,old in candidates[:max_units]:
        if used>=request_budget:break
        def bounded(source):
            url=canonical(source['url']);scope=cfg.get('base_url') or url
            if not allowed(url,scope):raise ValueError('目录补充来源离开登记官方机构边界')
            if fetcher:
                before_request();return fetcher(dict(source,url=url,official_scope=scope))
            return fetch_html(url,scope,before_request=before_request,accepted_types=content_types(url))
        sources=mentor_quality.Sources(root,bounded,stamp)
        try:
            index=directory_index(root,cfg,sources,refresh=True,max_pages=max(1,request_budget//max(1,max_units)//2))
            previous={(row['name'],row['url']) for row in old.get('links',[])}
            added=[row for row in index['links'] if (row['name'],row['url']) not in previous]
            woke=[]
            for key,record in records.items():
                # Older releases labelled insufficient evidence as a hard conflict.
                # Reclassify the diagnostic before filtering; genuine conflicts stay blocked.
                current_reason=classify(record.get('reason',''),record.get('kind'))
                action=current_reason['next_action'] if current_reason['reason_code']=='identity_evidence_missing' else record.get('next_action')
                if (not key.startswith(unit+'/') or record.get('status') not in ('error','pending') or
                        action not in ('discover_official_source','retry') or used>=request_budget):continue
                path=root/'data/professors'/unit/(record['ref']+'.yaml')
                if path.parent!=root/'data/professors'/unit or not path.is_file():continue
                original=mentor_quality.load_yaml(path)
                new_urls={row['url'] for row in added if matches_name(row['name'],original['name'])}
                if not new_urls:continue
                sources.replacement=None
                try:
                    mentor_quality.profile(root,original,cfg,sources,failure_reason=record.get('reason',''))
                except Exception:
                    continue
                replacement=sources.replacement
                if replacement and replacement['new_url'] in new_urls:
                    wake.append((key,original,path,replacement,list(sources.used)))
                    woke.append(key)
            roster=collect_roster_candidates(root,cfg,index,sources)
            results.append(dict(unit=unit,pages_checked=index['pages_checked'],frontier=len(index['frontier']),roster=roster,
                                new_links=len(added),verified_candidates=len(woke),source_errors=len(index['failures'])))
        except Exception as error:
            results.append(dict(unit=unit,error=str(error)[:400]))
    requeued=[]
    if wake:
        with output_lock(state_path):
            state=json.loads(state_path.read_text(encoding='utf-8'))
            for key,original,path,replacement,evidence in wake:
                row=state['records'].get(key,{})
                current_reason=classify(row.get('reason',''),row.get('kind'))
                action=current_reason['next_action'] if current_reason['reason_code']=='identity_evidence_missing' else row.get('next_action')
                if (row.get('status') not in ('error','pending') or action not in ('discover_official_source','retry') or
                        mentor_quality.load_yaml(path)!=original):continue
                if current_reason['reason_code']=='identity_evidence_missing':row.update({k:v for k,v in current_reason.items() if k!='retry_hours'})
                row.update(next_check_at=stamp,discovery_verified_at=stamp,discovered_replacement=replacement,
                           discovery_evidence=evidence)
                requeued.append(key)
            atomic_json(state_path,state)
    report=dict(checked_at=stamp,attempted=len(results),requests=used,request_budget=request_budget,
                requeued=len(requeued),requeued_ids=requeued,error=sum('error' in row for row in results),results=results)
    atomic_json(root/'cache/mentor_quality/directory-refresh.json',report)
    return report

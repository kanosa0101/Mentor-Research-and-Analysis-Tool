"""公开招生政策摘要校验；来源检查不会修改人工核对记录。"""
import hashlib
import json
import re
from datetime import date, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from crawler import fetch

FIELDS = {'eligibility': '报名资格', 'materials': '所需材料', 'exams': '考核与科目',
          'timeline': '时间安排', 'tuition': '学费与学制', 'funding': '奖助政策',
          'quota': '招生计划', 'contact': '咨询与报名入口'}


def valid_date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value or value > date.today().isoformat():
        raise ValueError('日期格式错误或在未来')


def validate(data, units):
    if not isinstance(data, dict) or set(data) != {'version', 'sources', 'policies'} or type(data['version']) is not int or data['version'] != 1 or not isinstance(data['sources'], dict) or not isinstance(data['policies'], list):
        raise ValueError('招生政策结构错误')
    for sid, source in data['sources'].items():
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z0-9_-]+', sid) or not isinstance(source, dict) or not {'url', 'format', 'selector'} <= set(source) or set(source) - {'url', 'format', 'selector', 'label', 'api'}:
            raise ValueError('来源结构错误')
        if 'label' in source and (not isinstance(source['label'], str) or not source['label'].strip()):
            raise ValueError('来源名称须为非空字符串')
        if not isinstance(source['url'], str):
            raise ValueError('来源 URL 须为字符串')
        link = urlsplit(source['url'])
        if link.scheme not in ('http', 'https') or not link.hostname or link.username or link.password or source['format'] not in ('html', 'pdf', 'json') or not isinstance(source['selector'], str) or (source['format'] == 'html' and not source['selector']):
            raise ValueError('须登记 HTTP(S) 原文和正文选择器')
        if source['format'] == 'json':
            if not isinstance(source.get('api'), str) or not source['api'] or not source['selector'].startswith('/') or re.search(r'~(?:[^01]|$)', source['selector']):
                raise ValueError('JSON 来源须登记同源 API 和有效非空 JSON Pointer')
            api = urlsplit(source['api'])
            origin = lambda url: (url.scheme, url.hostname, url.port or (443 if url.scheme == 'https' else 80))
            if api.scheme not in ('http', 'https') or not api.hostname or api.username or api.password or origin(api) != origin(link):
                raise ValueError('JSON API 须与可阅读原文同源且不含凭据')
        elif 'api' in source:
            raise ValueError('只有 JSON 来源可登记 API')
    ids = set()
    keys = {'id', 'school', 'dept', 'level', 'title', 'year', 'degree', 'route', 'program', 'program_code', 'published_at', 'reviewed_at', 'review_hashes', 'source_id', 'fields'}
    for p in data['policies']:
        if not isinstance(p, dict) or not keys <= set(p) or set(p) - keys - {'track', 'events', 'applies_if'}:
            raise ValueError('政策结构错误')
        if not isinstance(p['id'], str) or not re.fullmatch(r'[a-z0-9_-]+', p['id']) or p['id'] in ids:
            raise ValueError('政策 ID 错误或重复')
        ids.add(p['id'])
        if p.get('track', 'ordinary') not in ('ordinary', 'special', 'general'):
            raise ValueError('须区分普通/专项/通用范围')
        if not isinstance(p.get('events', []), list):
            raise ValueError('时间事件结构错误')
        for event in p.get('events', []):
            if not isinstance(event, dict) or not {'label', 'kind', 'at', 'quote', 'locator'} <= set(event) or set(event) - {'label', 'kind', 'at', 'quote', 'locator', 'source_ids'} or any(not isinstance(event[k], str) or not event[k].strip() for k in ('label', 'kind', 'at', 'quote', 'locator')) or event['kind'] not in ('deadline', 'exam', 'qualification'):
                raise ValueError('时间事件须有明确类型与原文定位')
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', event['at']):
                date.fromisoformat(event['at'])
            else:
                timestamp = datetime.fromisoformat(event['at'])
                if timestamp.tzinfo is None:
                    raise ValueError('精确时间事件须明确时区；仅日期不补时刻')
        if any(not isinstance(p[k], str) for k in ('school', 'dept', 'level', 'degree', 'route', 'source_id')):
            raise ValueError('政策范围须为字符串')
        if p['school'] not in units or (p['dept'] and p['dept'] not in units[p['school']]) or p['level'] not in ('school', 'dept', 'program') or (p['level'] == 'school' and p['dept']) or (p['level'] != 'school' and not p['dept']) or (p['level'] == 'program' and not p['program']):
            raise ValueError('学校/院系/专业范围错误')
        if type(p['year']) is not int or not 2000 <= p['year'] <= 2100 or p['degree'] not in ('master', 'phd') or p['route'] not in ('recommend', 'exam', 'assessment'):
            raise ValueError('须明确年度、学位和渠道')
        for key in ('title', 'program', 'program_code'):
            if not isinstance(p[key], str) or (key == 'title' and not p[key].strip()):
                raise ValueError('标题/专业错误')
        valid_date(p['reviewed_at'])
        if p['published_at'] is not None:
            valid_date(p['published_at'])
            if p['published_at'] > p['reviewed_at']:
                raise ValueError('核对日期早于发布时间')
        hashes = p['review_hashes']
        if not isinstance(hashes, dict) or p['source_id'] not in hashes or not hashes or any(s not in data['sources'] or not isinstance(h, str) or not re.fullmatch(r'[a-f0-9]{64}', h) for s, h in hashes.items()):
            raise ValueError('原文及落地页核对指纹错误')
        if not isinstance(p['fields'], dict) or not p['fields'] or set(p['fields']) - set(FIELDS):
            raise ValueError('政策字段错误')
        evidence = list(p['fields'].values()) + ([p['applies_if']] if 'applies_if' in p else [])
        for field in evidence:
            if not isinstance(field, dict) or not {'text', 'quote', 'locator'} <= set(field) or set(field) - {'text', 'quote', 'locator', 'source_ids'} or any(not isinstance(field[k], str) or not field[k].strip() for k in ('text', 'quote', 'locator')):
                raise ValueError('每项摘要须有原文片段与定位')
        for part in evidence + p.get('events', []):
            refs = part.get('source_ids', [p['source_id']])
            if not isinstance(refs, list) or not refs or any(not isinstance(s, str) or s not in hashes or s not in data['sources'] for s in refs) or len(refs) != len(set(refs)):
                raise ValueError('字段/事件来源须为已登记且本政策已核对的非空唯一来源数组')


def validate_checks(checks, sources):
    if not isinstance(checks, dict) or set(checks) - set(sources):
        raise ValueError('检查来源引用错误')
    for result in checks.values():
        if not isinstance(result, dict) or result.get('status') not in ('ok', 'error'):
            raise ValueError('来源检查状态错误')
        valid_date(result.get('last_attempt'))
        if result['status'] == 'ok' or 'hash' in result or 'last_success' in result:
            valid_date(result.get('last_success'))
            if not isinstance(result.get('hash'), str) or not re.fullmatch(r'[a-f0-9]{64}', result['hash']) or result['last_success'] > result['last_attempt']:
                raise ValueError('检查成功日期/指纹错误')
        if 'cached' in result and type(result['cached']) is not bool:
            raise ValueError('缓存标志错误')


def fingerprint(body, source):
    if source['format'] == 'pdf':
        if not body.lstrip().startswith(b'%PDF-'):
            raise ValueError('来源未返回 PDF')
        content = body
    else:
        if source['format'] == 'json':
            try:
                value = json.loads(body)
                if isinstance(value, dict) and value.get('error'):
                    raise ValueError('JSON 接口返回错误')
                for token in source['selector'].split('/')[1:]:
                    token = token.replace('~1', '/').replace('~0', '~')
                    if isinstance(value, list):
                        if not re.fullmatch(r'0|[1-9]\d*', token):
                            raise ValueError('JSON Pointer 数组下标错误')
                        value = value[int(token)]
                    else:
                        value = value[token]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError('JSON 正文须为非空 HTML 字符串')
            except (ValueError, KeyError, IndexError, TypeError) as error:
                raise ValueError('未取得 JSON Pointer 指定的有效正文') from error
            soup = BeautifulSoup('<div></div>', 'html.parser')
            node = soup.div
            node.append(BeautifulSoup(value, 'html.parser'))
        else:
            soup = BeautifulSoup(body, 'html.parser')
            node = soup.select_one(source['selector'])
        if node is None:
            raise ValueError('未找到原文正文，不接受登录/拦截页面')
        for child in node.select('script, style'):
            child.decompose()
        links = [(tag.name, tag.get('href') or tag.get('src') or tag.get('data')) for tag in node.select('a[href], iframe[src], object[data], embed[src]')]
        content = (' '.join(node.stripped_strings) + repr(links)).encode('utf-8')
        if not node.get_text(strip=True) and not links:
            raise ValueError('正文为空')
    return hashlib.sha256(content).hexdigest()


def check_source(source, previous, refresh, today):
    result = dict(previous, last_attempt=today)
    try:
        body, meta, hit = fetch.fetch('GET', source['api'] if source['format'] == 'json' else source['url'], refresh=refresh)
        failed_live = hit and previous.get('status') == 'error'
        result.update(hash=fingerprint(body, source), last_success=meta['fetched_at'], cached=hit,
                      status='error' if failed_live else 'ok', error=previous.get('error') if failed_live else None)
    except Exception as error:
        result.update(status='error', error=str(error)[:500])
    return result

"""公开招生政策摘要校验；来源检查不会修改人工核对记录。"""
import hashlib
import re
from datetime import date
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
        if not isinstance(sid, str) or not re.fullmatch(r'[a-z0-9_-]+', sid) or not isinstance(source, dict) or set(source) != {'url', 'format', 'selector'}:
            raise ValueError('来源结构错误')
        if not isinstance(source['url'], str):
            raise ValueError('来源 URL 须为字符串')
        link = urlsplit(source['url'])
        if link.scheme not in ('http', 'https') or not link.hostname or link.username or link.password or source['format'] not in ('html', 'pdf') or not isinstance(source['selector'], str) or (source['format'] == 'html' and not source['selector']):
            raise ValueError('须登记 HTTP(S) 原文和正文选择器')
    ids = set()
    keys = {'id', 'school', 'dept', 'level', 'title', 'year', 'degree', 'route', 'program', 'program_code', 'published_at', 'reviewed_at', 'review_hashes', 'source_id', 'fields'}
    for p in data['policies']:
        if not isinstance(p, dict) or set(p) != keys:
            raise ValueError('政策结构错误')
        if not isinstance(p['id'], str) or not re.fullmatch(r'[a-z0-9_-]+', p['id']) or p['id'] in ids:
            raise ValueError('政策 ID 错误或重复')
        ids.add(p['id'])
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
        for field in p['fields'].values():
            if not isinstance(field, dict) or set(field) != {'text', 'quote', 'locator'} or any(not isinstance(v, str) or not v.strip() for v in field.values()):
                raise ValueError('每项摘要须有原文片段与定位')


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
        body, meta, hit = fetch.fetch('GET', source['url'], refresh=refresh)
        failed_live = hit and previous.get('status') == 'error'
        result.update(hash=fingerprint(body, source), last_success=meta['fetched_at'], cached=hit,
                      status='error' if failed_live else 'ok', error=previous.get('error') if failed_live else None)
    except Exception as error:
        result.update(status='error', error=str(error)[:500])
    return result

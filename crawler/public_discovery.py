"""Paginate public mentor discovery without receiving private application records.

Public rule semantics mirror discovery-core.js; private reviews stay in the local
browser path. Contract tests compare both implementations against real records.
"""
import hashlib
import json
import re

from crawler.discovery_util import empty, validate_preferences
from crawler.public_catalog import load


LABELS = {'research': '研究关键词', 'qualification': '导师资格', 'email': '公开邮箱',
          'opportunity': '本年度招生机会', 'eligibility': '我的申请资格'}
PARAMS = {'name', 'topics', 'school', 'context_school', 'dept', 'group', 'year',
          'degree', 'route', 'keep_unknown', 'seed', 'offset', 'limit'} | {'mode_' + k for k in LABELS}


def research_text(value):
    return '、'.join(part.strip() for part in re.split(r'[、,，;；\n]+', value or '')
                    if part.strip() and not re.fullmatch(
                        r'(研究方向|Research Focus|社会兼职|Social Affiliations|暂无内容|暂无|待补充|未整理|未知)[：:]?',
                        part.strip(), re.I))


def valid_email(value):
    return bool(isinstance(value, str) and re.fullmatch(
        r'[^\s@<>，；;,]+@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}', value.strip(), re.I))


def includes(text, term):
    if re.fullmatch(r'[a-z0-9 ._-]+', term, re.I):
        return bool(re.search(r'(^|[^a-z0-9])' + re.escape(term) + r'($|[^a-z0-9])', text, re.I))
    return term.lower() in text.lower()


def evaluate(p, prefs, corpus=''):
    checks, evidence = [], []

    def add(key, state, detail):
        checks.append(dict(key=key, state=state, detail=detail, mode=prefs['modes'][key], label=LABELS[key]))

    if prefs['topics']:
        direction = research_text(p.get('research_direction_raw'))
        hits = [term for term in prefs['topics'] if includes(direction, term) or includes(corpus, term)]
        known = bool((direction + ' ' + corpus).strip())
        add('research', 'pass' if hits else 'fail' if known else 'unknown',
            '关键词任一命中：' + '、'.join(hits) if hits else
            '资料文字未命中所选关键词，不代表真实研究不适合' if known else '缺少可检索研究材料')
        for term in hits:
            field = 'research_direction_raw' if includes(direction, term) else 'bio_raw'
            raw = direction if field == 'research_direction_raw' else corpus
            index = raw.lower().find(term.lower())
            evidence.append(dict(field=field, term=term, snippet=raw[max(0, index - 25):index + len(term) + 70]))
    if prefs['degree'] != 'any':
        value = p.get('supervisor', '')
        found = ('博' if prefs['degree'] == 'phd' else '硕') in value and not re.search(r'(无|非|不|未具备)', value)
        add('qualification', 'pass' if found else 'unknown', '官网导师资格：' + value if found else
            '该学位导师资格未明确；其他学位资格不自动推断')
    email = valid_email(p.get('email'))
    add('email', 'pass' if email else 'unknown', '官网提供邮箱，使用前仍需核对' if email else
        '邮箱记录格式异常，请回官网核对' if p.get('email') else '官网库未提供邮箱，需查主页或咨询院系')
    for key in ('opportunity', 'eligibility'):
        add(key, 'unknown', '没有对应年度/学位/渠道的核验记录')
    active = [c for c in checks if c['mode'] != 'off']
    return dict(visible=not any(c['mode'] == 'hard' and (c['state'] == 'fail' or
                     not prefs['keep_unknown'] and c['state'] == 'unknown') for c in active),
                checks=checks, evidence=evidence, score=sum(c['state'] == 'pass' for c in active),
                unknown=sum(c['state'] == 'unknown' for c in active))


def completeness(p):
    def present(value):
        return bool(value and value.strip() and not re.search(r'(未知|待补充|未整理)', value))
    return (int(present(research_text(p.get('research_direction_raw')))) + int(valid_email(p.get('email'))) +
            int(present(p.get('bio_excerpt', ''))) + int(bool(re.match(r'^https?://',
                p.get('profile_url') or p.get('detail_url') or '', re.I))))


def random_key(identifier, seed):
    value = 2166136261
    for char in seed + '|' + identifier:
        code = ord(char)
        # JS for-of iterates code points, while charCodeAt(0) uses the first UTF-16 unit.
        value ^= code if code <= 0xffff else 0xd800 + ((code - 0x10000) >> 10)
        value = value * 16777619 & 0xffffffff
    value ^= value >> 16
    value = value * 0x85ebca6b & 0xffffffff
    value ^= value >> 13
    return value


def candidates(root, query):
    if set(query) - PARAMS or any(not isinstance(v, list) or not v for v in query.values()):
        raise ValueError('仅接受公开筛选条件')
    if any(len(values) != 1 for key, values in query.items() if key != 'school'):
        raise ValueError('筛选参数重复')

    def one(key, default=''):
        return query.get(key, [default])[0]

    for key in ('name', 'context_school', 'dept', 'group', 'seed'):
        if len(one(key)) > 100:
            raise ValueError('筛选参数过长')
    prefs = empty()['preferences']
    prefs.update(topics=json.loads(one('topics', '[]')), schools=query.get('school', []),
                 year=int(one('year')) if one('year') else None, degree=one('degree', 'any'),
                 route=one('route', 'unknown'), keep_unknown=one('keep_unknown', '1') == '1')
    if one('keep_unknown', '1') not in ('0', '1'):
        raise ValueError('保留未知条件参数错误')
    prefs['modes'].update({key: one('mode_' + key, prefs['modes'][key]) for key in LABELS})
    records = load(root, 'discovery-data.js')
    validate_preferences(prefs, {p['page'] for p in records})
    if len(prefs['topics']) > 20 or sum(map(len, prefs['topics'])) > 1000:
        raise ValueError('最多20个研究关键词、合计1000字')
    offset, limit = int(one('offset', '0')), int(one('limit', '20'))
    if not 0 <= offset <= len(records) or not 1 <= limit <= 20:
        raise ValueError('分页范围错误')
    corpus = load(root, 'search.js') if prefs['topics'] else {}
    name, group, school, dept = one('name').lower(), one('group'), one('context_school'), one('dept')
    matched = bool(prefs['topics'] and prefs['modes']['research'] != 'off' or
                   prefs['degree'] != 'any' and prefs['modes']['qualification'] != 'off' or
                   prefs['year'] or prefs['route'] != 'unknown' or
                   any(prefs['modes'][key] == 'hard' for key in ('email', 'opportunity', 'eligibility')))
    rows = []
    for p in records:
        if (prefs['schools'] and p['school'] not in prefs['schools'] or name and name not in p['name'].lower() or
                group and group not in p.get('unit_groups', []) or school and school != p['school'] or dept and dept != p['dept']):
            continue
        result = evaluate(p, prefs, corpus.get(p['page'], ''))
        if result['visible']:
            rows.append(dict(p=p, result=result))
    def order(row):
        p, result = row['p'], row['result']
        return ((-result['score'], result['unknown']) if matched else ()) + (
            -completeness(p), random_key(p['page'], one('seed')), p['page'])
    rows.sort(key=order)
    stamps = []
    for filename in ('discovery-data.js', 'search.js'):
        stat = (root / 'site' / filename).stat()
        stamps.append((stat.st_mtime_ns, stat.st_size, stat.st_ino))
    revision = hashlib.sha256(repr(stamps).encode()).hexdigest()[:20]
    return dict(version=1, total=len(rows), offset=offset, limit=limit, matched=matched,
                revision=revision, rows=rows[offset:offset + limit])

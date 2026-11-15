"""Paginate public mentor discovery without receiving private application records.

Public rule semantics mirror discovery-core.js; private reviews stay in the local
browser path. Contract tests compare both implementations against real records.
"""
import hashlib
import json
import re

from crawler.public_catalog import load


LABELS = {'research': '研究关键词', 'qualification': '导师资格', 'email': '公开邮箱',
          'opportunity': '本年度招生机会', 'eligibility': '我的申请资格'}



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


TITLE_GROUPS = {
    'professor': ('教授', '长聘教授', '特聘教授', '讲席教授', '准聘教授', '兼职教授', '教授（研究员）'),
    'associate_professor': ('副教授', '长聘教轨副教授', '长聘副教授', '特聘副教授', '预聘副教授', '准聘副教授'),
    'assistant_professor': ('助理教授', '预聘助理教授', '长聘教轨助理教授'),
    'lecturer': ('讲师',),
    'researcher': ('研究员', '特聘研究员', '青年研究员', '长聘研究员', '讲席研究员', '正高级研究员'),
    'associate_researcher': ('副研究员', '特聘副研究员', '青年副研究员', '副高级研究员'),
    'assistant_researcher': ('助理研究员',),
    'other': ('副高级', '正高级', '中级', '高级工程师', '工程师', '正高级工程师', '实验师', '研究实习员',
              '高级实验师', '教辅系列', '助理工程师', '助教', '教授级高级工程师', '正高级实验师', '馆员'),
}
TITLE_IDS = set(TITLE_GROUPS) | {'unknown'}
LEGACY_PARAMS = {'degree', 'year', 'route', 'keep_unknown'} | {'mode_' + key for key in LABELS}
PARAMS = {'name', 'topics', 'school', 'context_school', 'dept', 'group', 'seed', 'offset', 'limit',
          'qualifications', 'titles', 'include_missing_email'} | LEGACY_PARAMS


def title_group(value):
    return next((key for key, values in TITLE_GROUPS.items() if (value or '').strip() in values), 'unknown')


def contactable(p):
    source = p.get('email_source') or (p.get('provenance') or {}).get('email', {}).get('source', '')
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(source)
        return valid_email(p.get('email')) and parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    except (ValueError, TypeError):
        return False


def directory_match(p, criteria, corpus=''):
    if not criteria.get('include_missing_email') and not contactable(p):
        return False
    if criteria.get('qualifications'):
        value = p.get('supervisor') or ''
        if re.search(r'(无|非|不|未具备)', value) or not any(
                ('博' if key == 'phd' else '硕') in value for key in criteria['qualifications']):
            return False
    if criteria.get('titles') and title_group(p.get('title')) not in criteria['titles']:
        return False
    if criteria.get('topics') and not any(includes(research_text(p.get('research_direction_raw')), term) or
                                         includes(corpus, term) for term in criteria['topics']):
        return False
    return True


def candidates(root, query):
    if set(query) - PARAMS or any(not isinstance(v, list) or not v for v in query.values()):
        raise ValueError('仅接受公开筛选条件')
    if any(len(values) != 1 for key, values in query.items() if key not in ('school', 'qualifications', 'titles')):
        raise ValueError('筛选参数重复')
    def one(key, default=''):
        return query.get(key, [default])[0]
    for key in ('name', 'context_school', 'dept', 'group', 'seed'):
        if len(one(key)) > 100:
            raise ValueError('筛选参数过长')
    topics = json.loads(one('topics', '[]'))
    if not isinstance(topics, list) or len(topics) > 20 or any(not isinstance(t, str) or not t.strip() or len(t) > 100 for t in topics) or sum(map(len, topics)) > 1000:
        raise ValueError('最多20个研究关键词、合计1000字')
    qualifications, titles, schools = query.get('qualifications', []), query.get('titles', []), query.get('school', [])
    if len(qualifications) > 2 or set(qualifications) - {'phd', 'master'} or len(titles) > len(TITLE_IDS) or set(titles) - TITLE_IDS:
        raise ValueError('导师资格或职称无效')
    if one('include_missing_email', '0') not in ('0', '1'):
        raise ValueError('邮箱范围无效')
    records = load(root, 'discovery-data.js')
    if len(schools) > 50 or set(schools) - {p['school'] for p in records}:
        raise ValueError('未知学校')
    offset, limit = int(one('offset', '0')), int(one('limit', '20'))
    if not 0 <= offset <= len(records) or not 1 <= limit <= 20:
        raise ValueError('分页范围错误')
    criteria = dict(topics=topics, qualifications=qualifications, titles=titles,
                    include_missing_email=one('include_missing_email', '0') == '1')
    corpus = load(root, 'search.js') if topics else {}
    rows, missing_email = [], 0
    for p in records:
        if (schools and p['school'] not in schools or one('name').lower() not in p['name'].lower() or
            one('group') and one('group') not in p.get('unit_groups', []) or
            one('context_school') and one('context_school') != p['school'] or one('dept') and one('dept') != p['dept']):
            continue
        if not directory_match(p, dict(criteria, include_missing_email=True), corpus.get(p['page'], '')):
            continue
        if not contactable(p):
            missing_email += 1
            if not criteria['include_missing_email']:
                continue
        rows.append(dict(p=p))
    rows.sort(key=lambda row: (-completeness(row['p']), random_key(row['p']['page'], one('seed')), row['p']['page']))
    stamps = []
    for filename in ('discovery-data.js', 'search.js'):
        stat = (root / 'site' / filename).stat()
        stamps.append((stat.st_mtime_ns, stat.st_size, stat.st_ino))
    revision = hashlib.sha256(('directory-v2:' + repr(stamps)).encode()).hexdigest()[:20]
    return dict(version=2, total=len(rows), missing_email=missing_email, offset=offset, limit=limit,
                revision=revision, rows=rows[offset:offset + limit])

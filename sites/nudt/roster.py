"""公开导师查询表单的分页读取；登记资格不代表当年名额。"""
import json
import math
import re
from bs4 import BeautifulSoup
from crawler import fetch
from crawler.email_util import normalize_email

API = 'https://yjszs.nudt.edu.cn/zsmh/pubweb/homePageList/list.json'
VIEW = 'https://yjszs.nudt.edu.cn/zsmh/pubweb/homePageList/getView.view?keyId='


def parse_detail(cfg, html, url):
    """Official public mentor detail fields; registration is not a current vacancy."""
    if not url.startswith(VIEW):
        raise ValueError('不是已登记的国防科大公开导师详情入口')
    lines = BeautifulSoup(html, 'html.parser').get_text('\n', strip=True).splitlines()
    labels = {'姓名', '学院', '学科', '导师层次', '基本情况'}
    values, current = {}, None
    for line in lines:
        line = line.strip()
        label = line.rstrip('：:')
        if label in labels:
            current = label
            values[current] = []
        elif current and line:
            values[current].append(line)
    fields = {key: ' '.join(value).strip() for key, value in values.items()}
    if cfg['dept_name'] not in re.split(r'[、,，;；|]', fields.get('学院', '')):
        raise ValueError('公开导师详情的学院归属与配置不符')
    name, bio = fields.get('姓名'), fields.get('基本情况', '')
    if not name or not bio:
        raise ValueError('公开导师详情缺少姓名或基本情况')
    out = {'name': name, 'bio_raw': bio}
    if fields.get('导师层次') in ('博导', '硕导'):
        out['supervisor'] = fields['导师层次']
    match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', bio)
    if match:
        out['email'] = normalize_email(match.group())
    directions = re.findall(r'(?:主要研究方向|研究方向)\s*[:：]\s*([^。！？\n]+)', bio)
    if not directions:
        directions = re.findall(r'(?:主要从事|长期从事|主要研究|从事)([^。！？\n]*(?:研究|设计|开发)[^。！？\n]*)', bio)
    if directions:
        out['research_direction_raw'] = '；'.join(directions)[:500]
    return out


def record(row, unit, fetched_at):
    if unit not in re.split(r'[、,，;；|]', row.get('unit') or ''):
        raise ValueError('导师登记归属不匹配')
    if not row.get('keyId') or not row.get('tchNo'):
        raise ValueError('导师登记缺少身份字段')
    url = VIEW + str(row['keyId'])
    text = BeautifulSoup(row.get('headship') or '', 'html.parser').get_text(' ', strip=True)
    directions = re.findall(r'[^。！？\n]*研究方向[^。！？\n]*(?:[。！？]|$)', text)
    email = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)
    out = {'name': row['tchNo'].strip(), 'url': url, 'profile_url': url,
           'subjects': row.get('subunit'), 'roster_source': url, 'bio_raw': text,
           'roster_fetched_at': fetched_at,
           'institutes': ['官方导师登记归属：' + row['unit']]}
    if row.get('title') in ('博导', '硕导'):
        out['supervisor'] = row['title']
    if directions:
        out['research_direction_raw'] = ' '.join(s.strip() for s in directions)
    if email:
        out['email'] = normalize_email(email.group())
    return out


def iter_roster(cfg):
    people, seen, dates = [], set(), []
    total = None
    page = 1
    while total is None or page <= math.ceil(total / 50):
        if page > 20:
            raise ValueError('导师分页超限')
        html, meta, _ = fetch.fetch_text('POST', API, {'unit': cfg['dept_name'], 'pager.pageSize': 50, 'pager.pageNo': page})
        payload = json.loads(html)
        reported = payload['pager.totalRows']
        if total is not None and reported != total:
            raise ValueError('导师分页总数变化，停止')
        total = reported
        rows = payload['rows']
        if not isinstance(total, int) or total <= 0 or len(rows) != min(50, total - (page - 1) * 50):
            raise ValueError('导师分页缺失或数量异常')
        for row in rows:
            if row['keyId'] in seen:
                raise ValueError('导师分页重复身份，停止')
            seen.add(row['keyId'])
            people.append(record(row, cfg['dept_name'], meta['fetched_at']))
        dates.append(meta['fetched_at'])
        page += 1
    email_names = {}
    for person in people:
        if person.get('email'):
            email_names.setdefault(person['email'].lower(), set()).add(person['name'])
    for person in people:
        if person.get('email') and len(email_names[person['email'].lower()]) > 1:
            person['shared_contact'] = person.pop('email')
    return people, {'fetched_at': min(dates), 'roster_total': total, 'pages': page - 1}

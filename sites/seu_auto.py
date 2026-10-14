"""东南自动化官网公开 teacherHome 名单；只收录明示学术身份的条目。"""
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
from crawler.title_util import normalize_title


API_PATH = '/_wp3services/generalQuery?queryObj=teacherHome'
RANK = re.compile(r'教授|研究员|讲师|工程师|实验师|助教')


def supervisor(text):
    return '、'.join(v for label, v in [('博士生导师', '博导'), ('硕士生导师', '硕导')] if label in text)


def collect(cfg, rows, fetched_at):
    out = {}
    for row in rows:
        match = re.match(r'^[\u4e00-\u9fff·]{2,6}', row.get('title', '').strip())
        title = row.get('post', '').strip()
        sup = supervisor(row.get('exField1', ''))
        if not match or not (sup or RANK.search(title)):
            continue
        url = urljoin(cfg['base_url'], row.get('cnUrl', ''))
        if urlsplit(url).hostname != urlsplit(cfg['base_url']).hostname:
            raise ValueError('官方名单出现未登记的跨站个人页')
        # 官网给出 http 链接，使用同主机提供的 HTTPS 个人页。
        url = re.sub(r'^http:', 'https:', url)
        rec = {'name': match.group(), 'url': url, 'profile_url': url, 'institutes': [],
               'roster_source': cfg['list']['urls'][0], 'roster_fetched_at': fetched_at}
        if RANK.search(title):
            rec['title'] = normalize_title(title)[0]
        if sup:
            rec['supervisor'] = sup
        out.setdefault((rec['name'], url), rec)
    return list(out.values())


def iter_roster(cfg):
    params = {'siteId': 338, 'pageIndex': 1, 'rows': 100,
              'conditions': json.dumps([{'field': 'published', 'value': '1', 'judge': '='}]),
              'orders': json.dumps([{'field': 'letter', 'type': 'asc'}]),
              'returnInfos': json.dumps([{'field': x, 'name': x} for x in ['title', 'exField1', 'degree', 'post', 'cnUrl', 'headerPic']]),
              'articleType': 1, 'level': 1}
    raw, people, dates = [], {}, []
    total = None
    pages = 1
    page = 1
    while page <= pages:
        params['pageIndex'] = page
        text, meta, _ = fetch.fetch_text('POST', urljoin(cfg['base_url'], API_PATH), dict(params))
        result = json.loads(text)
        if total is None:
            total, pages = int(result['total']), int(result['pageCount'])
            if total <= 0 or not 1 <= pages <= 20:
                raise ValueError('名单总数为空或分页超限')
        if int(result['total']) != total or int(result['pageCount']) != pages or not result['data']:
            raise ValueError('名单分页不一致或页面为空')
        raw.extend(result['data'])
        for rec in collect(cfg, result['data'], meta['fetched_at']):
            people.setdefault((rec['name'], rec['url']), rec)
        dates.append(meta['fetched_at'])
        page += 1
    observed_counts = {'reported': total, 'returned': len(raw), 'pages': pages}
    verified_gap = observed_counts == cfg['list'].get('verified_counts')
    if len(raw) > total or not people or (len(raw) != total and not verified_gap):
        raise ValueError('名单未完整分页或没有可确认的学术身份记录')
    if len({(r.get('title'), r.get('cnUrl')) for r in raw}) != len(raw):
        raise ValueError('名单分页有重复条目，停止而非掩盖分页失效')
    return list(people.values()), {'fetched_at': min(dates), 'pages': pages, 'raw_total': total,
                                 'returned_total': len(raw), 'selected_total': len(people),
                                 'partial': len(raw) != total}


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, 'html.parser')
    header = soup.select_one('.carrer')
    content = soup.select_one('.tearchContainer')
    if header is None or header.select_one('.xing') is None:
        raise ValueError('个人页缺少姓名与身份区，不能将空壳当成已富化')
    out = {'name': header.select_one('.xing').get_text(strip=True)}
    for node in header.select('.title span'):
        text = node.get_text(' ', strip=True)
        if RANK.search(text):
            out['title'] = normalize_title(text)[0]
        if supervisor(text):
            out['supervisor'] = supervisor(text)
    for node in header.select('.text'):
        text = node.get_text(' ', strip=True)
        if re.match(r'邮箱\s*[:：]', text):
            match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)
            if match and normalize_email(match.group()):
                out['email'] = normalize_email(match.group())
        for label, field in [('电话', 'phone'), ('地点', 'office_address')]:
            if re.match(label + r'\s*[:：]', text):
                value = re.split(r'[:：]', text, maxsplit=1)[1].strip()
                if value:
                    out[field] = value
    if content is not None:
        for section in content.select('.news_box'):
            heading, body = section.select_one('.tit'), section.select_one('.con')
            if heading is None or body is None:
                continue
            label, text = heading.get_text(strip=True), body.get_text('\n', strip=True)
            if label in ('基本信息', '个人简介') and text:
                out['bio_raw'] = text
            if label in ('研究兴趣', '研究方向', '研究领域') and text:
                out['research_directions'] = [text]
    return out

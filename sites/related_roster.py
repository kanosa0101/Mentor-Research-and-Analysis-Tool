"""已核验的相关院系卡片名单；限制同站分页，逐条保留来源日期。"""
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from crawler import fetch
from crawler.email_util import normalize_email
from crawler.title_util import normalize_title
from sites.wp import parse_wp_detail
from sites.profile_fields import research, qualification, own_labelled_email


def collect(cfg, page_url, html, fetched_at):
    listing = cfg['list']
    soup = BeautifulSoup(html, 'html.parser')
    out = {}
    for card in soup.select(listing['card_selector']):
        anchor = card.select_one(listing['link_selector'])
        name_node = card.select_one(listing['name_selector'])
        if anchor is None or name_node is None:
            continue
        name = re.sub(r'\s+', '', name_node.get_text(strip=True))
        if not re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', name):
            continue
        url = urljoin(page_url, anchor.get('href', ''))
        if urlsplit(url).hostname not in listing.get('person_hosts', [urlsplit(cfg['base_url']).hostname]) or not re.search(listing['person_href'], url):
            continue
        rec = {'name': name, 'url': url, 'profile_url': url, 'institutes': [],
               'roster_source': listing.get('public_url', page_url), 'roster_fetched_at': fetched_at}
        if listing.get('supervisor'):
            rec['supervisor'] = listing['supervisor']
        text = card.get_text('\n', strip=True)
        for key, labels in [('title', '职称'), ('research_direction_raw', '研究领域|研究方向'), ('phone', '办公电话|联系电话')]:
            match = re.search('(?:' + labels + r')\s*[：:]?\s*([^\n]+)', text)
            if match:
                rec[key] = match.group(1).strip()
        email = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)
        if email and normalize_email(email.group()):
            rec['email'] = normalize_email(email.group())
        out.setdefault((name, url), rec)
    return list(out.values())


def iter_roster(cfg):
    listing = cfg['list']
    pending = list(listing['urls'])
    seen, people, dates = set(), {}, []
    while pending:
        url = pending.pop(0)
        if url in seen:
            continue
        if len(seen) >= 50 or urlsplit(url).hostname != urlsplit(cfg['base_url']).hostname:
            raise ValueError('名单分页超限或跨站')
        seen.add(url)
        html, meta, _ = fetch.fetch_text(listing.get('method', 'GET'), url, listing.get('params'))
        if listing.get('json_content'):
            html = json.loads(html)['content']
        rows = collect(cfg, url, html, meta['fetched_at'])
        if not rows:
            raise ValueError('已登记名单页面未提取到教师，停止而非写入不完整名单：' + url)
        for row in rows:
            people.setdefault((row['name'], row['url']), row)
        dates.append(meta['fetched_at'])
        if listing.get('next_selector'):
            soup = BeautifulSoup(html, 'html.parser')
            for link in soup.select(listing['next_selector']):
                nxt = urljoin(url, link.get('href', ''))
                if nxt not in seen:
                    pending.append(nxt)
    return list(people.values()), {'fetched_at': min(dates), 'pages': len(seen)}


def parse_detail(cfg, html, url):
    result = parse_wp_detail(cfg, html, url)
    soup = BeautifulSoup(html, 'html.parser')
    for key, selector in cfg.get('detail_fields', {}).items():
        nodes = soup.select(selector)
        node = next((n for n in nodes if re.search(r'教授|研究员|讲师|工程师|院士|实验师|研究实习员|助教', n.get_text()) and not re.search(r'曾任|原任', n.get_text())), None) if key == 'title' else next(iter(nodes), None)
        if node is not None:
            value = node.get_text(' ', strip=True)
            if key == 'title' and not re.search(r'教授|研究员|讲师|工程师|院士|实验师|研究实习员|助教', value):
                value = None
            if key == 'title' and value:
                value = normalize_title(value)[0]
            if key == 'email':
                match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', value)
                value = normalize_email(match.group()) if match else None
            if value:
                result[key] = value
    if cfg.get('bio_selector'):
        text = '\n'.join(n.get_text('\n', strip=True) for n in soup.select(cfg['bio_selector']))
        if text.strip():
            result['bio_raw'] = text
    biography=result.get('bio_raw') or ''
    direction=research(biography)
    if direction:result['research_direction_raw']=direction
    name=result.get('name') or cfg.get('_expected_name')
    personal_header='\n'.join(n.get_text('\n',strip=True) for selector in cfg.get('detail_fields',{}).values() for n in soup.select(selector))
    supervisor=qualification(biography,name) or qualification(personal_header,name)
    if supervisor:result['supervisor']=supervisor
    if not result.get('email'):
        email=own_labelled_email(biography)
        if email:result['email']=email
    if biography or personal_header:result['_field_scope']=personal_header+'\n'+biography
    return result

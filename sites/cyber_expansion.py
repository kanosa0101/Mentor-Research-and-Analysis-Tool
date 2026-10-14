"""两所网安学院的正式院系名单；仅提取官网明确字段，不解密隐藏联系方式。"""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
from sites.wp import parse_wp_detail
from sites.tsites import _header_block, parse_detail as parse_portal

WHU_UNITS = {'信息安全系', '网络空间安全系', '密码科学与技术系'}


def collect(cfg, page_url, html, fetched_at):
    soup = BeautifulSoup(html, 'html.parser')
    groups = []
    if cfg['school'] == 'whu':
        for heading in soup.select('.wlaq-sz-box h3.name'):
            unit = heading.get_text(strip=True)
            listing = heading.find_next_sibling('div', class_='wlaq-sz-list')
            if unit in WHU_UNITS and listing:
                for block in listing.select('li'):
                    rank = block.select_one('h3.zc')
                    groups.append((block.select('.sz-list a[href]'), unit, rank.get_text(strip=True) if rank else None))
    else:
        groups = [(soup.select('dl dd li a[href]'), cfg['list'].get('units', {}).get(page_url), None)]
    people = {}
    for anchors, unit, title in groups:
        for a in anchors:
            name = re.sub(r'\s+', '', a.get_text(strip=True))
            url = urljoin(page_url, a['href'])
            if not re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', name) or urlsplit(url).hostname not in cfg['list']['person_hosts']:
                continue
            rec = {'name': name, 'url': url, 'profile_url': url, 'institutes': [unit] if unit else [],
                   'roster_source': page_url, 'roster_fetched_at': fetched_at}
            if title in {'教授', '副教授', '讲师', '研究员', '副研究员', '工程师', '高级工程师', '实验师', '高级实验师', '助理研究员'}:
                rec['title'] = title
            people.setdefault((name, url), rec)
    return list(people.values())


def iter_roster(cfg):
    people, dates = {}, []
    for url in cfg['list']['urls']:
        html, meta, _ = fetch.fetch_text('GET', url)
        rows = collect(cfg, url, html, meta['fetched_at'])
        if not rows:
            raise ValueError('登记的正式师资名单为空，停止采集：' + url)
        for row in rows:
            people.setdefault((row['name'], row['url']), row)
        dates.append(meta['fetched_at'])
    return list(people.values()), {'fetched_at': min(dates), 'pages': len(dates)}


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select('script, style, nav, footer, .footer, #footer, [_tsites_encrypt_field], [style*="display:none"], [style*="display: none"]'):
        node.decompose()
    is_portal = urlsplit(url).hostname in {'faculty.hust.edu.cn', 'jszy.whu.edu.cn'}
    out = parse_portal(cfg, str(soup), url) if is_portal else parse_wp_detail(cfg, str(soup), url)
    # 名单具有职称时不以履历里的旧任职覆盖；门户只接受明确职称标签。
    if not is_portal:
        out.pop('title', None)
        out.pop('supervisor', None)
        name = soup.find('meta', attrs={'name': 'pageTitle'})
        if name and re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', name.get('content', '')):
            for block in soup.select('.teacher-cont'):
                heading, paragraph = block.select_one('h3'), block.select_one('p')
                if heading and heading.get_text(strip=True) == '个人简介' and paragraph:
                    sentence = re.split(r'[。；;]', paragraph.get_text(' ', strip=True), maxsplit=1)[0]
                    if sentence.startswith(name['content']) and len(sentence) < 150 and not re.search(r'曾任|原任|曾经|师从|导师为|导师是|指导老师', sentence):
                        bits = [short for full, short in [('博士生导师', '博导'), ('硕士生导师', '硕导')] if full in sentence]
                        if bits:
                            out['supervisor'] = '、'.join(bits)
    else:
        out.pop('research_directions', None)
        out.pop('title', None)
        out.pop('supervisor', None)
        out.pop('email', None)
        identity = _header_block(soup)
        if not identity and soup.select_one('.infoblock'):
            identity = soup.select_one('.infoblock').get_text('\n', strip=True)
        for line in identity.split('\n'):
            value = re.sub(r'^(?:职称|职务)\s*[：:]\s*', '', line).strip()
            if re.fullmatch(r'教授|副教授|讲师|研究员|副研究员|助理研究员|工程师|高级工程师', value):
                out.setdefault('title', value)
        qualification = [re.sub(r'^(?:导师类型|导师资格)\s*[：:]\s*', '', line).strip() for line in identity.split('\n')]
        qualification = [line for line in qualification if re.fullmatch(r'(?:博士生导师|硕士生导师)(?:[、，,\s]+(?:博士生导师|硕士生导师))*', line)]
        bits = [short for full, short in [('博士生导师', '博导'), ('硕士生导师', '硕导')] if any(full in line for line in qualification)]
        if bits:
            out['supervisor'] = '、'.join(bits)
        for node in soup.select('p, li, td'):
            text = node.get_text(' ', strip=True)
            match = re.match(r'^[·•\s]*(?:电子邮箱|邮箱|E-mail|Email)\s*[：:]\s*(.+)', text, re.I)
            if match and len(text) < 300:
                email = normalize_email(match.group(1))
                if email:
                    out.setdefault('email', email)
    scope = soup.select_one('.infoblock') or soup.select_one('.wlaq-teacher-inf') or soup.select_one('.v_news_content')
    if scope:
        text = scope.get_text('\n', strip=True)
        for label, field in [('职称', 'title'), ('电子邮箱|邮箱|E-mail|Email', 'email'), ('办公电话|联系电话', 'phone')]:
            match = re.search(r'(?:' + label + r')\s*[：:]\s*([^\n]+)', text, re.I)
            if match:
                value = match.group(1).strip()
                if field == 'email':
                    email = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', value)
                    value = normalize_email(email.group()) if email else None
                if field == 'title' and not re.fullmatch(r'教授|副教授|讲师|研究员|副研究员|助理研究员|工程师|高级工程师', value):
                    value = None
                if value:
                    out[field] = value
        if is_portal:
            out.setdefault('bio_raw', text)
    directions = []
    for block in soup.select('.teacher-cont'):
        heading = block.select_one('h3')
        if heading and heading.get_text(strip=True) == '研究方向':
            directions.extend(p.get_text(' ', strip=True) for p in block.select('p') if p.get_text(strip=True))
    if not directions:
        for block in soup.select('.Rsh-focus .cont'):
            directions.extend(n.get_text(' ', strip=True) for n in block.select('li, p') if n.get_text(strip=True))
    if not directions:
        for heading in soup.select('h2'):
            if heading.get_text(strip=True) == '研究方向':
                block = heading.find_next_sibling() or heading.parent.find_next_sibling()
                if block:
                    directions.extend(n.get_text(' ', strip=True) for n in block.select('li, p') if n.get_text(strip=True))
    directions = [re.sub(r'^[·•\s]+', '', value).strip() for value in directions]
    directions = list(dict.fromkeys(value for value in directions if value and value not in {'研究领域', '研究方向'}))
    if directions:
        out['research_directions'] = directions
    if not any(out.get(key) for key in ['bio_raw', 'title', 'email', 'research_directions', 'supervisor']):
        raise ValueError('详情未识别到明确个人信息，保留名单并登记缺口')
    return out

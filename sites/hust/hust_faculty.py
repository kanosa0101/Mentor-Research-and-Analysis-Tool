"""HUST's named department articles and visible official profile modules."""
import re
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString

from crawler import fetch
from crawler.mentor_recovery import homepage_url, personal_email
from crawler.title_util import normalize_title
from sites import cyber_expansion, hust_profile, related_v7
from sites.profile_fields import clean_research, qualification, research

PORTAL = 'faculty.hust.edu.cn'
CYBER_LAB = 'cse-sinclab.hust.edu.cn'
DEPARTMENT = {'aia': 'aia.hust.edu.cn', 'cyber': 'cse.hust.edu.cn'}
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
MAIL_LABEL = re.compile(r'^(?:本人邮箱|电子邮箱|电子邮件|邮箱|E-?mail)\s*[:：]\s*(.+)$', re.I)
TITLE = re.compile(related_v7.TITLE)
RANKS = {'博士生导师': '博导', '博士研究生导师': '博导', '博导': '博导',
         '硕士生导师': '硕导', '硕士研究生导师': '硕导', '硕导': '硕导'}
PERSON = re.compile(r'[\u3400-\u9fff·]{2,6}')
HOME_LABELS = {'个人主页', '本人主页', '个人网站', '学术主页', 'personal homepage', 'personal website'}
TRUNCATED = re.compile(r'…|\.{3,}|\bMore\s*\+|查看更多', re.I)
DIRECTION_END = re.compile(
    r'[，,；;：:]\s*(?=(?:在[^。]{0,120}(?:会议|期刊)|特别是在[^。]{0,100}(?:取得|成果)|'
    r'首次提出|发表论文|包括\s*[:：]|具体在[^。]{0,150}方面开展))'
)


def clean_direction(value):
    if not value or TRUNCATED.search(value):
        return None
    value = clean_research(DIRECTION_END.split(value, maxsplit=1)[0])
    return value if value and not value.startswith('我们关心') else None


def cyber_titles(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    title = ''
    for element in soup.select('.jcrc .rc_bt h6,.jcrc .bt > a[href]'):
        label = element.get_text(strip=True)
        if element.name == 'h6':
            title = label if TITLE.fullmatch(label) else ''
        elif title and PERSON.fullmatch(label):
            target = urljoin(url, element['href'])
            if urlsplit(target).hostname in (PORTAL, DEPARTMENT['cyber']):
                rows.append((label, target, title))
    return rows


def iter_roster(cfg):
    if cfg['dept'] != 'cyber':
        return related_v7.iter_roster(cfg)
    rows, meta = cyber_expansion.iter_roster(cfg)
    by_person = {(row['name'], row['url']): row for row in rows}
    for url in cfg.get('profile_lookup_urls', []):
        if '/szdw/axsjs/' not in url:
            continue
        try:
            html, source, _ = fetch.fetch_text('GET', url)
        except OSError:
            continue
        for name, target, title in cyber_titles(html, url):
            row = by_person.get((name, target))
            if row is not None and not row.get('title'):
                row.update(title=title, roster_source=url, roster_fetched_at=source['fetched_at'])
    cfg['_roster_names'] = {row['url']: row['name'] for row in rows}
    return rows, meta


def personal_name(soup, host):
    if host == PORTAL:
        headings = soup.select('.js-top .info h2,.name h1,.photobox .name,.t_xm,.t_name')
        title = soup.title.get_text(' ', strip=True) if soup.title else ''
        named_title = re.match(r'^华中科技大学主页平台管理系统\s+([\u3400-\u9fff·]{2,6})--', title)
        names = {node.get_text(strip=True) for node in headings if PERSON.fullmatch(node.get_text(strip=True))}
        names.update(hust_profile.identity_names(soup))
        if named_title:
            names.add(named_title[1])
    elif host == CYBER_LAB:
        title = soup.title.get_text(strip=True) if soup.title else ''
        value = re.sub(r'\s+', '', title.removesuffix('-天地一体化实验室'))
        card = soup.select_one('.v_news_content tr.firstRow')
        names = {value} if title.endswith('-天地一体化实验室') and PERSON.fullmatch(value) and card and value in re.sub(r'\s+', '', card.get_text()) else set()
    else:
        names = {node.get_text(strip=True) for node in soup.select('.content_title h1,.am-article-hd h1,.v_news_content .txt h1')
                 if PERSON.fullmatch(node.get_text(strip=True))}
    return next(iter(names)) if len(names) == 1 else None


def visible_mail(lines):
    addresses = set()
    for line in lines:
        match = MAIL_LABEL.fullmatch(line.strip())
        if not match or hust_profile._TEAM_NEARBY.search(line):
            continue
        for token in EMAIL.findall(match[1]):
            value = personal_email(token)
            if value and value.split('@', 1)[0].casefold() not in {'aia-president', 'cyberse', 'zdhyjsk'}:
                addresses.add(value)
    return next(iter(addresses)) if len(addresses) == 1 else None


def visible_lines(blocks):
    lines = []
    for block in blocks:
        current = []
        for node in block.descendants:
            if isinstance(node, Comment):
                continue
            if isinstance(node, NavigableString):
                current.append(str(node).strip())
            elif node.name in ('br', 'p', 'li', 'tr'):
                lines.append(' '.join(part for part in current if part))
                current = []
        lines.append(' '.join(part for part in current if part))
    return [line for line in lines if line]


def cyber_lab_email(html, name):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select(hust_profile._HIDDEN):
        node.decompose()
    matches = []
    for card in soup.select('.member td'):
        heading = card.find('b')
        if (heading and not card.find('table') and re.sub(r'\s+', '', heading.get_text()) == name
                and '华中科技大学网络空间安全学院' in re.sub(r'\s+', '', card.get_text())):
            matches.append(card)
    if len(matches) != 1:
        return None
    lines = [re.sub(r'^华中科技大学\s*网络空间安全学院(?:6G中心)?\s+(?=邮箱\s*[:：])', '', line)
             for line in visible_lines(matches)]
    return visible_mail(lines)


def parse_person(cfg, html, url):
    host = urlsplit(url).hostname
    if host not in (PORTAL, DEPARTMENT.get(cfg['dept'])) and not (cfg['dept'] == 'cyber' and host == CYBER_LAB):
        return {}
    soup = BeautifulSoup(html, 'html.parser')
    name = personal_name(soup, host)
    expected = cfg.get('_expected_name') or cfg.get('_roster_names', {}).get(url)
    if not name or (expected and name != expected):
        raise ValueError('HUST具名官方详情与所登记人员不符')
    for node in soup.select(hust_profile._HIDDEN + ',.footer,#footer,.translatorExtension'):
        node.decompose()
    if host == PORTAL:
        identity = soup.select('.dft-side .Psl-info .cont,.t_jbxx_nr,.jbqk,.brief .data,.photobox .name')
        contact = soup.select('.Ot-ctact .cont,.t_qtlxfs_nr,.xx_lx') + identity
        overview = soup.select_one('.dft-midcont .Psl-info .cont,.t_grjj_nr,.brief .summary,.zw-article .atccont')
        if overview is None:
            heading = next((node for node in soup.select('.part_tit') if node.get_text(strip=True) == '个人简介'), None)
            overview = heading.find_next_sibling(class_='account') if heading else None
        directions = soup.select('.Rsh-focus .cont li,.Rsh-focus .cont p')
    else:
        article = soup.select_one('.v_news_content')
        if not article:
            raise ValueError('HUST个人条目没有可读取的本人正文')
        identity = article.select('.txt,.teacher-cont .teacher-info,.wlaq-teacher-inf,.infoblock')
        if host == CYBER_LAB:
            identity = article.select('tr.firstRow')[:1]
        contact = identity or article.find_all('p', recursive=False)[:4]
        identity = identity or contact
        overview = article.select_one('.t_con,.teacher-cont') or article
        directions = []

    body_lines = visible_lines(identity) + [line for node in identity for line in node.get_text('\n', strip=True).splitlines()]
    contacts = [line for node in contact for line in node.get_text('\n', strip=True).splitlines()]
    contacts.extend(visible_lines(contact))
    for block in contact:
        for node in block.select('p,li,tr'):
            contacts.append(node.get_text(' ', strip=True))
        if block.name == 'p':
            contacts.append(block.get_text(' ', strip=True))
        for link in block.select('a[href^="mailto:"]'):
            if MAIL_LABEL.fullmatch(link.parent.get_text(' ', strip=True)):
                contacts.append('邮箱：' + unquote(link['href'][7:].partition('?')[0]))
    values = {'name': name}
    if email := visible_mail(contacts):
        values['email'] = email
    homepages = {homepage_url(urljoin(url, a['href'])) for block in identity + ([overview] if overview else [])
                 for a in block.select('a[href]') if a.get_text(strip=True).lower() in HOME_LABELS}
    homepages.discard(None)
    if len(homepages)==1:
        values['homepage'] = next(iter(homepages))
    for line in body_lines:
        text = re.sub(r'^(?:职称|职务|导师类型|导师资格)\s*[:：]\s*', '', line)
        for part in re.split(r'[、，,；;]+', text):
            if TITLE.fullmatch(part.strip()):
                values.setdefault('title', normalize_title(part.strip())[0])
    ranks = {RANKS[part.strip()] for line in body_lines
             for part in re.split(r'[、，,；;]+', re.sub(r'^(?:职称|导师类型|导师资格)\s*[:：]\s*', '', line))
             if part.strip() in RANKS}
    bio = overview.get_text('\n', strip=True) if overview else ''
    if result := qualification(bio, name):
        ranks.update(result.split('、'))
    if ranks:
        values['supervisor'] = '、'.join(rank for rank in ('博导', '硕导') if rank in ranks)
    terms = list(dict.fromkeys(term for node in directions if (term := clean_direction(node.get_text(' ', strip=True)))))
    direction = '、'.join(terms)
    if direction := direction or clean_direction(research(bio)):
        values['research_direction_raw'] = direction
    if bio and bio not in {'暂无内容', 'No content'}:
        values['bio_raw'] = bio
    return values


def parse_detail(cfg, html, url):
    parsed = parse_person(cfg, html, url)
    if not parsed:
        return (cyber_expansion if cfg['dept'] == 'cyber' else related_v7).parse_detail(cfg, html, url)
    fallback = (cyber_expansion if cfg['dept'] == 'cyber' else related_v7).parse_detail
    try:
        prior = fallback(cfg, html, url)
    except ValueError:
        prior = {}
    for key in ('bio_raw', 'title', 'supervisor', 'phone'):
        if prior.get(key):
            parsed.setdefault(key, prior[key])
    if not parsed.get('research_direction_raw'):
        suggested = prior.get('research_direction_raw') or '、'.join(prior.get('research_directions', []))
        suggested = suggested or research(parsed.get('bio_raw') or '')
        if clean := clean_direction(suggested):
            parsed['research_direction_raw'] = clean
        elif (suggested and TRUNCATED.search(suggested) and cfg.get('_read_source')
              and urlsplit(url).hostname == PORTAL):
            root = urlsplit(url)
            profile = re.escape(root.path.strip('/').split('/')[0])
            links = set()
            for link in BeautifulSoup(html, 'html.parser').select('.Psl-info a[href],.account a[href],.t_grjj_nr a[href]'):
                target = urljoin(url, link['href'])
                parts = urlsplit(target)
                if (link.get_text(strip=True) in {'更多', '更多+', 'More+', '查看更多'}
                        and parts.netloc == root.netloc and parts.scheme == root.scheme and not parts.query and not parts.fragment
                        and re.fullmatch(rf'/{profile}/(?:zh_CN|en)/more/\d+/jsjjgd/index\.htm', parts.path)):
                    links.add(target)
            if len(links) == 1:
                target = next(iter(links))
                try:
                    _, full = cfg['_read_source'](target)
                    described = parse_person(dict(cfg, _expected_name=parsed['name']), full, target)
                except (OSError, ValueError):
                    described = {}
                if direction := described.get('research_direction_raw'):
                    parsed['research_direction_raw'] = direction
                    parsed['_field_sources'] = {'research_direction_raw': target}
    return parsed


def parse_contact(cfg, original):
    if not cfg.get('_read_source'):
        return {}
    url = original['detail_url']
    reader = cfg['_read_source']
    raw, html = reader(url)
    fields = parse_person(dict(cfg, _expected_name=original['name']), html, url)
    result = {'name': original['name'], '_field_sources': {}}
    directory = cfg.get('contact_article_directories', {}).get(original.get('slug', '')[:1])
    if urlsplit(url).hostname == PORTAL:
        def read_source(target):
            return (raw, html) if target == url else reader(target)
        try:
            supplemental = hust_profile.parse_contact(dict(cfg, _read_source=read_source), original)
            if supplemental:
                result = supplemental
        except (OSError, ValueError):
            if not directory and not cfg.get('contact_lab_url') and not any(fields.get(field) for field in ('email', 'homepage')):
                raise
    for field in ('email', 'homepage'):
        if fields.get(field):
            result[field] = fields[field]
            result.setdefault('_field_sources', {})[field] = url
    lab = cfg.get('contact_lab_url')
    old_email_source = original.get('provenance', {}).get('email', {}).get('source')
    if lab and not result.get('email') and (not original.get('email') or old_email_source == lab):
        try:
            _, roster = reader(lab)
        except (OSError, ValueError):
            if not result.get('homepage'):
                raise
        else:
            if email := cyber_lab_email(roster, original['name']):
                result['email'] = email
                result.setdefault('_field_sources', {})['email'] = lab
    if directory and not original.get('email') and not result.get('email'):
        _, index = reader(directory)
        links = set()
        for heading in BeautifulSoup(index, 'html.parser').select('.list li > a[href] > h2'):
            target = urljoin(directory, heading.parent['href'])
            parts = urlsplit(target)
            if (heading.get_text(strip=True) == original['name'] and parts.netloc == DEPARTMENT['aia']
                    and parts.scheme == 'https' and re.fullmatch(r'/info/\d+/\d+\.htm', parts.path)):
                links.add(target)
        if len(links) == 1:
            target = next(iter(links))
            _, article = reader(target)
            if email := parse_person(dict(cfg, _expected_name=original['name']), article, target).get('email'):
                result['email'] = email
                result['_field_sources']['email'] = target
                result['_contact_locator'] = {'email': {'article_url': directory, 'named_person': original['name']}}
    return result

"""Profiles linked from Tongji University's computer science faculty directories."""
import json
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.mentor_recovery import personal_email
from sites import profile_fields


UNIT = '计算机科学与技术学院'
ACADEMY = 'cs.tongji.edu.cn'
FACULTY = 'faculty.tongji.edu.cn'
NAME = re.compile(r'[\u3400-\u9fff·]{2,6}')
TITLE = re.compile(r'(?:(?:讲席|特聘|长聘|准聘|预聘|助理|兼职|客座|高级|副)*(?:教授|研究员|工程师|实验师)|讲师)')
SUPERVISION = (('博导', r'博士(?:研究)?生(?:导师|指导教师)|博导'), ('硕导', r'硕士(?:研究)?生(?:导师|指导教师)|硕导'))
CURRENT_OPENING = re.compile(r'^(?:现任|现为|现就职于|任|同济大学)')
PAST_OR_OTHERS = re.compile(r'曾任|曾为|曾是|原任|历任|退休|学生导师|合作导师|导师为|导师是|师从|团队|(?:非|未|无|不是)(?:博士|硕士|博导|硕导)|资格待定|不再|取消|撤销')
DISPLAY_EMAIL_ID = '_tsites_encryp_tsteacher_tsemail'
EMAIL_LABEL = re.compile(r'(?:本人)?(?:电子邮箱|电子邮件|联系邮箱|邮箱|E-?mail)\s*[:：]\s*(.+)', re.I)
VISIBLE_ADDRESS = re.compile(r'[A-Za-z0-9._%+-]+\s*(?:[@＠]|\(\s*at\s*\)|\s+at\s+)\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}', re.I)
OTHER_SECTIONS = re.compile(r'(?m)^(?:教育经历|教育背景|学习经历|工作经历|相关领域|科研项目|代表性论文|论文)\s*[:：]?\s*$')


def text(node, separator=' '):
    return node.get_text(separator, strip=True) if node else ''


def parse_roster_page(cfg, html, url):
    soup = BeautifulSoup(html, 'html.parser')
    host = urlsplit(url).hostname
    if host == ACADEMY:
        anchors = ((node, text(node.select_one('h4.tit'))) for node in soup.select('a.con[href]:has(h4.tit)'))
        next_anchor = soup.select_one('.p_next a[href]')
    elif host == FACULTY:
        anchors = ((node, text(node.find('p'))) for node in soup.select('a[href]')
                   if [text(p) for p in node.find_all('p', recursive=False)][1:] == [UNIT])
        next_anchor = soup.select_one('a.Next[href]')
    else:
        return [], None
    records = []
    pattern = re.compile(cfg['list']['person_href'])
    for anchor, name in anchors:
        link = urlsplit(urljoin(url, anchor['href']))
        if link.netloc not in (ACADEMY, FACULTY) or link.scheme not in ('http', 'https'):
            continue
        profile = urlunsplit(('https', link.netloc, link.path, '', ''))
        if NAME.fullmatch(name) and anchor.get('title', name).strip() == name and pattern.fullmatch(profile):
            records.append(dict(name=name, url=profile, profile_url=profile, institutes=[], roster_source=url))
    following = urlsplit(urljoin(url, next_anchor['href'])) if next_anchor else None
    if not following or following.scheme != 'https' or following.netloc != host:
        return records, None
    if host == ACADEMY:
        channel = urlsplit(url).path
        # From a numbered page continue within its category directory.
        prefix = channel.rsplit('/', 1)[0] if re.search(r'/\d+\.htm$', channel) else channel.removesuffix('.htm')
        same_category = bool(re.fullmatch(re.escape(prefix) + r'/\d+\.htm', following.path))
    else:
        same_category = (following.path == '/unit_teacherlist.jsp' and
                         parse_qs(following.query).get('id') == ['3542'])
    return records, following.geturl() if same_category else None


def iter_roster(cfg):
    people = {}
    meta = None
    for channel in cfg['list']['channels']:
        url = channel['url']
        visited = set()
        while url and url not in visited and len(visited) < 20:
            visited.add(url)
            html, meta, _ = fetch.fetch_text('GET', url)
            records, following = parse_roster_page(cfg, html, url)
            if not records:
                raise ValueError(f'同济计算机学院教师名单中未找到本人条目：{url}')
            for record in records:
                record['roster_fetched_at'] = meta['fetched_at']
                people.setdefault(record['name'], {}).setdefault(record['url'], record)
            url = following
    # Where the university directory has additional aliases, prefer the exact
    # link published by the department. Defer competing department identities.
    result = []
    for records in people.values():
        choices = list(records.values())
        primary = [record for record in choices if urlsplit(record['roster_source']).hostname == ACADEMY]
        selected = primary or choices
        if len(selected) == 1:
            result.append(selected[0])
    return result, meta


def labelled(rows, label):
    pattern = re.compile(r'(?:' + label + r')\s*[:：]\s*(.+)')
    return next(((match[1].strip(), row) for row in rows if (match := pattern.fullmatch(row))), ('', ''))


def supervision(value):
    if re.search(r'硕博导师|博硕导师|博士[、及和]硕士(?:研究)?生导师|硕士[、及和]博士(?:研究)?生导师', value):
        return '博导、硕导'
    return '、'.join(label for label, pattern in SUPERVISION if re.search(pattern, value))


def public_email_url(html, url):
    """Address of the ordinary public page's email display request, if present."""
    if urlsplit(url).hostname != FACULTY:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    node = soup.select_one(f'.leftside li > span#{DISPLAY_EMAIL_ID}[_tsites_encrypt_field]')
    script = soup.select_one('script[src="/system/resource/tsites/tsitesencrypt.js"]')
    mode = re.search(r'_tsites_com_view_mode_type_\s*=\s*(\d+)', str(soup)) if script else None
    token = text(node)
    if not node or not mode or not re.fullmatch(r'[0-9a-fA-F]{16,1024}', token):
        return None
    if text(node.parent).removesuffix(token).strip() not in ('电子邮箱：', '电子邮箱:'):
        return None
    query = urlencode({'id': DISPLAY_EMAIL_ID, 'content': token, 'mode': mode[1]})
    return f'https://{FACULTY}/system/resource/tsites/tsitesencrypt.jsp?{query}'


def displayed_email(html):
    value = text(BeautifulSoup(html, 'html.parser'))
    try:
        payload = json.loads(value)
    except ValueError:
        pass
    else:
        value = payload.get('content', '') if isinstance(payload, dict) else ''
    return value if isinstance(value, str) and value and personal_email(value) == value else None


def biography_research(bio):
    section = re.search(r'(?m)^(?:研究方向|研究兴趣|研究领域)\s*[:：]?\s*\n', bio)
    if section:
        return OTHER_SECTIONS.split(bio[section.start():], maxsplit=1)[0]
    return OTHER_SECTIONS.split(bio, maxsplit=1)[0]


def parse_detail_evidence(html, url):
    """Return the profile fields, plus the original display lines for evidence."""
    host = urlsplit(url).hostname
    soup = BeautifulSoup(html, 'html.parser')
    if host == ACADEMY:
        header = soup.select_one('.teamnr .txt')
        name = text(header.select_one('h5')) if header else ''
        if not soup.title or text(soup.title) != f'{name}-同济大学{UNIT}':
            return {}, {}
        biography = soup.select_one('.teamtxt .v_news_content')
        research_section = None
    elif host == FACULTY:
        heading = soup.select_one('.leftside .name, .nm h2, .sy-right-1 > h3')
        name = text(heading)
        if not soup.title or f'{name}--' not in text(soup.title):
            return {}, {}
        header = soup.select_one('.leftside')
        sections = {text(h): h.parent for h in soup.select('h2')}
        biography = sections.get('个人简介')
        research_section = sections.get('研究方向') or sections.get('研究领域')
    else:
        return {}, {}
    if not NAME.fullmatch(name):
        return {}, {}

    rows = text(header, '\n').splitlines()
    bio = text(biography, '\n').removeprefix('个人简介\n')
    opening = re.split(r'[。；;\n]', bio, maxsplit=1)[0]
    own_statement = opening.startswith(name) or bool(CURRENT_OPENING.match(opening))
    own_opening = PAST_OR_OTHERS.split(opening, maxsplit=1)[0] if own_statement else ''
    evidence = {}
    out = {'name': name}
    title, quote = labelled(rows, r'职\s*称')
    if not title and host == FACULTY:
        title = next((row for row in rows[1:3] if TITLE.fullmatch(row)), '')
        quote = title
    match = TITLE.search(title or (own_opening if '同济大学' in own_opening else ''))
    if match:
        out['title'] = match[0]
        evidence['title'] = quote or opening
    qualification, quote = labelled(rows, r'导师类型|导师资格')
    if qualification and PAST_OR_OTHERS.search(qualification):
        qualification = quote = ''
    kinds = supervision(qualification or own_opening)
    if kinds:
        out['supervisor'] = kinds
        evidence['supervisor'] = quote or opening
    _, quote = labelled(rows, r'(?:主要)?研究(?:方向|领域|兴趣)')
    section = text(research_section, '\n')
    for source in (quote, section, biography_research(bio)):
        direction = profile_fields.research(source)
        if direction and not profile_fields.direction_is_mixed(direction) and not re.search(r'学位\s*[:：]|学历\s*[:：]|\d{2}/\d{4}', direction):
            out['research_direction_raw'] = direction
            evidence['research_direction_raw'] = next((line for line in source.splitlines() if direction in line), source)
            break
    addresses = {}
    for row in rows:
        match = EMAIL_LABEL.fullmatch(row)
        if match and VISIBLE_ADDRESS.fullmatch(match[1]) and (email := personal_email(match[1])):
            addresses[email.casefold()] = (email, row)
    if len(addresses) == 1:
        out['email'], evidence['email'] = next(iter(addresses.values()))
    if bio:
        out['bio_raw'] = bio
    return out, evidence


def parse_detail(cfg, html, url):
    result, _ = parse_detail_evidence(html, url)
    if not result or (cfg.get('_expected_name') and result.get('name') != cfg['_expected_name']):
        return {}
    if not result.get('email') and (public_url := public_email_url(html, url)):
        reader = cfg.get('_read_source')
        body = reader(public_url)[0] if reader else fetch.fetch_text('GET', public_url)[0]
        if email := displayed_email(body):
            result['email'] = email
    return result

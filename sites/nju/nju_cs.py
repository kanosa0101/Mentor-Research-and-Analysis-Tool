import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Comment

from crawler.mentor_recovery import IdentityConflict, homepage_url, personal_email
from sites.profile_fields import clean_research, direction_is_mixed
from sites.wp import parse_wp_detail, walk_channels


_HOST = 'cs.nju.edu.cn'
_PERSON = re.compile(r'(?:/[0-9a-f]{2})*/c\d+a\d+/page\.htm')
_TITLE = r'(?:院士|博士|硕士|博导|硕导|博士生导师|硕士生导师|(?:副|助理)?教授|(?:高级)?(?:工程师|讲师)|(?:副|助理)?研究员)'
_RANK = re.compile(rf'\s*[（(]{_TITLE}(?:[、，,/]{_TITLE})*[）)]$')
_NUMBER = r'(?:[一二三四五六七八九十]+|\d+)\s*[、．.]\s*'
_LABEL = r'(?:具体|主要)?(?:研究兴趣与方向|研究方向|研究领域|研究兴趣|科研方向)'
_ASSIGN = r'(?:[:：]|(?:主要)?(?:包括|包含|涉及|涵盖|集中于|集中在|聚焦于|聚焦在|为|是|有)\s*[:：]?)'
_HEADING = re.compile(rf'^(?P<number>{_NUMBER})?(?P<label>{_LABEL})(?:\s*{_ASSIGN}\s*(?P<value>.+))?\s*[:：]?$')
_DIRECT = re.compile(rf'^(?:{_LABEL}|主要研究内容)\s*{_ASSIGN}\s*(.+)$')
_WORK = re.compile(r'^(?:(?:主要|长期|一直|多年来一直|\d{4}\s*年开始)?从事|长期专注于)\s*'
                   r'(.+?)\s*(?:等(?:方向|方面|领域)的|方面的|的|领域|方面)?(?:学术)?研究(?:工作)?'
                   r'(?:[，,]\s*((?:包括|(?:近期|现|目前)聚焦)[^。；]+))?$')
_SECTION_END = re.compile(
    r'^(?:' + _NUMBER + r')?(?:[【\[])?(?:教育背景|教育经历|工作经历|个人经历|教学工作|课程|主讲课程|'
    r'研究内容|科研项目|科研工作|研究团队|学术兼职|代表性?成果|代表性?论文|主要论文|发表论文|'
    r'论文|专利|获奖|荣誉|招生|招聘|联系方式|电话|个人主页|电子邮件|邮箱|Publications?)(?:[】\]:：\s]|$)', re.I)
_OTHER_SCOPE = re.compile(
    r'^(?:(?:以下|下文|后文).{0,45}(?:合作者|合作导师|其他教师|其他导师|团队|课题组|实验室|研究组|研究院|教授|同学)|'
    r'(?:附|摘录)\s*.*(?:研究院|研究组|团队|实验室|课题组)|'
    r'(?:本|该)(?:研究组|团队|实验室|课题组|研究院)|'
    r'(?:研究组|团队|实验室|课题组|研究院)(?:介绍|简介))')
_AFTER_TOPIC = re.compile(
    r'[,，;；]\s*(?=(?:(?:近年来|近[几五十\d]+年|近年|先后|已|共|曾|累计|长期)\s*)*'
    r'(?:主持|承担|发表|出版|获得|获|担任|入选|研制|取得|笔者|招生|教授课程))|'
    r'[,，;；]\s*(?=在[^，。；;]{0,85}(?:发表|获奖)|在[^。；;]{0,110}方面取得|'
    r'在[^。；;]{0,110}(?:期刊|会议)[^。；;]{0,60}发表|以[^。；;]{0,110}为理念)')
_INLINE = re.compile(rf'[，,]\s*(?:{_LABEL}|主要研究内容)\s*{_ASSIGN}\s*(.+)$')
_DECLARED_WORK = re.compile(r'^(?:主要研究|所研究工作主要涉及)\s*(.{2,})$')
_CONTACT = re.compile(
    r'(?P<label>个人(?:主页(?:网址)?|网站)|教师主页|学术主页|电子邮件|电子邮箱|联系邮箱|邮箱|E-?mail)\s*[:：]', re.I)
_CONTACT_END = re.compile(r'\s*(?:电话|手\s*机|办公地点|办公室|通讯地址|Wechat|微信)\s*[:：]', re.I)
_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def iter_roster(cfg):
    return walk_channels(cfg, cfg["list"]["channels"])


def _path(url):
    parts = urlsplit(url)
    if (parts.scheme == 'https' and parts.netloc == _HOST and not parts.query and not parts.fragment
            and _PERSON.fullmatch(parts.path)):
        return parts.path
    return None


def _name(text):
    return ''.join(_RANK.sub('', text).split())


def _person_page(html, url, expected=None, original=None):
    path = _path(url)
    if not path or (original and _path(original) != path):
        raise IdentityConflict('南大详情与已登记本人路径不符，保留原档')
    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.select('div.article > h1.arti_title')
    if len(cards) != 1 or not (name := _name(cards[0].get_text(' ', strip=True))):
        raise ValueError('未解析南大本人页唯一姓名栏，保留原档')
    if expected and name != _name(expected):
        raise IdentityConflict('南大详情明确姓名与原记录不符，保留原档')
    canonical = soup.select('link[rel=canonical][href]')
    if canonical and (len(canonical) != 1 or _path(urljoin(url, canonical[0]['href'])) != path):
        raise IdentityConflict('南大详情自链接与已登记本人路径不符，保留原档')
    box = cards[0].parent.select('.wp_articlecontent')
    if len(box) != 1:
        return expected or name, None
    for node in box[0].select('script, style, [hidden], [style*="display:none"], [style*="display: none"]'):
        node.decompose()
    return expected or name, box[0]


def _rows(box):
    # Keep paragraph boundaries without fragmenting words from inline emphasis.
    blocks = {'p', 'div', 'li', 'td', 'h2', 'h3', 'h4', 'br', 'ul', 'ol'}

    def parts(node):
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if child.name in blocks:
                yield '\n'
            if child.name:
                yield from parts(child)
            else:
                yield str(child).replace('\n', ' ')
            if child.name in blocks:
                yield '\n'

    for line in ''.join(parts(box)).splitlines():
        value = re.sub(r'\s+', ' ', line).strip()
        if value:
            yield value


def _trim_topic(text):
    text = _AFTER_TOPIC.split(text, maxsplit=1)[0]
    topic = clean_research(text)
    return topic if topic and not direction_is_mixed(topic) else None


def _heading_topics(lines, index, heading):
    value = heading['value'] or ''
    parts = re.split(r'[。！？]', value, maxsplit=1)[:1] if value else []
    if value:
        return _trim_topic(parts[0])
    for line in lines[index + 1:]:
        if (_HEADING.fullmatch(line) or _SECTION_END.match(line) or _OTHER_SCOPE.match(line)
                or heading['number'] and re.match(_NUMBER, line) or direction_is_mixed(line)):
            break
        if not (topic := _trim_topic(line)):
            break
        parts.append(topic)
        if line.endswith(('。', '.', '！', '!', '？', '?')):
            break
    return '；'.join(parts) or None


def _directions(box, name):
    if box is None:
        return None
    lines = list(_rows(box))
    headings, statements = set(), set()
    in_bio = True
    for index, line in enumerate(lines):
        if _OTHER_SCOPE.match(line):
            break
        if heading := _HEADING.fullmatch(line):
            if value := _heading_topics(lines, index, heading):
                headings.add(value)
            continue
        if _SECTION_END.match(line):
            in_bio = False
        elif re.fullmatch(r'[【\[]?个人(?:简介|简历)[】\]:：]?', line):
            in_bio = True
        if not in_bio:
            continue
        for sentence in re.split(r'[。！？]', line):
            sentence = sentence.strip()
            if _OTHER_SCOPE.match(sentence):
                break
            inline = _INLINE.search(sentence) if sentence.startswith((name, '本人')) or _WORK.match(
                sentence.partition('，')[0]) else None
            sentence = re.sub(r'^(?:本人|其|他|她|' + re.escape(name)
                              + r'(?:(?:教授|博士|老师|研究员))?)\s*(?:的)?\s*', '', sentence)
            sentence = re.sub(r'^(?:目前|现阶段|近年来)\s*', '', sentence)
            direct = _DIRECT.match(sentence)
            value = direct[1] if direct else inline[1] if inline else None
            if not value and (work := _WORK.fullmatch(_AFTER_TOPIC.split(sentence, maxsplit=1)[0])):
                value = '，'.join(part for part in work.groups() if part)
            if not value and (work := _DECLARED_WORK.fullmatch(sentence)):
                value = work[1]
            if value and (topic := _trim_topic(value)):
                statements.add(topic)
    values = headings or statements
    return next(iter(values)) if len(values) == 1 else None


def parse_detail(cfg, html, url):
    original = cfg.get('_original_profile') or {}
    name, box = _person_page(html, url, cfg.get('_expected_name') or original.get('name'), original.get('detail_url'))
    fields = {'name': name}
    value = _directions(box, name)
    if value and original.get('research_direction_raw') in (None, '', value):
        fields.update(research_direction_raw=value, research_directions=[value])
    # Let normal maintenance recheck an unchanged biography at its recorded
    # source. The older CLI can infer eligibility from a returned biography.
    provenance = (original.get('provenance') or {}).get('bio_raw') or {}
    existing_bio = original.get('bio_raw')
    if (box is not None and cfg.get('_read_source') and existing_bio and provenance.get('origin') == 'crawled'
            and provenance.get('source') == url and parse_wp_detail(cfg, html, url).get('bio_raw') == existing_bio):
        fields['bio_raw'] = existing_bio
    return fields


def _contact_values(box, url):
    pages, emails, issues = set(), set(), set()
    if box is None:
        return None, None
    foreign_scope = False
    for node in box.select('p, div, li, td'):
        if node.select_one('p, div, li, td'):
            continue
        line = ' '.join(node.stripped_strings)
        if _OTHER_SCOPE.match(line):
            foreign_scope = True
        contact_bar = ('other' in node.get('class', ()) and
                       node.find_previous_sibling('div', class_='content') is not None)
        if foreign_scope and not contact_bar:
            continue
        labels = list(_CONTACT.finditer(line))
        if not labels or not re.fullmatch(r'(?:(?:电话|办公电话)\s*[:：]\s*[\d\s()（）+-]+)?\s*', line[:labels[0].start()]):
            continue
        for index, label in enumerate(labels):
            end = labels[index + 1].start() if index + 1 < len(labels) else len(line)
            value = _CONTACT_END.split(line[label.end():end], maxsplit=1)[0].strip(' ，,；;。')
            if '主页' in label['label'] or '网站' in label['label']:
                hrefs = {urljoin(url, a['href']) for a in node.select('a[href]')
                         if value and a.get_text(' ', strip=True) == value}
                if len(hrefs) > 1:
                    issues.add('homepage')
                    continue
                # Prefer the actual labelled link; do not upgrade a literal HTTP address.
                target = next(iter(hrefs), homepage_url(value))
                if not target:
                    continue
                parts = urlsplit(target)
                shown = urlsplit(value) if homepage_url(value) else None
                if shown and (shown.netloc, shown.path.rstrip('/')) != (parts.netloc, parts.path.rstrip('/')):
                    issues.add('homepage')
                    continue
                if (parts.scheme == 'https' and parts.netloc == _HOST and not parts.query and not parts.fragment
                        and not _path(target)):
                    pages.add(target)
            else:
                value = re.sub(r'\s*@\s*', '@', value)
                email = personal_email(value) if _EMAIL.fullmatch(value) else None
                targets = {a['href'][7:] for a in node.select('a[href^="mailto:"]')}
                if value and (not email or targets and targets != {email}):
                    issues.add('email')
                if email:
                    emails.add(email)
    return (next(iter(pages)) if len(pages) == 1 and 'homepage' not in issues else None,
            next(iter(emails)) if len(emails) == 1 and 'email' not in issues else None)


def parse_contact(cfg, original):
    url = original['detail_url']
    if not cfg.get('_read_source') or not _path(url):
        return {}
    _, html = cfg['_read_source'](url)
    name, box = _person_page(html, url, original['name'], url)
    page, email = _contact_values(box, url)
    values = {}
    if page and not original.get('homepage'):
        values['homepage'] = page
    previous = cfg.get('_previous_email') or original.get('email')
    if email and (not previous or previous.casefold() == email.casefold()):
        values['email'] = previous or email
    return {**values, '_verified_roster_name': name, '_field_sources': dict.fromkeys(values, url)} if values else {}

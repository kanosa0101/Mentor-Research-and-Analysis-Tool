import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler.email_util import VALID, normalize_email
from crawler.mentor_recovery import canonical, homepage_url, personal_email
from sites.profile_fields import clean_research, direction_is_mixed
from sites.ucas import cas_lists


INSTITUTE = '中国科学院自动化研究所'
PERSON_PATH = re.compile(r'/rcdw/(?:yjy|fyjy)/\d{6}/t20\d{6}_\d+\.html')
DIRECTION = re.compile(r'^\s*【?\s*(?:本人)?(?:主要)?研究(?:方向|领域|兴趣)\s*】?(?:\s*(?:包括|为|是|[:：])\s*|\s+|$)(.*)$')
SECTION_BOUNDARY = re.compile(
    r'\s*(?:(?:研究方向|研究领域|教育背景|教育经历|工作经历|代表论著|代表性论文|发表论文|论文发表|'
    r'承担科研项目情况|科研项目|主要项目|课程|教授课程|招生信息|招生要求|主要荣誉|联系方式)\s*(?:[:：]|$)|'
    r'招生[^。；]{0,24}(?:访问|联系|主页)|(?:个人|教师|学术)(?:主页|网站)\s*[:：]|https?://)'
)
HOME_LABEL = r'(?:个人|教师|学术)(?:主页|网站)'
HOME_PREFIX = re.compile(r'(?:^|[。；])\s*(?:(?:招生信息请访问|详情请见|更多内容见|详见)\s*)?'
                         + HOME_LABEL + r'\s*[:：]?\s*$')
OTHER_CONTACT = re.compile(r'团队|学生|秘书|助理|办公室|联系人|教务|合作导师')
OTHER_SCOPE = re.compile(r'^(?:(?:以下(?:内容|资料)?|下文|下述|下面(?:内容)?)\s*(?:为|是|介绍|关于)\s*'
                         r'[^。]{0,36}(?:合作者|合作导师|其他导师|学生|课题组|团队|实验室)|'
                         r'(?:课题组|团队|实验室)(?:简介|介绍|研究方向)\s*[:：]?)')
NUMBERED_TOPIC = re.compile(r'^\s*(?:\[(\d+)\]|[（(](\d+)[）)]|(\d+)[.、．])\s*[^\d]')
BULLET_TOPIC = re.compile(r'^[·•●]\s*\S')
TEAM_DIRECTION = re.compile(r'(?:^|[。；])\s*[^，。；]{0,14}(?:团队|课题组)\s*(?:聚焦|主要从事|致力于)')
AFFILIATION = re.compile(r'^[^，,、；;。]+(?:工程中心|实验室|研究中心|研究所)$')
PROJECT_BUDGET = re.compile(r'[（(][^）)]+(?:经费|获资助)[^）)]*[）)]')
PAST_OUTCOME = re.compile(r'[。；]\s*(?:构建了|完成了|建成了|研制了|成果发表于)')


def iter_roster(cfg):
    return cas_lists.walk_and_collect(cfg, cfg['list']['urls'])


def _text(node):
    return node.get_text(' ', strip=True) if node else ''


def _named_rows(table, name):
    cells = [tr.find_all(['th', 'td'], recursive=False) for tr in table.find_all('tr')
             if tr.find_parent('table') is table]
    pairs = [(_text(label).rstrip('：:'), value) for row in cells for label, value in zip(row, row[1:])]
    return pairs if {_text(value) for label, value in pairs if label == '姓名'} == {name} else []


def _direction(value):
    # The topic text ends where the resume switches to another identifiable field.
    team = TEAM_DIRECTION.search(value)
    if (team and not re.match(r'\s*本人及(?:领导|带领)的团队', team[0].lstrip('。；')) or
            AFFILIATION.fullmatch(value)):
        return None
    value = PROJECT_BUDGET.sub('', value)
    boundaries = [marker.start() for pattern in (SECTION_BOUNDARY, PAST_OUTCOME) if (marker := pattern.search(value))]
    if boundaries:
        value = value[:min(boundaries)]
    value = clean_research(value)
    return value if value and not direction_is_mixed(value) else None


def _resume_directions(content):
    own_scope = True
    for p in content.find_all('p'):
        if p.find_parent('table'):
            continue
        text = _text(p)
        if OTHER_SCOPE.match(text):
            own_scope = False
            continue
        if not (label := DIRECTION.fullmatch(text)):
            continue
        if text.lstrip('【 ').startswith('本人'):
            own_scope = True
        if not own_scope:
            continue
        value = label[1].strip()
        if not value:
            parts = []
            bullets = False
            for sibling in p.find_next_siblings():
                if sibling.name not in ('p', 'div', 'ul', 'ol'):
                    break
                value = _text(sibling)
                if not value:
                    continue
                numbered = NUMBERED_TOPIC.match(value)
                number = int(next(n for n in numbered.groups() if n)) if numbered else None
                if parts:
                    if not (BULLET_TOPIC.match(value) if bullets else number == len(parts) + 1):
                        break
                else:
                    bullets = bool(BULLET_TOPIC.match(value))
                if not (part := _direction(value)):
                    break
                parts.append(part)
                if sibling.name != 'p' or (not bullets and number is None):
                    break
            value = '；'.join(parts)
        if parsed := _direction(value):
            yield parsed


def _labelled_homepages(box, url, original):
    registered = {canonical(url), *(canonical(original[k]) for k in ('detail_url', 'profile_url') if original.get(k))}
    for a in box.select('.gunius-list .gunitem a[href], .gunius-info li a[href]'):
        label = _text(a)
        row = a.find_parent(['p', 'li', 'td']) or a.parent
        caption = _text(row)
        before, found, after = caption.rpartition(label) if label else ('', '', '')
        if OTHER_CONTACT.search(before.rsplit('。', 1)[-1]):
            continue
        if not (re.fullmatch(HOME_LABEL, label) or (found and HOME_PREFIX.search(before)) or
                (found and not before and re.fullmatch(r'\s*[（(]' + HOME_LABEL + r'[）)]', after))):
            continue
        href = homepage_url(urljoin(url, a['href']))
        if href and canonical(href) not in registered:
            yield href


def _direct_email(value):
    value = value.strip()
    return personal_email(value) if VALID.fullmatch(value) else None


def parse_detail(cfg, html, url):
    target = urlsplit(url)
    if target.scheme != 'https' or target.netloc != 'ia.cas.cn' or not PERSON_PATH.fullmatch(target.path):
        return {}
    soup = BeautifulSoup(html, 'html.parser')
    box = soup.select_one('.gunius-detail')
    if box is None:
        return {}
    cards = box.select('.gunius-info .name')
    if len(cards) != 1:
        return {}
    name = _text(cards[0]).split('/')[0].strip()
    if not name or _text(soup.title) != f'{name}----{INSTITUTE}' or cfg.get('_expected_name', name) != name:
        return {}

    parsed = cas_lists.parse_generic_detail(cfg, html, url)
    for field in ('research_direction_raw', 'email', 'homepage'):
        parsed.pop(field, None)
    directions, emails = set(), set()
    for row in box.select('.gunius-info li'):
        match = re.fullmatch(r'电子(?:邮件|邮箱)\s*[:：]\s*(.+)', _text(row))
        if match and (email := _direct_email(match[1])):
            emails.add(email)
    for section in box.select('.gunius-list'):
        heading = _text(section.select_one('h3'))
        content = section.select_one('.gunitem')
        if not content:
            continue
        if heading in ('研究方向', '研究领域'):
            if value := _direction(_text(content)):
                directions.add(value)
        elif heading in ('个人简历', '个人简介'):
            directions.update(_resume_directions(content))
            for table in content.find_all('table'):
                for label, value in _named_rows(table, name):
                    if label in ('研究方向', '研究领域') and (direction := _direction(_text(value))):
                        directions.add(direction)
                    if label in ('联系方式', '邮箱', '电子邮件', '电子邮箱') and (email := _direct_email(_text(value))):
                        emails.add(email)
    homepages = set(_labelled_homepages(box, url, cfg.get('_original_profile') or {}))
    for field, values in (('research_direction_raw', directions), ('email', emails), ('_declared_homepage', homepages)):
        if len(values) == 1:
            parsed[field] = next(iter(values))
    original = cfg.get('_original_profile') or {}
    if original.get('email') and normalize_email(original['email']) != parsed.get('email'):
        parsed.pop('email', None)
    return parsed


def parse_contact(cfg, original):
    """Give the field task the named contact and declared homepage candidates."""
    url = original['detail_url']
    _, html = cfg['_read_source'](url)
    parsed = parse_detail(dict(cfg, _expected_name=original['name'], _original_profile=original), html, url)
    email = parsed.get('email')
    previous = cfg.get('_previous_email')
    values = {}
    if email and (not previous or previous.casefold() == email.casefold()):
        values['email'] = previous or email
    if parsed.get('_declared_homepage'):
        values['homepage'] = parsed['_declared_homepage']
    if not values:
        return {}
    return {**values, '_verified_roster_name': parsed['name'], '_field_sources': {field: url for field in values}}

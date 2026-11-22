"""中国人民大学高瓴人工智能学院的具名名册与本人页。"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.mentor_recovery import personal_email
from crawler.title_util import normalize_title
from sites.profile_fields import clean_research, qualification


_COLLEGE = '中国人民大学高瓴人工智能学院'
_PERSON = re.compile(r'https://ai\.ruc\.edu\.cn/szdw/zrjs/[a-z0-9]+/index\.htm')
_NAME = re.compile(r'[\u4e00-\u9fff·]{2,5}')
_MAIL_LABEL = re.compile(r'^(?:电子邮箱|电子邮件|邮箱|E-?mail)\s*[:：]\s*(.*)', re.I)
_LOCAL = r'[A-Za-z0-9._%+\-]+'
_DOMAIN = r'[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
_ADDRESS = re.compile(rf'({_LOCAL})\s*(?:@|\(\s*@\s*\)|\[\s*(?:at|@)\s*\]|\s+at\s+)\s*({_DOMAIN})', re.I)
_ADDRESS_CHOICES = re.compile(rf'({_LOCAL})\s+at\s+\{{({_DOMAIN}(?:\s*,\s*{_DOMAIN})+)\}}', re.I)
_ADDRESS_SEPARATORS = re.compile(r'[\s,，;；、/]*')
_SHARED = {'ai@ruc.edu.cn', 'gsai@ruc.edu.cn'}
_TITLE_PREFIX = re.compile(r'^(?:长聘|预聘|准聘|特聘|讲席)')
_SECTION_END = re.compile(r'^(?:一些链接|这里附上)')
_SECTION_NOTE = re.compile(r'^(?:更多|详见|推荐联系|["“].+---|'
                           r'.{0,18}(?:报道|网站|公众号|主页|学术|报告链接|资源汇总|内容整理)\s*[:：])')
_SECTION_TAIL = re.compile(r'[。；，,]\s*(?:详见|部分研究介绍|更多详细介绍)')
_SECTION_LIST_INTRO = re.compile(r'[。；，,]\s*(?:具体聚焦以下几个方面|具体研究课题包括)[:：]$')
_SECTION_PREFIX = re.compile(r'^[-●\s]*(?:[（(]?\d+[）).、]\s*)?')


def roster_entries(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    if not soup.title or soup.title.get_text(strip=True) != '专任教师_' + _COLLEGE:
        raise ValueError('人大高瓴专任教师名册标题未确认')
    records = {}
    seen_urls = set()
    for link in soup.select('.teacherBox .teaItem .name a[href]'):
        name = link.get_text(strip=True)
        target = urljoin(url, link['href'])
        if not _NAME.fullmatch(name) or not _PERSON.fullmatch(target):
            continue
        if name in records or target in seen_urls:
            raise ValueError('人大高瓴专任教师名册存在重复身份')
        records[name] = target
        seen_urls.add(target)
    if not records:
        raise ValueError('人大高瓴专任教师名册为空')
    return records


def iter_roster(cfg):
    url = cfg['list']['urls'][0]
    html, meta, _ = fetch.fetch_text('GET', url)
    rows = roster_entries(html, url)
    return [dict(name=name, url=target) for name, target in rows.items()], meta


def _named_profile(html, url, expected):
    if not _PERSON.fullmatch(url):
        raise ValueError('不是人大高瓴现行专任教师本人页')
    soup = BeautifulSoup(html, 'html.parser')
    boxes = soup.select('.teaDetailBox')
    heading = boxes[0].select_one('.teaBaseCon > .name > h2') if len(boxes) == 1 else None
    name = ''.join(part.strip() for part in heading.find_all(string=True, recursive=False)) if heading else ''
    if (not _NAME.fullmatch(name) or not soup.title or soup.title.get_text(strip=True) != name + '_' + _COLLEGE
            or expected and name != expected):
        raise ValueError('人大高瓴本人页姓名与登记不一致或标题未确认')
    return name, boxes[0], heading


def _mailboxes(box):
    values = set()
    for node in box.select('.teaBaseCon > .lxfs > p'):
        label = _MAIL_LABEL.fullmatch(node.get_text(' ', strip=True))
        if not label:
            continue
        text = label[1]
        if choices := _ADDRESS_CHOICES.fullmatch(text):
            # The page prints the same local part and multiple complete domains.
            fields = [(choices[1], domain.strip()) for domain in choices[2].split(',')]
        else:
            if not _ADDRESS_SEPARATORS.fullmatch(_ADDRESS.sub('', text)):
                continue
            fields = _ADDRESS.findall(text)
        values.update(value.casefold() for local, domain in fields
                      if (value := personal_email(local + '@' + domain)) and value.casefold() not in _SHARED)
    return values


def _contact_value(box, previous):
    addresses = _mailboxes(box)
    if previous:
        return previous if previous.casefold() in addresses else None
    if len(addresses) == 1:
        return next(iter(addresses))
    return None


def _research(box):
    labels = [item for item in box.select('.teaContent > h2')
              if item.get_text(strip=True) in ('研究方向', '研究领域', '研究兴趣')]
    if len(labels) != 1:
        return None
    parts = []
    for node in labels[0].find_next_siblings():
        if node.name == 'h2':
            break
        if _SECTION_END.match(_SECTION_PREFIX.sub('', node.get_text(' ', strip=True))):
            break
        items = node.find_all('li', recursive=False) if node.name in ('ul', 'ol') else [node]
        for item in items:
            text = _SECTION_PREFIX.sub('', item.get_text(' ', strip=True))
            text = _SECTION_LIST_INTRO.sub('', _SECTION_TAIL.split(text, maxsplit=1)[0])
            if (_SECTION_NOTE.match(text) or text.endswith(('包括：', '以下几个方面：', '包括但不限于：'))
                    or text == '具体方向：'):
                continue
            if value := clean_research(text):
                parts.append(value)
    return '；'.join(parts) or None


def _supervisor(box, name):
    summary = box.select_one('.teaBaseCon > .summary')
    text = summary.get_text(' ', strip=True) if summary else ''
    current = re.split(r'[。；;]', text, maxsplit=1)[0]
    if not re.match(rf'^(?:{re.escape(name)}(?:博士)?[，,、]|中国人民大学(?:高瓴人工智能学院|[，,、])'
                    r'|长聘(?:副)?教授[，,、])', current) or re.search(
                        r'师从|曾任|曾为|导师为|导师是|同事|合作|前任|原任|退休|荣休', current):
        return None
    roles = [part.strip() for part in re.split(r'[，,、]', current)
             if re.fullmatch(r'(?:现任)?(?:博士(?:研究)?生导师|硕士(?:研究)?生导师|博导|硕导)', part.strip())]
    return qualification('，'.join([name, *roles]), name)


def parse_detail(cfg, html, url):
    original = cfg.get('_original_profile') or {}
    name, box, heading = _named_profile(html, url, cfg.get('_expected_name') or original.get('name'))
    if original.get('detail_url') and original['detail_url'] != url:
        reader = cfg.get('_read_source')
        if not reader:
            raise ValueError('人大高瓴替代本人页缺少现行名册佐证')
        roster_url = cfg['list']['urls'][0]
        if roster_entries(reader(roster_url)[1], roster_url).get(name) != url:
            raise ValueError('人大高瓴现行名册未唯一链接该本人页')
    result = {'name': name}
    rank = heading.find('span')
    title = normalize_title(rank.get_text(strip=True))[0] if rank else None
    previous_title = original.get('title')
    if title and previous_title and _TITLE_PREFIX.sub('', title) == _TITLE_PREFIX.sub('', previous_title):
        title = previous_title
    claimed = {'title': title, 'research_direction_raw': _research(box), 'supervisor': _supervisor(box, name)}
    provenance = original.get('provenance') or {}
    for field, value in claimed.items():
        if value and (provenance.get(field) or {}).get('origin') != 'manual' and original.get(field) in (None, '', value):
            result[field] = value
    if email := _contact_value(box, original.get('email')):
        result['email'] = email
    return result


def parse_contact(cfg, person):
    url = person['detail_url']
    reader = cfg.get('_read_source')
    if (not reader or not _PERSON.fullmatch(url) or
            ((person.get('provenance') or {}).get('email') or {}).get('origin') == 'manual'):
        return {}
    _, html = reader(url)
    name, box, _ = _named_profile(html, url, person['name'])
    previous = cfg.get('_previous_email') or person.get('email')
    if value := _contact_value(box, previous):
        return {'_verified_roster_name': name, 'email': value, '_field_sources': {'email': url}}
    return {}

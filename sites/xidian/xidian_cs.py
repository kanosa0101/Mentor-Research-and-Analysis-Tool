"""Xidian computer-science roster and bound public teacher profiles."""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.mentor_recovery import IdentityConflict, homepage_url, personal_email, same_scope
from crawler.title_util import normalize_title
from sites import tsites
from sites.profile_fields import clean_research, direction_is_mixed


_FACULTY = 'faculty.xidian.edu.cn'
_WEB = 'web.xidian.edu.cn'
_NAME = re.compile(r'[\u4e00-\u9fff·]{2,8}')
_FACULTY_PATH = re.compile(r'/([A-Za-z0-9_-]+)(?:/(?:zh_CN|en)(?:/index(?:\.htm|/\d+/list(?:/index\.htm)?))?)?/?')
_WEB_PATH = re.compile(r'/([A-Za-z0-9_-]+)(?:/index\.html?)?/?')
_FACULTY_NAME = '.t_photo > span, .photo > p.name, .dianzan h3'
_FACULTY_HOME = re.compile(r'首页|主页|Home', re.I)
_RANK = r'(?:教授|副教授|助理教授|研究员|副研究员|讲师|博士生导师|硕士生导师|工程师|博导|硕导)'
_NAME_RECORD = re.compile(rf'({_NAME.pattern})(?:\s+(?:(?:职称|职位)\s*[:：]\s*)?{_RANK}(?:[\s/、]+{_RANK})*)?')
_EMAIL_LABEL = re.compile(r'^(?:电子邮箱|电子邮件|邮箱|E\s*-?\s*mail|联系方式)\s*[:：]\s*(.*)$', re.I)
_ADDRESS = re.compile(
    r'[A-Za-z0-9._%+-]+(?:\s*@\s*|\s*(?:\[AT\]|\(AT\))\s*|\s+AT\s+)'
    r'[A-Za-z0-9-]+(?:(?:\.|\s+\(DOT\)\s+)[A-Za-z0-9-]+)*'
    r'(?:\.|\s+\(DOT\)\s+)[A-Za-z]{2,}', re.I)
_HOME_LABEL = re.compile(r'^(?:个人主页|个人网站|学术主页|教师主页)(?:\s*[:：]\s*(.*))?$')
_PLACEHOLDER = re.compile(r'^(?:暂无(?:内容)?|未填写|待补充|无|研究方向|Research Focus|The Research Direction|/)$', re.I)
_TAB_PREFIX = '研究方向、Research Focus、社会兼职、Social Affiliations、'
_ORDERED_PREFIX = '研究方向、/、The Research Direction、'
_SECTION_BOUNDARY = re.compile(r'^(?:社会兼职|学术兼职|科研项目|承担项目|代表性论文|代表性成果|联系方式|招生信息|教学工作|课程教学)\s*[:：]?')
_TEAM_ACTIVITY = re.compile(r'^(?:(?:目前|现阶段)\s*)?也?(?:跟随|协助|参与)(?:课题组|团队|导师|实验室)')
_NON_CONTACT_FIELDS = ('title', 'supervisor', 'subjects', 'photo_url', 'phone', 'office_address', 'bio_raw')


def _text(node):
    return ' '.join(node.stripped_strings) if node else ''


def _profile_key(url):
    target = urlsplit(url)
    if target.scheme not in ('http', 'https') or target.query or target.fragment:
        return None
    pattern = {_FACULTY:_FACULTY_PATH, _WEB:_WEB_PATH}.get(target.netloc)
    match = pattern.fullmatch(target.path) if pattern else None
    return (target.netloc, match[1]) if match else None


def iter_roster(cfg):
    people = {}
    for roster in cfg['list']['urls']:
        html, meta, _ = fetch.fetch_text('GET', roster)
        soup = BeautifulSoup(html, 'html.parser')
        for anchor in soup.select('#vsb_content_2 table.yjsds_table td a[href]'):
            name = ''.join(_text(anchor).split())
            title = ''.join(anchor.get('title', '').split())
            url = urljoin(roster, anchor['href'])
            if _NAME.fullmatch(name) and (not title or title == name) and _profile_key(url):
                people.setdefault(name, set()).add(url)
    if not people:
        raise ValueError('西电计算机学院正式名录未解析出具名导师链接')
    records = []
    for name, urls in people.items():
        if len({_profile_key(url) for url in urls}) == 1:
            chosen = min(urls, key=lambda url: (urlsplit(url).scheme != 'https', url))
            records.append({'name':name, 'url':chosen})
    return records, meta


def _person_page(html, url, expected, registered):
    key = _profile_key(url)
    if not key or registered and key != _profile_key(registered):
        raise IdentityConflict('西电当前详情离开原登记本人路径')
    target = urlsplit(url)
    if key[0] == _FACULTY and target.scheme == 'http' and target.path.rstrip('/') == '/' + key[1]:
        raise ValueError('西电 faculty 的旧 HTTP 短地址缺少可持续安全入口，保留原档')
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select('script, style, [hidden], [style*="display:none"], [style*="display: none"]'):
        node.decompose()
    title = _text(soup.title)
    if key[0] == _FACULTY:
        names = {text for node in soup.select(_FACULTY_NAME) if _NAME.fullmatch(text := _text(node))}
        anchors = [anchor for anchor in soup.select('a[href]') if _FACULTY_HOME.fullmatch(_text(anchor))
                   and not anchor['href'].startswith('#')]
        match = re.match(r'^西安电子科技大学主页平台管理系统\s+(\S+)\s+', title)
    else:
        anchors = soup.select('#top li:first-child a[href]')
        names = {match[1] for anchor in anchors if (match := re.fullmatch(r'(.+)的主页\s*[:：]', _text(anchor)))}
        for node in soup.select('#n0 > p'):
            if label := re.fullmatch(r'姓名\s*[:：]\s*(.+)', _text(node)):
                named = _NAME_RECORD.fullmatch(label[1])
                names.add(named[1] if named else label[1])
        match = re.fullmatch(r'(.+?)\s*\|\s*[^|]+\|\s*西安电子科技大学个人主页', title)
    keys = {_profile_key(urljoin(url, anchor['href'])) for anchor in anchors}
    if names and (len(names) != 1 or (expected and names != {expected}) or (match and names != {match[1]})):
        raise IdentityConflict('西电本人页的可见姓名与登记不一致')
    if keys and keys != {key}:
        raise IdentityConflict('西电本人页自链接与登记路径不一致')
    if not match or names != {match[1]} or keys != {key}:
        raise ValueError('西电本人页缺独立姓名栏或自链接，保留原档')
    return match[1], soup


def _parts(pane):
    blocks = pane.select('li, p')
    leaves = [node for node in blocks if not node.select_one('li, p')]
    lines = [_text(node) for node in leaves] if leaves else list(pane.stripped_strings)
    return [line for line in lines if line]


def _direction_panes(soup):
    for box in soup.select('.slideTxtBox2'):
        labels = [_text(node) for node in box.select(':scope > .hd > ul > li')]
        panels = box.select(':scope > .bd > ul')
        if (labels == ['研究方向 Research Focus', '社会兼职 Social Affiliations'] and len(panels) == 2
                and 'shjz-list' in panels[1].get('class', [])):
            yield panels[0], True
    for head in soup.select('.rightconside1 > h2, section.container02 .con > h2'):
        if _text(head) != '研究方向':
            continue
        short = 'rightconside1' in head.parent.get('class', [])
        pane = (head if short else head.parent).find_next_sibling()
        expected = 'rightfont' if short else 'pro-content'
        if pane is not None and pane.name == 'div' and expected in pane.get('class', []):
            yield pane, False
    for head in soup.select('.mo > .drag > #t1'):
        pane = head.parent.find_next_sibling()
        if _text(head) == '主要研究方向' and pane is not None and pane.name == 'div' and pane.get('id') == 'n1':
            yield pane, False


def _direction(soup):
    offered = set()
    for pane, tab in _direction_panes(soup):
        parts = _parts(pane)
        if not parts or any(_PLACEHOLDER.fullmatch(line) or _SECTION_BOUNDARY.match(line) or _TEAM_ACTIVITY.match(line)
                            or direction_is_mixed(line) for line in parts):
            continue
        value = '、'.join(parts)
        if len(value) <= 650 and not re.search(r'https?://|\S+@\S+', value) and clean_research(value) == value:
            offered.add((value, tab))
    return next(iter(offered)) if len(offered) == 1 else (None, False)


def _protected(provenance):
    return bool(provenance and (provenance.get('origin') == 'manual' or provenance.get('confidence') in ('manual', 'verified')))


def _same_source(provenance, url):
    return bool(provenance and not _protected(provenance) and provenance.get('origin') == 'crawled'
                and provenance.get('source') == url)


def _repairable(person, url, value, tab, legacy):
    previous = (person.get('provenance', {}).get('research_direction_raw') or {})
    old = person.get('research_direction_raw')
    if not value or _protected(previous):
        return False
    if not old:
        return True
    if not _same_source(previous, url):
        return False
    if old == value or _PLACEHOLDER.fullmatch(old):
        return True
    if old == _ORDERED_PREFIX + value:
        return True
    if tab and old.startswith(_TAB_PREFIX):
        # Match the same old selector output from these exact source bytes.
        return old == '、'.join(legacy.get('research_directions') or [])
    return False


def parse_detail(cfg, html, url):
    person = cfg.get('_original_profile') or {}
    name, soup = _person_page(html, url, cfg.get('_expected_name') or person.get('name'), person.get('detail_url'))
    key = _profile_key(url)
    full_home = key[0] == _FACULTY and url == f'https://{_FACULTY}/{key[1]}/zh_CN/index.htm'
    if full_home and person.get('detail_url') not in (None, url):
        provenance = person.get('provenance') or {}
        if any(_protected(provenance.get(field)) for field in ('detail_url', 'profile_url')):
            raise IdentityConflict('西电现登记URL的人工或独立核验证据受保护')
        if old := personal_email(person.get('email')):
            addresses, _, conflicted = _declared_contacts(soup, url)
            if conflicted or addresses and {value.casefold() for value in addresses} != {old.casefold()}:
                raise IdentityConflict('西电备用本人页的明确邮箱与原档不同，保留原登记')
    # The old parser may fetch encrypted tSites fields. The normalized DOM
    # intentionally contains only the HTML proof already read by the caller.
    for node in soup.select('span[_tsites_encrypt_field]'):
        node.decompose()
    legacy = tsites.parse_detail(cfg, str(soup), url)
    result = {'name': name}
    if full_home:
        result['_identity_profile_home'] = url
    for field in _NON_CONTACT_FIELDS:
        current = person.get(field)
        value = legacy.get(field)
        if value and field == 'title':
            value, _ = normalize_title(value)
        if current and current == value and _same_source(person.get('provenance', {}).get(field), url):
            result[field] = current
    value, tab = _direction(soup)
    if _repairable(person, url, value, tab, legacy):
        result.update(research_direction_raw=value, research_directions=[value])
    return result


def _contact_rows(soup):
    yield from soup.select('#n0 > p, .p_left .t_jbxx_nr > p, .leftside .jjside li, .profie .lxfs h5')
    for heading in soup.select('.rightconside1 > h2, .mo > .drag > span'):
        if _text(heading) not in ('其他联系方式', '联系方式'):
            continue
        faculty = heading.name == 'h2'
        pane = (heading if faculty else heading.parent).find_next_sibling()
        expected = 'rightfont' if faculty else 'nr'
        if pane is not None and pane.name == 'div' and expected in pane.get('class', []):
            yield from pane.select('p, li')


def _declared_contacts(soup, url):
    addresses, sites = set(), set()
    conflicted = False
    for row in _contact_rows(soup):
        if row.select_one('[_tsites_encrypt_field]'):
            continue
        text = _text(row)
        if match := _EMAIL_LABEL.fullmatch(text):
            shown = match[1].strip()
            if not shown and row.name == 'p':
                sibling = row.find_next_sibling()
                if sibling is not None and sibling.name == 'p':
                    row, shown = sibling, _text(sibling)
                    following = row.find_next_sibling()
                    if following is not None and following.name == 'p' and _ADDRESS.fullmatch(_text(following)):
                        conflicted = True
            value = personal_email(shown) if _ADDRESS.fullmatch(shown) else None
            links = {personal_email(a['href'][7:]) for a in row.select('a[href^="mailto:"]')}
            if value and (not links or links == {value}):
                addresses.add(value)
            elif links or '@' in shown or '[AT]' in shown.upper():
                conflicted = True
        if match := _HOME_LABEL.fullmatch(text):
            for a in row.select('a[href]'):
                target = homepage_url(urljoin(url, a['href']))
                shown = homepage_url((match[1] or '').strip())
                parts = urlsplit(target or '')
                owner = (parts.netloc, parts.path.strip('/').split('/', 1)[0])
                if (target and (not shown or shown == target) and target.startswith('https://')
                        and same_scope(target, url) and owner != _profile_key(url)):
                    sites.add(target)
    return addresses, sites, conflicted


def parse_contact(cfg, person):
    read = cfg.get('_read_source')
    url = person['detail_url']
    if not read or not _profile_key(url):
        return {}
    _, html = read(url)
    name, soup = _person_page(html, url, person['name'], url)
    addresses, sites, conflicted = _declared_contacts(soup, url)
    result = {}
    provenance = person.get('provenance') or {}
    prior = cfg.get('_previous_email') or person.get('email')
    if not conflicted and len(addresses) == 1 and not _protected(provenance.get('email')):
        value = next(iter(addresses))
        if not prior or prior.casefold() == value.casefold() and _same_source(provenance.get('email'), url):
            result['email'] = prior or value
    if len(sites) == 1 and not person.get('homepage') and not _protected(provenance.get('homepage')):
        result['homepage'] = next(iter(sites))
    return {**result, '_verified_roster_name':name, '_field_sources':dict.fromkeys(result, url)} if result else {}

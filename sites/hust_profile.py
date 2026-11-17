"""Read explicit English personal modules; never infer identity from pinyin."""
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler.mentor_recovery import personal_email


_MAIL_LINE = re.compile(r"^[·•\s]*(?:本人邮箱|电子邮箱|电子邮件|邮箱|E-?mail)\s*[：:]\s*(.+)$", re.I)
_HOME_LINE = re.compile(r"(?:^|[。；;，,])\s*(?:(?:我的|本人)?个人(?:学术)?主页|个人网站|学术主页|Personal (?:website|homepage))\s*[：:]\s*(https?://[^\s<>，。；、]+)", re.I)
_TEAM_NEARBY = re.compile(r"学生|秘书|助理|行政|团队|课题组|公共邮箱|共用邮箱|办公室|教务|合作|通讯作者|导师为|导师是")
_HIDDEN = 'script, style, footer, nav, [_tsites_encrypt_field], [hidden], [style*="display:none"], [style*="display: none"]'


def _personal_identity(soup, expected):
    head = soup.select_one('.js-top .info h2')
    visible_name = head.get_text(strip=True) if head else ''
    if visible_name and re.fullmatch(r'[\u3400-\u9fff·]{2,6}', visible_name):
        return visible_name == expected
    if expected in identity_names(soup):
        return True
    title = soup.title.get_text(strip=True) if soup.title else ''
    return title.startswith('华中科技大学主页平台管理系统 ' + expected + '--')


def _contact_fields(blocks, biography):
    emails = set()
    homes = set()
    for block in blocks:
        for element in block.select('p, li, td'):
            line = element.get_text(' ', strip=True)
            match = _MAIL_LINE.fullmatch(line)
            if not match or _TEAM_NEARBY.search(line) or match[1].count('@') != 1:
                continue
            email = personal_email(match[1])
            domain = email.rpartition('@')[2].casefold() if email else ''
            if domain == 'hust.edu.cn' or domain.endswith('.hust.edu.cn'):
                emails.add(email)
    for block in biography:
        for line in block.get_text('\n', strip=True).splitlines():
            # Label ownership must be explicit. Other parties and project links
            # in a biography remain outside the contact fields.
            if _TEAM_NEARBY.search(line):
                continue
            if match := _HOME_LINE.search(line):
                address = match[1].rstrip('.,;:）)】]')
                parts = urlsplit(address)
                if parts.hostname and not parts.username and not parts.password:
                    homes.add(address)
    result = {}
    if len(emails) == 1:
        result['email'] = next(iter(emails))
    if len(homes) == 1:
        result['homepage'] = next(iter(homes))
    return result


def parse_contact(cfg, original):
    """Read a verified public HUST profile and its explicitly linked full bio."""
    if not cfg.get('hust_contact_profile') or not cfg.get('_read_source'):
        return {}
    url = original['detail_url']
    if urlsplit(url).hostname != 'faculty.hust.edu.cn':
        return {}
    reader = cfg['_read_source']
    _, html = reader(url)
    soup = BeautifulSoup(html, 'html.parser')
    name = original['name']
    if not _personal_identity(soup, name):
        raise ValueError('华科个人页身份与名单不符')
    for node in soup.select(_HIDDEN):
        node.decompose()
    visible = soup.select('.dft-midcont .Psl-info .cont')
    parsed = _contact_fields(soup.select('.Ot-ctact .cont, .dft-side .Psl-info .cont') + visible, visible)
    sources = {field: url for field in parsed}
    if any(not original.get(field) and field not in parsed for field in ('email', 'homepage')):
        prefix = urlsplit(url).path.strip('/').split('/')[0]
        links = set()
        for anchor in soup.select('.Psl-info a[href]'):
            target = urljoin(url, anchor['href'])
            parts = urlsplit(target)
            if (anchor.get_text(strip=True) in {'More+', '更多', '更多+'}
                    and parts.netloc == 'faculty.hust.edu.cn' and parts.scheme == urlsplit(url).scheme
                    and not parts.query and not parts.fragment
                    and re.fullmatch(rf'/{re.escape(prefix)}/(?:zh_CN|en)/more/\d+/jsjjgd/index\.htm', parts.path)):
                links.add(target)
        if len(links) == 1:
            target = next(iter(links))
            try:
                _, html = reader(target)
            except (OSError, ValueError):
                if parsed and (original.get('email') or parsed.get('email')):
                    return {'name': name, '_field_sources': sources, **parsed}
                raise
            full = BeautifulSoup(html, 'html.parser')
            if not _personal_identity(full, name):
                raise ValueError('华科完整个人简介身份与名单不符')
            for node in full.select(_HIDDEN):
                node.decompose()
            # Inspect the biography text users see on the linked page.
            blocks = full.select('.zw-article .atccont')
            for field, value in _contact_fields(blocks, blocks).items():
                if field not in parsed:
                    parsed[field] = value
                    sources[field] = target
    return {'name': name, '_field_sources': sources, **parsed}


def identity_names(soup):
    head = soup.select_one('.js-top .info h2')
    keywords = soup.select_one('meta[name="keywords"]')
    description = soup.select_one('meta[name="description"]')
    if not all((head, keywords, description, soup.title)):
        return []
    name = keywords.get('content', '').split(',', 1)[0].strip()
    english = head.get_text(' ', strip=True)
    if (re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', name)
            and description.get('content', '').startswith(name + ',')
            and re.fullmatch(r'[A-Za-z ]+', english)
            and soup.title.get_text(strip=True).startswith('华中科技大学主页平台管理系统 ' + english + '--')):
        return [name]
    return []


def parse(soup):
    out = {}
    sections = []
    for box in soup.select('.blockwhite'):
        head = box.select_one('.title .info h2')
        content = box.select_one('.cont')
        if head and content:
            sections.append((head.get_text(' ', strip=True).lstrip('· ').strip(), content))
    for box in soup.select('dl.itempub'):
        head = box.select_one('dt .intit li')
        content = box.find('dd', recursive=False)
        if head and content:
            sections.append((head.get_text(' ', strip=True), content))
    for label, content in sections:
        if label == 'Personal Profile':
            text = content.get_text(' ', strip=True)
            text = re.sub(r'\s*More\+\s*$', '', text)
            if text and text != 'No content':
                out['bio_raw'] = text
        elif label == 'Research Focus':
            values = list(dict.fromkeys(p.get_text(' ', strip=True) for p in content.select('li')))
            values = [value for value in values if value and value != 'No content']
            if values:
                out['research_directions'] = values
    identity = soup.select_one('.dft-side .Psl-info .cont')
    if identity:
        values = set(identity.get_text('\n', strip=True).splitlines())
        for title, chinese in [('Professor', '教授'), ('Associate professor', '副教授'), ('Lecturer', '讲师')]:
            if title in values:
                out['title'] = chinese
                break
        bits = [chinese for title, chinese in [('Supervisor of Doctorate Candidates', '博导'),
                                              ("Supervisor of Master's Candidates", '硕导')] if title in values]
        if bits:
            out['supervisor'] = '、'.join(bits)
    return out

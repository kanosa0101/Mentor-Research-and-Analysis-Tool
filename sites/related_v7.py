"""0.7 新院系：复用名单钩子，个人字段仅从身份/联系/明确方向区获取。"""
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
from sites import related_roster
from sites.tsites import _header_block

TITLE = r'(?:讲席|特聘|长聘|兼职|客座|荣誉)?(?:教授|副教授|助理教授|讲师|助教|研究员|副研究员|助理研究员|教授级高级工程师|高级工程师|工程师|高级实验师|实验师|院士)'


def parse_contact(cfg, original):
    if cfg.get('hust_contact_profile'):
        from sites.hust_profile import parse_contact as parse_hust_contact
        return parse_hust_contact(cfg, original)
    return {}


class IdentityMismatch(ValueError):
    """官方标题或明确姓名区显示了名单之外的另一个人。"""


def collect(cfg, page_url, html, fetched_at):
    if not cfg['list'].get('academic_units'):
        return related_roster.collect(cfg, page_url, html, fetched_at)
    soup = BeautifulSoup(html, 'html.parser')
    cards = BeautifulSoup('<div></div>', 'html.parser')
    attrs = {}
    for a in soup.select('.teachers-name a'):
        if a.get('dept') not in cfg['list']['academic_units']:
            continue
        card = cards.new_tag('div', attrs={'class': 'person'})
        card.append(a)
        cards.div.append(card)
        attrs.setdefault((a.get_text(strip=True), a.get('href')), dict(a.attrs))
    local = dict(cfg, list=dict(cfg['list'], card_selector='.person'))
    rows = related_roster.collect(local, page_url, str(cards), fetched_at)
    for row in rows:
        attr = attrs.get((row['name'], row['url']), {})
        title = attr.get('title', '')
        if re.fullmatch(TITLE, title):
            row['title'] = title
        qualification = attr.get('type', '')
        if re.fullmatch(r'(?:博导|硕导)(?:[、，\s]+(?:博导|硕导))*', qualification):
            row['supervisor'] = qualification
        row['institutes'] = [attr['dept']]
    return rows


def iter_roster(cfg):
    people, dates = {}, []
    for url in cfg['list']['urls']:
        html, meta, _ = fetch.fetch_text('GET', url)
        if re.search(r'下一页|末页', BeautifulSoup(html, 'html.parser').get_text()):
            raise ValueError('出现未登记分页，停止而非声称完整')
        rows = collect(cfg, url, html, meta['fetched_at'])
        if not rows:
            raise ValueError('名单为空或解析失败：' + url)
        for row in rows:
            people.setdefault((row['name'], row['url']), row)
        dates.append(meta['fetched_at'])
    cfg['_roster_names'] = {row['url']: row['name'] for row in people.values()}
    return list(people.values()), {'fetched_at': min(dates), 'pages': len(dates)}


def parse_detail(cfg, html, url):
    if '_roster_names' not in cfg and not cfg.get('_expected_name'):
        iter_roster(cfg)
    expected = cfg.get('_expected_name') or cfg.get('_roster_names',{}).get(url)
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    names = []
    generic = {'个人信息', '个人资料', '个人简介', '教师简介', '个人主页', '教师主页', '首页', '姓名'}
    for node in soup.select('.name, .photobox h1, .js-top .info h2'):
        value = re.split(r'[\s（(]', node.get_text(' ', strip=True), maxsplit=1)[0]
        if re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', value) and value not in generic:
            names.append(value)
    if not names and urlsplit(url).hostname == 'faculty.csu.edu.cn':
        from sites.csu_profile import identity_names
        names += identity_names(soup)
    if not names and urlsplit(url).hostname == 'faculty.hust.edu.cn':
        from sites.hust_profile import identity_names
        names += identity_names(soup)
    named_title = re.fullmatch(r'(?:华中科技大学主页平台管理系统|中南大学)\s+([\u4e00-\u9fff·]{2,6})(?:--.*)?', title)
    if expected and ((names and expected not in names) or (named_title and named_title.group(1) not in generic and named_title.group(1) != expected)):
        raise IdentityMismatch('个人页身份明确变为他人：' + str(expected))
    title_match = expected and re.search(r'(?<![\u4e00-\u9fff])' + re.escape(expected) + r'(?![\u4e00-\u9fff])', title)
    if not expected or (names and expected not in names) or not (title_match or expected in names):
        raise ValueError('个人页身份未确认与名单本人一致：' + str(expected))
    result=parse_profile(cfg, html, url)
    result['name']=expected
    if result.get('bio_raw'):
        from sites.profile_fields import research,own_labelled_email
        if not result.get('research_directions') and not result.get('research_direction_raw'):
            direction=research(result['bio_raw'])
            if direction:result['research_direction_raw']=direction
        if not result.get('email'):
            email=own_labelled_email(result['bio_raw'])
            if email:result['email']=email
    return result


def parse_profile(cfg, html, url):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.select('script, style, span[_tsites_encrypt_field]'):
        node.decompose()
    out = {}
    portal = urlsplit(url).hostname.startswith('faculty.')
    if portal:
        identity = soup.select_one('.jbqk') or soup.select_one('.dft-side .Psl-info .cont') or soup.select_one('.brief .data') or soup.select_one('.t_jbxx_nr')
        text = identity.get_text('\n', strip=True) if identity else _header_block(soup)
        name_block = soup.select_one('.photobox .name')
        if name_block:
            text += '\n' + name_block.get_text('\n', strip=True)
        contacts = [identity] if identity else []
        contacts += list(soup.select('.Ot-ctact .cont'))
        for heading in soup.select('h1, h2, h3'):
            label = re.sub(r'[A-Za-z\s]', '', heading.get_text(strip=True))
            block = heading.parent
            if block.get('class') == ['info']:
                block = block.parent.parent
            elif set(block.get('class', [])) & {'title', 'part_tit'}:
                block = block.parent
            if len(block.get_text()) > 10000:
                continue
            content = block.get_text('\n', strip=True)
            if label in ('个人简介', '教师简介'):
                meaningful = re.sub(r'个人简介|教师简介|Personal [Pp]rofile|暂无内容|Teacher homepage|\s+', '', content)
                if meaningful:
                    out['bio_raw'] = content
            if label in ('研究方向', '研究领域'):
                content_box = block.select_one('.cont') or block
                if content_box is block and heading.parent is block:
                    nodes = []
                    for sibling in heading.find_next_siblings():
                        if sibling.name in ('h1', 'h2', 'h3') or re.match(r'招生|科研项目|论文|联系', sibling.get_text(strip=True)):
                            break
                        nodes.append(sibling)
                else:
                    nodes = content_box.select('li, p')
                values = list(dict.fromkeys(n.get_text(' ', strip=True) for n in nodes if n.get_text(strip=True)))
                values = [v for v in values if v not in {'暂无内容', 'Research focus', '研究方向', '研究领域'}]
                if values:
                    out['research_directions'] = values
            if label == '其他联系方式':
                contacts.append(block)
    else:
        article = soup.select_one('.v_news_content') or soup.select_one('#vsb_content')
        if article is None:
            raise ValueError('未识别个人正文')
        info = article.select_one('.txt') or article
        text = info.get_text('\n', strip=True).split('个人简介')[0]
        contacts = [BeautifulSoup('<div></div>', 'html.parser')]
        contacts[0].div.string = text
        out['bio_raw'] = article.get_text('\n', strip=True)
        match = re.search(r'研究方向\s*[：:]\s*([^\n]+)', text)
        if match:
            out['research_directions'] = [match.group(1)]
    qualifications = []
    for line in text.split('\n'):
        value = re.sub(r'^(?:职称|职务)\s*[：:]\s*', '', line).strip()
        if re.fullmatch(TITLE, value):
            out.setdefault('title', value)
        if re.fullmatch(r'(?:博士生导师|硕士生导师)(?:[、，,\s]+(?:博士生导师|硕士生导师))*', value):
            qualifications.append(value)
    bits = [short for full, short in [('博士生导师', '博导'), ('硕士生导师', '硕导')] if any(full in value for value in qualifications)]
    if bits:
        out['supervisor'] = '、'.join(bits)
    for block in contacts:
        if block is None:
            continue
        contact = block.get_text('\n', strip=True)
        match = re.search(r'(?:电子邮箱|邮箱|电子邮件|E-mail|Email)\s*[：:]\s*([^\n]+)', contact, re.I)
        if match:
            email = normalize_email(match.group(1))
            if email:
                out.setdefault('email', email)
    if urlsplit(url).hostname == 'faculty.csu.edu.cn':
        from sites.csu_profile import parse
        for key, value in parse(soup).items():
            out.setdefault(key, value)
    if urlsplit(url).hostname == 'faculty.hust.edu.cn':
        from sites.hust_profile import parse
        for key, value in parse(soup).items():
            out.setdefault(key, value)
    if not out:
        raise ValueError('详情无明确个人字段，保留名单并登记失败')
    return out

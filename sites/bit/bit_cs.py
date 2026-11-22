import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from crawler import fetch
from crawler.mentor_recovery import homepage_url, personal_email
from sites.wp import parse_wp_detail

# cs.bit.edu.cn 名录(bssds 博导/sssds 硕导)列表是 JS 注入, 需渲染; 条目是
# 32位哈希 .htm 链接。详情页字段卡片在 div.summary(逐行"职称：/E-mail："),
# 简介在 .article, 都不是标准 vsb_content——parse_wp_detail 返回空, 本钩子自理。
_HASH_HREF = re.compile(r"[0-9a-f]{32}\.htm$")
_LINE_LABEL = re.compile(
    r"^(职\s*称|电\s*话|联系电话|E\s*-?\s*mail|电子邮件|邮箱|通信地址|办公地址|个人主页)\s*[:：]\s*(.*)$", re.I)
_SUP_RE = re.compile(r"(?:博士生导师|硕士生导师|博导|硕导)")
_RESEARCH_HEADING = re.compile(r"(?m)^科研方向[ \t]*\r?$")
_NEXT_HEADING = re.compile(r"(?m)^(代表性学术成果|承担科研情况|所获奖励|社会兼职|备注)[ \t]*\r?$")
_TITLE = r"(?:预聘|准聘|特聘|长聘)?(?:副教授|助理教授|教授|副研究员|助理研究员|研究员|高级实验师|实验师|讲师)"
_TITLE_CLAUSE = re.compile(rf"(?:(?:北京理工大学)?计算机学院|北京理工大学)?\s*({_TITLE})")
_AFFILIATED_TITLE = re.compile(rf"(?:^|[。；]\s*)(?:现任\s*)?北京理工大学[，,\s]*计算机学院[，,\s]*({_TITLE})(?=$|[，,、。；])")
_EMAIL = re.compile(r"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_HOMEPAGE_LABEL = re.compile(r"^个人(?:主页|网站)\s*[:：]\s*(.+)$")


def extract_research_direction(bio):
    """Return an exact, bounded section from the BIT article text, or None."""
    starts = list(_RESEARCH_HEADING.finditer(bio or ''))
    if len(starts) != 1:
        return None
    end = _NEXT_HEADING.search(bio, starts[0].end())
    if end is None:
        return None
    section = bio[starts[0].end():end.start()].strip()
    return section if section and section not in ('无', '暂无', '待更新', '略') else None


def iter_roster(cfg):
    people = {}
    meta = None
    for ch in cfg["list"]["channels"]:
        text, meta, _ = fetch.fetch_rendered(ch["url"], wait_ms=6000, scroll=True)
        soup = BeautifulSoup(text or "", "html.parser")
        for a in soup.select("a[href]"):
            if not _HASH_HREF.fullmatch(a["href"].rsplit("/", 1)[-1]):
                continue
            name = re.sub(r"\s+", "", a.get_text(strip=True))
            if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name) or name in people:
                continue
            href = urljoin(ch["url"], a["href"])
            people[name] = {
                "name": name, "url": href, "profile_url": href,
                "institutes": [], "supervisor": ch["cat"],
            }
    return list(people.values()), meta


def _profile_email(value):
    addresses = {email.casefold(): email for token in _EMAIL.findall(value) if (email := personal_email(token))}
    institutional = [email for key, email in addresses.items() if key.endswith('@bit.edu.cn')]
    if len(institutional) == 1:
        return institutional[0]
    if len(addresses) == 1:
        return next(iter(addresses.values()))
    return personal_email(value) if not addresses else None


def _intro_title(intro, name):
    opening = re.split(r'[。；]', intro, maxsplit=1)[0]
    if opening.startswith((name + '，', name + ',')) or _TITLE_CLAUSE.fullmatch(re.split(r'[，,、]', opening)[0].strip()):
        titles = []
        for part in re.split(r'[，,、]', opening):
            if re.search(r'历任|曾任|师从|兼职|毕业', part):
                break
            if match := _TITLE_CLAUSE.fullmatch(part.strip()):
                titles.append(match.group(1))
        if titles:
            return '、'.join(dict.fromkeys(titles))
    match = _AFFILIATED_TITLE.search(intro)
    return match.group(1) if match else None


def parse_contact(cfg, original):
    """Read a unique personal email from a configured CS research institute table."""
    reader = cfg.get('_read_source')
    url = cfg.get('profile_contact_roster')
    if not reader or not url or original.get('email') or (original.get('school'), original.get('dept')) != ('bit', 'cs'):
        return {}
    _, html = reader(url)
    soup = BeautifulSoup(html, 'html.parser')
    matches, addresses = [], []
    for table in soup.select('.article table'):
        cells = [row.find_all(['th', 'td'], recursive=False) for row in table.find_all('tr')]
        if not cells or [cell.get_text(strip=True) for cell in cells[0]] != ['姓名', '导师类型', '研究领域', '邮箱']:
            continue
        for row in cells[1:]:
            if len(row) != 4:
                continue
            name, qualification, direction, raw_email = [cell.get_text(' ', strip=True) for cell in row]
            email = _profile_email(raw_email)
            if email:
                addresses.append(email.casefold())
            if name == original['name']:
                matches.append((email, ' | '.join((name, qualification, direction, raw_email))))
    if len(matches) == 1 and matches[0][0] and addresses.count(matches[0][0].casefold()) == 1:
        email, row = matches[0]
        return {'name': original['name'], '_verified_roster_name': original['name'], 'email': email,
                '_field_sources': {'email': url}, '_contact_locator': {'email': {'table_row': row}}}
    return {}


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one('.left > .title')
    name = heading.get_text(' ', strip=True) if heading else ''
    if cfg.get('_expected_name') and name != cfg['_expected_name']:
        raise ValueError('北理工计算机学院个人页的姓名未核对一致')
    out = {'name': name} if name else {}
    sm = soup.select_one(".summary")
    if sm:
        lines = [node.get_text(' ', strip=True) for node in sm.select('p, li')]
        for line in lines or sm.get_text('\n', strip=True).splitlines():
            m = _LINE_LABEL.fullmatch(line.strip())
            if not m or not m.group(2).strip():
                continue
            label, v = m.group(1), m.group(2).strip()
            if "称" in label:
                out.setdefault("title", v)
            elif "mail" in label.lower() or label in ('邮箱', '电子邮件'):
                e = _profile_email(v)
                if e:
                    out.setdefault("email", e)
            elif "电话" in label.replace(' ', ''):
                out.setdefault("phone", v)
            elif "地址" in label:
                out.setdefault("office_address", v)
    art = soup.select_one(".article")
    if art is not None and len(art.get_text(strip=True)) > 60:
        out.setdefault("bio_raw", art.get_text("\n", strip=True))
        direction = extract_research_direction(out['bio_raw'])
        if direction:
            out['research_direction_raw'] = direction
        if name and not out.get('title'):
            intro = art.find('p')
            if intro and (title := _intro_title(intro.get_text('', strip=True), name)):
                out['title'] = title
        homes = set()
        for node in art.select('p, li'):
            if match := _HOMEPAGE_LABEL.fullmatch(node.get_text(' ', strip=True)):
                link = node.select_one('a[href]')
                target = urljoin(url, link['href']) if link else match.group(1).strip()
                if target.startswith('www.'):
                    target = 'https://' + target
                if homepage_url(target) and target != url:
                    homes.add(target)
        if len(homes) == 1:
            out['homepage'] = next(iter(homes))
    page_title = soup.title.get_text(strip=True).split('-') if soup.title else []
    labels = page_title[1] if len(page_title) == 3 and page_title[0] == name and page_title[2] == '北京理工大学计算机学院' else ''
    supervisor = {'博导' if '博' in label else '硕导' for label in _SUP_RE.findall(labels)}
    if supervisor:
        out['supervisor'] = '、'.join(sorted(supervisor))
    return out

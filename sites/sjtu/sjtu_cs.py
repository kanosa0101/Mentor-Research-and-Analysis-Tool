import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.mentor_recovery import PAGE_CHROME, canonical, homepage_url, personal_email
from crawler.title_util import normalize_title
from sites.profile_fields import clean_research, direction_is_mixed, qualification

DETAIL_RE = re.compile(r"/jiaoshiml/[A-Za-z0-9\-]+\.html$")
COLLEGE_TITLE = '上海交通大学计算机学院（网络空间安全学院、密码学院）'
RESEARCH_HEADINGS = ('研究方向', '研究领域', '研究兴趣', '科研方向')
INTRO_HEADINGS = ('个人简介', '个人简历')
EXPLICIT_TOPIC = re.compile(r'^(?:目前|当前)?(?:主要)?研究(?:方向|领域|兴趣)(?:主要)?'
                            r'\s*(?:聚焦于?|集中在|侧重于?|为|是|包括|涵盖|涉及|[:：])\s*(.+)')
RESEARCH_FOCUS = re.compile(r'^(?:主要)?研究(?:工作)?聚焦于?\s*(.+)')
WORKS_ON = re.compile(r'^(?:以[^。；，,]{1,45}为(?:导向|目标)[，,]\s*)?'
                      r'(?:目前|长期|一直)?(?:主要)?从事\s*(.+?研究(?:[，,]\s*深耕.+)?)(?:$|[，,；;])')
TOPIC_TAIL = re.compile(r'[，,；;]\s*(?=迄今|截至|先后|曾|累计|现任|提出|发布|获得|主持|承担|参与|'
                        r'主导|负责|发表|出版|担任|开发了|研发了|欢迎|具体成果|主要成果)')
UNSAFE_TOPIC = re.compile(r'https?://|\S+@\S+|招生|培养学生|申请人|课题资助|个人主页|'
                           r'毕业|授课|教学|指导教师|导师的|团队成员|负责项目|任职')
FOREIGN_INTRO = re.compile(r'(?:以下|下文|下面|下述|下方)\s*(?:内容|文字|资料)?\s*'
                           r'(?:为|是|系|介绍|列出|展示|说明)[^。；，]{0,12}?'
                           r'(?:合作者|合作方|同事|学生|导师|他人|团队|课题组|实验室)')
EMAIL_LABELS = {'邮箱', '电子邮箱', '电子邮件', 'email', 'e-mail'}
HOME_LABELS = {'个人主页', '个人网站', '课题组主页', '实验室主页'}
ADDRESS = re.compile(r'[A-Za-z0-9._%+\-]+\s*(?:@|\(\s*@\s*\)|\[\s*at\s*\])\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}', re.I)
SHARED_EMAILS = {'scs@sjtu.edu.cn'}


def _official_detail(url):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.netloc == 'www.cs.sjtu.edu.cn'
            and not parsed.query and not parsed.fragment and DETAIL_RE.fullmatch(parsed.path))


def _roster_name(name):
    return ''.join(name.split()).removesuffix('（兼）')


def iter_roster(cfg):
    lst = cfg["list"]
    text, meta, _ = fetch.fetch_text(lst["method"], lst["url"], lst["params"])
    d = _extract_json(text)
    soup = BeautifulSoup(d["content"], "html.parser")
    found = {}
    disputed = set()
    for item in soup.select(".rc-item"):
        head = item.select_one(".name")
        inst = head.get_text(strip=True) if head else ""
        for a in item.select('a[href]'):
            try:
                href = urljoin(cfg["base_url"], a["href"])
            except ValueError:
                continue
            if not _official_detail(href):
                continue
            name = a.get_text(strip=True)
            if not name:
                continue
            rec = found.setdefault(href, {"name": name, "url": href, "institutes": []})
            if _roster_name(rec['name']) != _roster_name(name):
                disputed.add(href)
            if inst and inst not in rec["institutes"]:
                rec["institutes"].append(inst)
    return [row for url, row in found.items() if url not in disputed], meta


def _profile(cfg, html, url):
    if not _official_detail(url):
        raise ValueError('不是上海交大计算机学院登记本人页')
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select(PAGE_CHROME):
        node.decompose()
    cards = soup.select(".js-info")
    if len(cards) != 1:
        raise ValueError('上海交大本人页缺少唯一姓名资料栏')
    names = cards[0].select('.name')
    name = names[0].get_text(strip=True) if len(names) == 1 else ''
    expected = cfg.get('_expected_name') or (cfg.get('_original_profile') or {}).get('name')
    key = ''.join(name.split())
    if not re.fullmatch(r'[\u4e00-\u9fff·]{2,6}', key) or expected and ''.join(expected.split()) != key:
        raise ValueError('上海交大本人页姓名与登记不一致')
    if (expected or soup.title) and (not soup.title or soup.title.get_text(strip=True) != key + '-' + COLLEGE_TITLE):
        raise ValueError('上海交大本人页标题未核实名人与学院')
    return expected or name, soup, cards[0]


def _contact_rows(info):
    for row in info.select('.dt > p'):
        label, sep, value = row.get_text(' ', strip=True).replace('：', ':', 1).partition(':')
        if sep and value.strip():
            yield label.strip().casefold(), value.strip(), row.find_all('a', href=True)


def _visible_addresses(value, links):
    matches = list(ADDRESS.finditer(value))
    if not matches or not re.fullmatch(r'[\s,，;；、/]*', ADDRESS.sub('', value)):
        return set()
    addresses = set()
    for match in matches:
        address = re.sub(r'\(\s*@\s*\)|\[\s*at\s*\]', '@', match[0], flags=re.I)
        if personal := personal_email(re.sub(r'\s+', '', address)):
            addresses.add(personal.casefold())
    mailto = {link['href'][7:].casefold() for link in links if link['href'].casefold().startswith('mailto:')}
    if mailto and mailto != addresses:
        return set()
    return addresses - SHARED_EMAILS


def _research_value(value):
    if (not value or UNSAFE_TOPIC.search(value)
            or direction_is_mixed(value) or not 2 <= len(value) <= 1000):
        return None
    return clean_research(value)


def _research_section(extra, name):
    parts = {}
    for part in extra.select(':scope > .item'):
        label = part.select_one(':scope > .name')
        text = part.select_one(':scope > .txt')
        if label and text:
            parts.setdefault(label.get_text(strip=True), []).append(text)
    dedicated = [item for label in RESEARCH_HEADINGS for item in parts.get(label, ())]
    if len(dedicated) == 1 and (value := _research_value(dedicated[0].get_text(' ', strip=True))):
        return value
    if len(dedicated) > 1:
        return None
    introductions = [item for label in INTRO_HEADINGS for item in parts.get(label, ())]
    if len(introductions) == 1:
        intro = introductions[0].get_text(' ', strip=True)
    elif not parts and not extra.find(True):
        lead, _, intro = extra.get_text(strip=True).partition('\n')
        if lead.strip() not in INTRO_HEADINGS:
            return None
    else:
        return None
    found = set()
    named_prefix = re.compile(r'^' + re.escape(''.join(name.split())) + r'(?:博士|副教授|教授|研究员)?[，,\s]*')
    for sentence in re.split(r'[。！？\n]', intro):
        if FOREIGN_INTRO.search(sentence):
            break
        sentence = named_prefix.sub('', sentence.strip())
        match = EXPLICIT_TOPIC.match(sentence) or RESEARCH_FOCUS.match(sentence) or WORKS_ON.match(sentence)
        if match and (value := _research_value(TOPIC_TAIL.split(match[1], maxsplit=1)[0].strip())):
            found.add(value)
    return next(iter(found)) if len(found) == 1 else None


def _existing_fields(original, parsed):
    provenance = original.get('provenance') or {}
    if original.get('title') and normalize_title(parsed.get('title') or '')[0] == normalize_title(original['title'])[0]:
        parsed['title'] = original['title']
    return {field: value for field, value in parsed.items() if field == 'name' or
            (value is not None and (provenance.get(field) or {}).get('origin') != 'manual'
             and original.get(field) in (None, '', value))}


def parse_detail(cfg, html, url):
    name, soup, info = _profile(cfg, html, url)
    original = cfg.get('_original_profile') or {}
    title_el = info.select_one(".zw")
    out = {"name": name, "title": title_el.get_text(strip=True) if title_el else None}
    img = info.select_one(".imgk img")
    if img and img.get("src"):
        out["photo_url"] = urljoin(cfg["base_url"], img["src"])
    known = {"email": set(), "institutes": [], "unknown": []}
    for label, value, links in _contact_rows(info):
        if label in EMAIL_LABELS:
            known['email'].update(_visible_addresses(value, links))
        elif label == "所在研究所":
            known["institutes"].append(value)
        elif label in HOME_LABELS:
            continue
        elif label == "电话":
            known.setdefault("phone", []).append(value)
        elif label in ("地址", "办公地址"):
            known.setdefault("office_address", []).append(value)
        else:
            known["unknown"].append(f"{label}：{value}")
    previous = original.get('email')
    if previous and previous.casefold() in known['email']:
        out['email'] = previous
    if not original:
        out["institute_from_detail"] = known["institutes"]
    if known.get("phone"):
        out["phone"] = "；".join(known["phone"])
    if known.get("office_address"):
        out["office_address"] = "；".join(known["office_address"])
    out["unknown_fields"] = known["unknown"]
    extra = soup.select_one(".js-dt")
    if extra is not None:
        bio = extra.get_text("\n", strip=True)
        if bio:
            out["bio_raw"] = bio
            if direction := _research_section(extra, name):
                out['research_direction_raw'] = direction
            supervisor=qualification(bio,out.get('name',''))
            if supervisor:out['supervisor']=supervisor
    return _existing_fields(original, out)


def parse_contact(cfg, person):
    reader = cfg.get('_read_source')
    if not reader:
        return {}
    url = person['detail_url']
    _, html = reader(url)
    name, _, info = _profile(dict(cfg, _expected_name=person['name']), html, url)
    provenance = person.get('provenance') or {}
    previous = cfg.get('_previous_email') or person.get('email')
    emails, homepages = set(), set()
    registered = {canonical(person[key]) for key in ('detail_url', 'profile_url') if person.get(key)}
    for label, value, links in _contact_rows(info):
        if label in EMAIL_LABELS and (provenance.get('email') or {}).get('origin') != 'manual':
            emails.update(_visible_addresses(value, links))
        if label in HOME_LABELS and not person.get('homepage') and (provenance.get('homepage') or {}).get('origin') != 'manual':
            shown = homepage_url(value)
            candidates = [urljoin(url, link['href']) for link in links] if links else [shown]
            for candidate in candidates:
                if (target := homepage_url(candidate)) and canonical(target) not in registered and (
                        not shown or canonical(shown) == canonical(target)):
                    homepages.add(target)
    claims = {}
    if previous and previous.casefold() in emails:
        claims['email'] = previous
    elif not previous and len(emails) == 1:
        claims['email'] = next(iter(emails))
    if len(homepages) == 1:
        claims['homepage'] = next(iter(homepages))
    return {'_verified_roster_name': name, **claims, '_field_sources': dict.fromkeys(claims, url)}


def _extract_json(text):
    import json

    start = text.find("{")
    if start < 0:
        raise ValueError("no json in response")
    return json.loads(text[start:])

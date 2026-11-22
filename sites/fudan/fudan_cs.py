"""复旦大学计算与智能创新学院（cs.fudan.edu.cn）。
教师名录走 sudy WP generalQuery POST 接口（siteId=577, 189 人）:
title(姓名)/email/exField1(职称+博导)/exField4(研究方向)/exField5(faculty 主页)/
exField6(职称)/exField8(博导硕导)/exField9(级别)。cnUrl 详情页解析简介。
"""
import json
import re
from urllib.parse import urljoin, urlsplit

import requests

from bs4 import BeautifulSoup

from crawler import mentor_recovery
from crawler.mentor_recovery import contact_target, personal_email
from sites.profile_fields import clean_research, direction_is_mixed
from sites.wp import parse_wp_detail

_API = "https://cs.fudan.edu.cn/_wp3services/generalQuery?queryObj=teacherHome"
_FIELDS = ["title", "email", "phone", "cnUrl", "headerPic"] \
    + [f"exField{i}" for i in range(1, 11)]
_PRIMARY_HOSTS = {'ai.fudan.edu.cn', 'cs.fudan.edu.cn'}
_DIRECTION_LABEL = re.compile(r'(?:(?:目前|当前|现阶段)\s*)?(?:主要)?研究(?:方向|领域|兴趣)\s*'
                              r'(?:为|是|包括|包含|聚焦于|集中在|[:：])\s*(.+)')
_OTHER_SCOPE = re.compile(r'^(?:以下|下文|下面|下述).{0,24}(?:合作者|团队|课题组|学生|实验室)')
_INSTITUTE = r'(?:复旦大学)?(?:计算与智能创新学院|计算智能与创新学院|计算机科学技术学院|计算机学院)'
_ROLE = r'(?:(?:副|助理|特聘|长聘|准聘)?(?:教授|研究员)|博士生导师|硕士生导师|博导|硕导|讲师)'
_SELF_ROLE = re.compile(_INSTITUTE + _ROLE + r'(?:[、,，\s]+' + _ROLE + r')*')
_DIRECTION_END = re.compile(r'[，,；;。]\s*(?:在(?:顶级|国际|国内|重要)?(?:期刊|会议)|'
                            r'已?(?:发表|主持|参与|获奖)|代表性?论文\s*[:：]|招生(?:信息|要求)\s*[:：]|'
                            r'(?:科研项目|教学课程|个人主页|联系方式)\s*[:：])')


def _query():
    s = requests.Session()
    s.trust_env = False
    s.headers["User-Agent"] = "Mozilla/5.0 (advisor-research local tool)"
    r = s.post(_API, data={
        "siteId": 577,
        "conditions": json.dumps([
            {"field": "published", "value": "1", "judge": "="},
            {"field": "language", "value": "1", "judge": "="}], ensure_ascii=False),
        "returnInfos": json.dumps([{"field": f, "name": f} for f in _FIELDS],
                                  ensure_ascii=False),
        "pageIndex": 1, "rows": 999,
        "orders": json.dumps([{"field": "siteSort", "type": "asc"}]),
        "articleType": 1, "level": 1,
    }, headers={"X-Requested-With": "XMLHttpRequest",
                "Referer": "https://cs.fudan.edu.cn/53161/list.htm"}, timeout=30)
    r.raise_for_status()
    return json.loads(r.text).get("data") or []


def iter_roster(cfg):
    people = {}
    meta = None
    for r in _query():
        nm = (r.get("title") or "").strip()
        u = (r.get("cnUrl") or "").strip()
        if not nm or not u:
            continue
        # exField5 是"个人主页"文章页——实测为空壳(无正文, meta 仅"点击进入个人主页")，
        # 只存链接不换 detail_url(ai.fudan cnUrl 仍是身份锚点)
        hp = (r.get("exField5") or "").strip()
        if hp and "fudan" in hp:
            hp = hp if hp.startswith("http") else "https://cs.fudan.edu.cn" + hp
        rec = {"name": nm, "url": u, "profile_url": u, "institutes": []}
        if cfg.get('contact_hook_only'):
            # The directory is an identity source. The named field task owns contact writes.
            people[u] = {'name': nm, 'url': u, 'institutes': []}
            continue
        if hp:
            rec["homepage"] = hp
        if r.get("email"):
            rec["email"] = r["email"]
        if r.get("phone"):
            rec["phone"] = r["phone"]
        if r.get("headerPic"):
            rec["photo_url"] = ("https://cs.fudan.edu.cn" + r["headerPic"]
                                if r["headerPic"].startswith("/") else r["headerPic"])
        if r.get("exField1"):
            rec["title"] = r["exField1"]  # "教授、博导" → normalize 拆出导师资格
        elif r.get("exField6"):
            rec["title"] = r["exField6"]
        if r.get("exField8"):
            v = r["exField8"]
            sup = [x for x in ("博导", "硕导") if x[0] in v]
            if sup and "supervisor" not in rec:
                rec["supervisor"] = "、".join(sup)
        if r.get("exField4"):
            rec["research_direction_raw"] = r["exField4"][:300]
        if r.get("exField5") and "fudan" in r["exField5"]:
            rec["homepage"] = r["exField5"]
        people[u] = rec
    return list(people.values()), meta


def _text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''


def _primary_key(url):
    parts = urlsplit(url)
    if (parts.scheme not in ('http', 'https') or parts.netloc not in _PRIMARY_HOSTS or
            parts.query or parts.fragment):
        return None
    path = parts.path + 'list.htm' if parts.path.endswith('/') else parts.path
    return (parts.netloc, path)


def _primary(soup, url, expected, original):
    names = soup.select('.news_wz .news_title')
    if not names:
        return None
    if len(names) != 1 or not (name := _text(names[0])):
        raise ValueError('复旦本人页缺少唯一姓名栏，保留原档')
    if expected and name != expected:
        raise mentor_recovery.IdentityConflict('复旦详情明确姓名与原记录不符，保留原档')
    links = [a for a in soup.select('.col_path a[href]') if _text(a) == '中文信息']
    key = _primary_key(url)
    if not key or len(links) != 1:
        raise ValueError('复旦本人页缺少唯一中文信息自链接，保留原档')
    if (original and key != _primary_key(original['detail_url']) or key != _primary_key(urljoin(url, links[0]['href']))):
        raise mentor_recovery.IdentityConflict('复旦中文本人页路径与原登记不符，保留原档')
    return name


def _direction(value):
    cut = _DIRECTION_END.search(value)
    value = clean_research(value[:cut.start()] if cut else value)
    return value if value and value not in ('—', '--', '未填写') and not direction_is_mixed(value) else None


def _primary_direction(soup, name):
    rows = soup.select('.news_con .news_ex')
    if len(rows) != 1 or _text(rows[0].select_one('.bt')).rstrip('：:') not in ('研究领域', '研究方向'):
        return None
    if value := _direction(_text(rows[0].select_one('.nr'))):
        return value
    directions = set()
    for sentence in re.split(r'[。！？]', _text(soup.select_one('.news_con .news_jj .nr'))):
        sentence = sentence.strip()
        if _OTHER_SCOPE.match(sentence):
            break
        if not (match := _DIRECTION_LABEL.search(sentence)):
            continue
        subject = sentence[:match.start()].strip(' ，,、')
        if subject and subject not in (name, '本人') and not _SELF_ROLE.fullmatch(subject):
            continue
        if value := _direction(match[1]):
            directions.add(value)
    if len(directions) > 1:
        raise ValueError('复旦本人简介存在不同研究方向声明，保留原档待核')
    return next(iter(directions), None)


def _declared_homepage(soup, url):
    links = [a for a in soup.select('.news_con .news_gr > a[href]') if _text(a) == '个人主页']
    if len(links) != 1:
        return None
    target = urljoin(url, links[0]['href'].strip())
    parts = urlsplit(target)
    if (parts.scheme == 'https' and parts.netloc == 'faculty.fudan.edu.cn' and
            re.fullmatch(r'/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*/?', parts.path) and
            not parts.query and not parts.fragment):
        return target
    return None


def _faculty_direction(html, expected, current_email):
    soup = BeautifulSoup(html, 'html.parser')
    title = _text(soup.title)
    if title != expected + ' 中文主页--首页':
        return None
    names = soup.select('.banner-nr > h5, .name > strong')
    if len(names) != 1 or ' '.join(names[0].find_all(string=True, recursive=False)).strip() != expected:
        return None
    affiliation = [_text(node) for node in soup.select('.banner-nr li, .item p')]
    if not any(re.search(r'(?:所在单位|所属院系)\s*[:：]\s*计算与智能创新学院(?:\s|$)', row) for row in affiliation):
        return None
    emails = {personal_email(row.partition('：')[2].strip()) for row in affiliation
              if re.match(r'^(?:电子)?邮箱：', row)} - {None}
    if current_email and emails and {email.casefold() for email in emails} != {current_email.casefold()}:
        return None
    sections = []
    for box in soup.select('.slideTxtBox'):
        heads = [_text(node) for node in box.select(':scope > .hd ul > li')]
        bodies = box.select(':scope > .bd > ul')
        if heads.count('研究方向') == 1 and len(heads) == len(bodies):
            sections.append([_text(node) for node in bodies[heads.index('研究方向')].find_all('li', recursive=False)])
    for box in soup.select('div.shworklist.shworklist2'):
        if _text(box.find('h2', recursive=False)) != '研究方向':
            continue
        region = box.select_one('.yjfx')
        if region:
            for br in region.find_all('br'):
                br.replace_with('\n')
            sections.append([line.strip() for p in region.find_all('p') for line in p.get_text().splitlines()])
    if len(sections) == 1:
        topics = [_direction(line.lstrip('·• ')) for line in sections[0] if line]
        return '；'.join(value for value in topics if value) or None
    return None


def parse_detail(cfg, html, url):
    original = cfg.get('_original_profile') or {}
    expected = cfg.get('_expected_name') or original.get('name')
    if original and _primary_key(original['detail_url']) != _primary_key(url):
        raise mentor_recovery.IdentityConflict('复旦详情候选离开已登记本人路径，保留原档')
    soup = BeautifulSoup(html, 'html.parser')
    name = _primary(soup, url, expected, original)
    if name:
        out = {'name': name}
        for selector, field in [('.news_cara .nr1','title'),('.news_email .nr','email'),
                                ('.news_dz .nr','office_address'),('.news_tel .nr','phone')]:
            value = soup.select_one(selector)
            if value and value.get_text(strip=True) not in ('无','暂无',''):
                stated = value.get_text(' ',strip=True)
                if not cfg.get('contact_hook_only') or original.get(field) in (None, '', stated):
                    out[field] = stated
        qualification = soup.select_one('.news_cara .nr2')
        if qualification and not cfg.get('contact_hook_only'):
            text = qualification.get_text(strip=True)
            parts = [label for token,label in [('博士','博导'),('硕士','硕导')] if token in text]
            if parts:out['supervisor']='、'.join(parts)
        old = original.get('research_direction_raw')
        value = _primary_direction(soup, name)
        if value and old in (None, '', value):
            out['research_direction_raw'] = value
            out['research_directions'] = [value]
        elif not old and cfg.get('_read_source') and (target := _declared_homepage(soup, url)) and target == original.get('homepage'):
            _, target_html = cfg['_read_source'](target)
            if value := _faculty_direction(target_html, name, personal_email(out.get('email') or original.get('email'))):
                out.update(research_direction_raw=value, _field_sources={'research_direction_raw': target})
        return out
    if "/page.htm" not in url:
        return {}  # ai.fudan 等列表页无可解析字段
    parsed = parse_wp_detail(cfg, html, url)
    if parsed.get('name') and expected and parsed['name'] != expected:
        raise mentor_recovery.IdentityConflict('复旦详情明确姓名与原记录不符，保留原档')
    if cfg.get('contact_hook_only'):
        parsed.pop('homepage', None)
    return parsed


def parse_contact(cfg, original):
    url = contact_target(original['detail_url'], cfg)
    if not _primary_key(url) or not cfg.get('_read_source'):
        return {}
    _, html = cfg['_read_source'](url)
    soup = BeautifulSoup(html, 'html.parser')
    name = _primary(soup, url, original['name'], original)
    if not name:
        return {}
    values = {}
    boxes = soup.select('.news_con .news_email .nr')
    previous = cfg.get('_previous_email') or original.get('email')
    if len(boxes) == 1 and (mail := personal_email(_text(boxes[0]))) and _text(boxes[0]) == mail:
        if not previous or previous.casefold() == mail.casefold():
            values['email'] = previous or mail
    if not original.get('homepage') and (target := _declared_homepage(soup, url)):
        values['homepage'] = target
    if not values:
        return {}
    return {**values, '_verified_roster_name': name, '_field_sources': dict.fromkeys(values, url)}

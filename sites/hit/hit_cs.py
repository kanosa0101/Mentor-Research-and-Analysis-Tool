import re
import json
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from crawler import fetch

# 博导/硕导名单页(Word 导出表格, 姓名链 homepage 内网穿透地址——外网不可达,
# 详情无源; 但名单本身能给 roster 级补 supervisor)。渲染需 CDP。
_SUP_PAGES = [("博导", "https://cs.hit.edu.cn/22195/list.htm"),
              ("硕导", "https://cs.hit.edu.cn/22196/list.htm")]


def _supervisor_map():
    sup = {}
    for kind, u in _SUP_PAGES:
        try:
            html, _, _ = fetch.fetch_cdp(u, wait_ms=4000, scroll=True)
        except Exception:
            continue
        for nm in re.findall(
                r'<a href="[^"]*(?:ivpn|homepage)[^"]*"[^>]*>'
                r'(?:<span[^>]*>)?([\u4e00-\u9fa5·]{2,4})', html):
            sup.setdefault(nm, [])
            if kind not in sup[nm]:
                sup[nm].append(kind)
    return sup


def iter_roster(cfg):
    url = cfg["list"]["url"]
    html, meta, _ = fetch.fetch_cdp(url, wait_ms=4000, scroll=True)
    soup = BeautifulSoup(html, "html.parser")
    people = {}
    for tbody in soup.select("tbody"):
        lines = [l.strip().replace("\xa0", "").replace("\t", "")
                 for l in tbody.get_text("\n", strip=True).split("\n")]
        lines = [l for l in lines if l]
        if not lines:
            continue
        section = None
        if re.search(r"(研究中心|研究所|实验室|实验中心|中心|系|学院)$", lines[0]):
            section = lines[0]
        if not section:
            continue
        for l in lines[1:]:
            name = re.sub(r"\d+$", "", l)
            if not re.match(r"^[\u4e00-\u9fa5·]{2,4}$", name):
                continue
            rec = {"name": name, "url": url, "profile_url": url,
                   "institutes": [section]}
            key = (name, url)
            if key in people:
                if section not in people[key]["institutes"]:
                    people[key]["institutes"].append(section)
            else:
                people[key] = rec
    sup = _supervisor_map()
    for rec in people.values():
        kinds = sup.get(rec["name"])
        if kinds:
            rec["supervisor"] = "、".join(kinds)
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    if urlsplit(url).hostname!='homepage.hit.edu.cn':return {}
    soup=BeautifulSoup(html,'html.parser');name=soup.select_one('h3.chineseName')
    if name is None:return {}
    out={'name':name.get_text(strip=True)}
    from crawler.email_util import normalize_email
    # The official newUtils.js renders EmailText by IsReverse; decode only this
    # known public template, never encrypted/private contact fields.
    if soup.select_one('script[src="scripts/utils/newUtils.js"]'):
        emails={normalize_email(node.get_text(strip=True)[::-1]) for node in soup.select('#col-r .EmailText')}
        emails.discard(None)
        if len(emails)==1:out['email']=next(iter(emails))
    directions=soup.select_one('#teacher_info .user-label')
    if directions and directions.get_text(strip=True):out['research_direction_raw']=directions.get_text(' ',strip=True)
    holder=soup.select_one('div.teacher-body[data-tid]');reader=cfg.get('_read_source')
    if holder and reader and re.fullmatch(r'[a-f0-9]{32}',holder['data-tid']):
        _,body=reader('https://homepage.hit.edu.cn/TeacherHome/teacherBody.do?id='+holder['data-tid']+'&versionId=')
        content=json.loads(body)
        if not isinstance(content,str):raise ValueError('HIT公开个人简介不是JSON字符串')
        detail=BeautifulSoup(content,'html.parser')
        for heading in detail.select('.part_t_l em'):
            if heading.get_text(strip=True)!='个人简介':continue
            section=heading.find_parent(class_='part_box')
            if section:
                bio=re.sub(r'^(?:个人简介\s*)?(?:名称\s*)?','',section.get_text(' ',strip=True)).strip()
                out['bio_raw']=bio
                # The identity centre must appear in the person's own opening,
                # not a collaborator, publication, or the rest of the homepage.
                opening=re.split(r'[。]',bio,maxsplit=1)[0][:240]
                if opening.startswith(out['name']):out['_identity_bio']=opening
                match=re.search(r'(?:特聘|长聘|准聘|预聘|助理|副)?(?:教授|研究员)|讲师',opening)
                if match:out['title']=match[0]
                # Existing HIT qualifications come from separate official lists.
                # A shortened biography must not remove a listed qualification.
                break
    return out

"""华东师范大学计算机学院。
- 教师名录 jzgml/list.htm: .team ul li 服务端内嵌全部教师(姓名/个人主页/
  职称/办公室/电话/邮箱 + data-name 分类), 直接解析, 无需交互
- 个人主页 faculty.ecnu.edu.cn/.../main.psp: 教育背景/工作经历/个人简介
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch
from sites.profile_fields import research,qualification,own_labelled_email


def iter_roster(cfg):
    people = {}
    meta = None
    for lu in cfg["list"]["urls"]:
        html, meta, _ = fetch.fetch_text("GET", lu)
        soup = BeautifulSoup(html, "html.parser")
        for li in soup.select(".team ul li"):
            a = li.select_one("a[title]") or li.select_one("a[href]")
            if a is None:
                continue
            nm_raw = a.get("title") or a.get_text(strip=True) or ""
            nm = re.sub(r"\s+", "", re.sub(r"[（(][^）)]*[)）]", "", nm_raw))  # 去掉"（兼）"
            href = str(a.get("href") or "")
            # 有个人主页的链 faculty.ecnu.edu.cn, 没有的链 /_redirect 文章页
            if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", nm) \
                    or not (href.startswith("http") or href.startswith("/_redirect")):
                continue
            if href.startswith("/"):
                href = "https://cs.ecnu.edu.cn" + href
            if href in people:
                continue
            rec = {"name": nm, "url": href, "profile_url": href, "institutes": []}
            intro = li.select_one(".intro")
            txt = ''
            if intro:
                txt = intro.get_text(" ", strip=True)
            for line in re.split(r"[$\n]", txt):
                line = line.strip()
                low = line.lower()
                if low.startswith("职称"):
                    rec["title"] = line.split("：", 1)[-1].strip() or None
                elif low.startswith(("邮箱", "email")):
                    rec["email"] = line.split("：", 1)[-1].strip() or None
                elif line.startswith("办公室"):
                    rec["office_address"] = line.split("：", 1)[-1].strip() or None
                elif low.startswith(("办公电话", "电话")):
                    rec["phone"] = line.split("：", 1)[-1].strip() or None
            cat = li.get("data-name")
            if cat and "title" not in rec:
                rec["title"] = cat  # 分类名(教授/副教授/专职科研人员)兜底
            people[href] = rec
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    out = {}
    name=soup.select_one('h1.news_title')
    if name is None:return out
    out['name']=name.get_text(strip=True)
    title=name.parent.select_one('.news_meta .tip1')
    if title is not None and re.search(r'教授|研究员|讲师|工程师',title.get_text()):out['title']=title.get_text(strip=True)
    sections={}
    for heading in soup.select('h3.tit'):
        label=heading.get_text(strip=True)
        if label not in ('个人资料','个人简介','研究方向'):continue
        section=heading.parent.parent
        sections[label]=section.get_text('\n',strip=True)
    biography=sections.get('个人简介','')
    if biography:out['bio_raw']=biography
    direction=research(sections.get('研究方向','')) or research(biography)
    if direction:out['research_direction_raw']=direction
    supervisor=qualification(biography,out['name'])
    if supervisor:out['supervisor']=supervisor
    email=own_labelled_email(sections.get('个人资料',''))
    if email:out['email']=email
    out['_field_scope']='\n'.join([name.parent.get_text('\n',strip=True),*sections.values()])
    return out

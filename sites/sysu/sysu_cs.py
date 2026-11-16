import re
from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email

TITLES = ("特聘研究员", "副研究员", "助理教授", "副教授", "教授", "讲师", "研究员")


def iter_roster(cfg):
    url = cfg["list"]["url"]
    html, meta, _ = fetch.fetch_rendered(url, wait_ms=3000, scroll=True)
    soup = BeautifulSoup(html, "html.parser")
    lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
    people = {}
    cur = None

    def flush():
        nonlocal cur
        if cur and (cur.get("email") or cur.get("institutes")):
            key = (cur["name"], cur.get("email") or len(people))
            people.setdefault(key, cur)
        cur = None

    pending = None
    for l in lines:
        if pending == "email":
            e = normalize_email(l)
            if e and cur is not None:
                cur["email"] = e
            pending = None
            continue
        if pending in ("inst", "direction"):
            if cur is not None and l and not re.match(r"^(Email|科研平台|研究领域)", l):
                if pending == "inst":
                    cur["institutes"] = [l]
                else:
                    cur["research_direction_raw"] = l
                pending = None
                continue
            pending = None
        if l.startswith("Email"):
            v = l.split(":", 1)[-1].strip() if ":" in l else ""
            if v:
                e = normalize_email(v)
                if e and cur is not None:
                    cur["email"] = e
            else:
                pending = "email"
            continue
        if l.startswith("科研平台"):
            v = l.split(":", 1)[-1].strip() if ":" in l else ""
            if v and cur is not None:
                cur["institutes"] = [v]
            else:
                pending = "inst"
            continue
        if l.startswith("研究领域"):
            v = l.split("：", 1)[-1].strip() if "：" in l else ""
            if v and cur is not None:
                cur["research_direction_raw"] = v
            else:
                pending = "direction"
            continue
        if cur is not None and "title" not in cur and l in TITLES:
            cur["title"] = l
            continue
        if re.match(r"^[\u4e00-\u9fa5·]{2,4}$", l):
            flush()
            cur = {"name": l, "url": url, "profile_url": url, "institutes": []}
            continue
    flush()
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, 'html.parser')
    card = soup.select_one('article.node--type-teacher .teacherinfo')
    if card is None or card.select_one('h1') is None:
        return {}
    result = {'name': card.select_one('h1').get_text(strip=True)}
    title = card.find('p', recursive=False)
    if title is not None:
        result['title'] = title.get_text(' ', strip=True)
    for paragraph in card.select('.teacherinfodetail p'):
        text = paragraph.get_text(' ', strip=True)
        if text.startswith('联系邮箱'):
            email = normalize_email(re.sub(r'^联系邮箱\s*[：:]\s*', '', text))
            if email:
                result['email'] = email
        elif text.startswith('联系地址'):
            result['office_address'] = re.sub(r'^联系地址\s*[：:]\s*', '', text)
    content = soup.select_one('article.node--type-teacher .field-body')
    if content is not None:
        for heading in content.select('h3'):
            label = heading.get_text(strip=True).rstrip(':：').strip()
            field = {'教师简介': 'bio_raw', '研究领域': 'research_direction_raw',
                     '研究方向': 'research_direction_raw'}.get(label)
            if field:
                parts = []
                for sibling in heading.find_next_siblings():
                    if sibling.name in ('h1', 'h2', 'h3'):
                        break
                    parts.append(sibling.get_text(' ', strip=True))
                if any(parts):
                    result[field] = '\n'.join(part for part in parts if part)
    return result

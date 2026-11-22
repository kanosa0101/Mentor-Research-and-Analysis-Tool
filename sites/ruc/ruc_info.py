import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
from crawler.mentor_recovery import personal_email
from sites.profile_fields import direction_is_mixed

# info.ruc.edu.cn 师资是三层 JS 跳转(师资队伍→按机构→不限)，落地
# ajxjgcx/bx/bx1/index.htm 为全院列表，VSB 翻页 index2.htm..N.htm，
# 名册卡片姓名和研究/课程摘要相邻，详情页才有完整具名栏目。
_NAME_RE = re.compile(r"[\u4e00-\u9fa5·]{2,8}")
_TITLE_RE = re.compile(r"副教授|副研究员|助理教授|研究员|教授|讲师")
_SUP_RE = re.compile(r"博士(?:研究)?生导师|硕士(?:研究)?生导师|博导|硕导")
_ROLE_CONTEXT = re.compile(r"师从|曾任|历任|原任|退休|(?:无|非|未|不|没有).{0,4}(?:博[士导]|硕[士导]|导师)|导师(?:为|是|组)|取消|撤销")
_PERSON_PATH = re.compile(r"/jsky/(?:szdw/ajxjgcx/[a-zA-Z0-9_/]+|rtjs)/[0-9a-f]{32}\.htm")
_SECTION = re.compile(r"(?:主要)?(?:研究方向|研究领域|研究兴趣|科研方向)")
_BLOCK = re.compile(r"</?(?:p|div|li|ol|ul|section|h[1-6]|tr)\b[^>]*>|<br\s*/?>", re.I)
_PLACEHOLDER = re.compile(r"暂无(?:内容)?|无|待补充|未更新|--|(?:感兴趣的)?研究方向[：:]?")
_TOPIC_END = re.compile(r"^(?:指导学生|招生|(?:对)?学生要求|期望要求|课题组|讲授课程|教授课程|课程|科研成果|科研项目|获奖|相关论文|欢迎|诚招|我正在寻找|我正在招|招收|联系我们|联系方式|具体研究内容参见)|(?:现有设备条件|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_INLINE = re.compile(r"(?:(?:目前|当前)的?)?(?:主要)?研究(?:方向|领域|兴趣)(?:为|是|包括|涉及|集中在|聚焦于|[:：])\s*[:：]?\s*([^。\n]+)")
_TOPIC_CUE = re.compile(r"(?:^|(?<=[。；;]))\s*(?:近年|目前|具体|大的)?(?:主要)?研究(?:方向|领域|兴趣)"
                        r"(?:为|是|包括|涉及|集中在|聚焦于|[:：])\s*[:：]?\s*")
_ADDRESS = re.compile(r"^(?:电子)?邮箱\s*[:：]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})(?=$|\s|<,p>)")


def _official_person(url):
    target = urlsplit(url)
    return (target.scheme in ('http', 'https') and target.netloc == 'info.ruc.edu.cn'
            and not target.query and not target.fragment and _PERSON_PATH.fullmatch(target.path))


def iter_roster(cfg):
    people = {}
    conflicts = set()
    meta = None
    for ch in cfg["list"]["channels"]:
        base = re.sub(r"index\.htm$", "", ch["url"])
        for n in range(1, 20):
            page_url = f"{base}index{n}.htm" if n > 1 else ch["url"]
            try:
                text, meta, _ = fetch.fetch_text("GET", page_url)
            except Exception:
                break
            soup = BeautifulSoup(text or "", "html.parser")
            fresh = 0
            for a in soup.select("a[href]"):
                href = urljoin(page_url, a['href'])
                identity = a.select_one('.research-text > .text1')
                if not identity or not _official_person(href):
                    continue
                name = identity.get_text(strip=True)
                if not _NAME_RE.fullmatch(name):
                    continue
                if name not in people:
                    people[name] = {"name": name, "url": href, "institutes": []}
                    fresh += 1
                elif urlsplit(people[name]['url']).path != urlsplit(href).path:
                    conflicts.add(name)
            if fresh == 0:
                break
    return [row for name, row in people.items() if name not in conflicts], meta


def _lines(nodes):
    doc = BeautifulSoup(''.join(map(str, nodes)), 'html.parser')
    for embedded in doc.select('script,style,template,[hidden]'):
        embedded.decompose()
    blocks = BeautifulSoup(_BLOCK.sub('\n', str(doc)), 'html.parser').get_text()
    return [re.sub(r'\s+', ' ', line).strip() for line in blocks.splitlines() if line.strip()]


def _research_direction(content, intro):
    sections = [heading for heading in content.select('.pro_info > .h2 > .name')
                if _SECTION.fullmatch(heading.get_text(strip=True))]
    if len(sections) > 1:
        return None
    topics = []
    if sections:
        for line in _lines(sections[0].parent.find_next_siblings()):
            if _TOPIC_END.search(line) or direction_is_mixed(line):
                break
            if not _PLACEHOLDER.fullmatch(line):
                topic = _TOPIC_CUE.sub('', line).strip('；;。')
                if topic:
                    topics.append(topic)
    if topics:
        return '；'.join(topics)
    if match := _INLINE.search(intro):
        value = re.split(r'，(?=利用前沿|主持|发表|担任|获评|在(?:国内外|管理科学|领域|国际|计算机科学))', match[1], maxsplit=1)[0]
        if not direction_is_mixed(value) and not _TOPIC_END.search(value):
            return value.strip(' ：:；;。')
    return None


def _personal_address(lines):
    labelled = [line for line in lines if re.match(r'^(?:电子)?邮箱\s*[:：]', line)]
    if any(line.count('@') > 1 for line in labelled):
        return None
    known = {match[1] for line in labelled if (match := _ADDRESS.match(line))}
    addresses = {address for value in known if (address := personal_email(value))}
    return next(iter(addresses)) if len(addresses) == 1 else None


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    content = soup.select_one(".content")
    if content is None or not _official_person(url):
        return out
    card = content.select_one(':scope > .card_box > .card')
    name_node = card.select_one(':scope > .name') if card else None
    name = name_node.get_text(strip=True) if name_node else ''
    original = cfg.get('_original_profile') or {}
    expected = cfg.get('_expected_name') or original.get('name') or name
    page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
    if not _NAME_RE.fullmatch(name) or name != expected or not page_title.startswith(name+' -'):
        raise ValueError('人大信息学院本人页标题或正文姓名未通过核对')
    out['name'] = name
    lines = [l.strip() for l in content.get_text("\n", strip=True).split("\n") if l.strip()]
    for line in lines:
        m = re.match(r"^个人主页\s*[:：]\s*(\S+)$", line)
        if m and m.group(1).startswith("http"):
            out.setdefault("homepage", m.group(1))
        # 工作经历行"2025年-至今，中国人民大学，信息学院，副教授"——职称兜底
        m = re.search(r"[\d]年[-–—至]*[\d年至今]*\s*[,，].*?[,，]\s*(教授|副教授|讲师|助理教授|研究员|副研究员)\s*$", line)
        if m:
            out.setdefault("title", m.group(1))
    # 简介段：以"姓名，"开头（半/全角逗号均可）且最长的行
    bio = max((l for l in lines if re.match(r"^[\u4e00-\u9fa5·]{2,4}[,，]", l)),
              key=len, default=None)
    if bio:
        out["bio_raw"] = bio
    # 职称：正文前 500 字内搜词表（bio 形态多样: 有在姓名行、有独立行、有"教学为主型副教授"）
    head = "\n".join(lines)[:500]
    t = _TITLE_RE.search(head)
    if t:
        out.setdefault("title", t.group(0))
    if urlsplit(url).path.startswith('/jsky/rtjs/'):
        return out
    contact = card.select_one(':scope > .contact')
    previous_email = normalize_email(original.get('email'))
    if contact and (address := _personal_address(_lines([contact]))):
        if not previous_email or address.casefold() == previous_email.casefold():
            out['email'] = address
    intro = card.select_one(':scope > .self_intro')
    intro = re.sub(r'\s+', ' ', intro.get_text('', strip=False)).strip() if intro else ''
    if direction := _research_direction(content, intro):
        out['research_direction_raw'] = direction
    opening = intro.split('。', 1)[0]
    kinds = _SUP_RE.findall(opening) if not _ROLE_CONTEXT.search(opening) else []
    role = '、'.join(label for label in ('博导', '硕导') if any(form[0] == label[0] for form in kinds))
    if role and original.get('supervisor') in (None, '', role):
        out['supervisor'] = role
    return out

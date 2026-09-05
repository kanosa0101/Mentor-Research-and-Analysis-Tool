import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from crawler import fetch
from crawler.email_util import normalize_email

# info.ruc.edu.cn 师资是三层 JS 跳转(师资队伍→按机构→不限)，落地
# ajxjgcx/bx/bx1/index.htm 为全院列表，VSB 翻页 index2.htm..N.htm，
# 条目是 32 位哈希 .htm。锚文字粘连("卞昊穹研究方向…讲授课程…")，姓名取开头汉字段。
# 详情页无 vsb_content，主内容在 .content：简介首行"姓名，职称，…导师"，后跟
# 电子邮箱/个人主页行。
_NAME_RE = re.compile(r"^([\u4e00-\u9fa5·]{2,4})(?:研究方向|讲授课程|研究方向·|$)")
_TITLE_RE = re.compile(r"副教授|副研究员|助理教授|研究员|教授|讲师")
_SUP_RE = re.compile(r"博士生导师|硕士生导师|博士研究生导师|硕士研究生导师")


def iter_roster(cfg):
    people = {}
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
                if not re.search(r"[0-9a-f]{32}\.htm$", a["href"]):
                    continue
                nm = _NAME_RE.match(re.sub(r"\s+", "", a.get_text(strip=True)))
                if not nm:
                    continue
                name = nm.group(1)
                if name not in people:
                    href = urljoin(page_url, a["href"])
                    people[name] = {"name": name, "url": href,
                                    "profile_url": href, "institutes": []}
                    fresh += 1
            if fresh == 0:
                break
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    content = soup.select_one(".content")
    if content is None:
        return out
    lines = [l.strip() for l in content.get_text("\n", strip=True).split("\n") if l.strip()]
    for line in lines:
        m = re.match(r"^(?:电子)?邮箱\s*[:：]\s*(.+)$", line)
        if m:
            v = re.sub(r"<[^>]*>|<,p>", "", m.group(1)).strip()
            e = normalize_email(v)
            if e:
                out.setdefault("email", e)
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
    sup = sorted({("博导" if "博" in s else "硕导")
                  for s in _SUP_RE.findall(head)})
    if sup:
        out["supervisor"] = "、".join(sup)
    return out

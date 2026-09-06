import re

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email

# scs.bupt.edu.cn 名录页(单页 jsyl.htm)按研究中心分组, 每人链到 teacher.bupt.edu.cn
# 的 tsites 主页。全站瑞数 412 —— crawl 以 cdp_fallback: true 走真实 Chrome。
# 北邮 tsites 模板与西电/中南不同: 无 _tsites_encrypt_field 密文 span,
# 邮箱明文在 div#gerenxinxi 的标签行里。
LIST_URL = "https://scs.bupt.edu.cn/szjs1/jsyl.htm"

_NAME = re.compile(r"^[\u4e00-\u9fa5·]{2,5}$")
_EMAIL = re.compile(r"电子邮箱\s*[:：]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_LABELS = ("职务", "职称", "所在单位", "办公地点", "学历", "性别")


def _normalize_home(u):
    u = u.strip().replace("http://teacher.bupt.edu.cn", "https://teacher.bupt.edu.cn")
    if u.startswith("//"):
        u = "https:" + u
    return u


def iter_roster(cfg):
    text, meta, _ = fetch.fetch_text("GET", LIST_URL)
    soup = BeautifulSoup(text or "", "html.parser")
    people = {}
    for a in soup.select('a[href*="teacher.bupt.edu.cn"]'):
        nm = a.get_text(strip=True)
        if not _NAME.match(nm):
            continue
        href = _normalize_home(a["href"])
        # 同一人可能同时挂短链(/zhoufeng)和全链(/zhoufeng/zh_CN/index.htm)——
        # 短链 302 到全链, 保留全链形态利于缓存与别名
        cur = people.get(nm)
        if cur is None or (len(href) > len(cur["url"]) and href.startswith(cur["url"])):
            people[nm] = {"name": nm, "url": href, "profile_url": href,
                          "institutes": []}
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    box = soup.select_one("#gerenxinxi") or soup
    h1 = box.find("h1")
    if h1 and _NAME.match(h1.get_text(strip=True)):
        out["name"] = h1.get_text(strip=True)
    text = box.get_text("\n", strip=True)
    m = _EMAIL.search(text)
    if m:
        out["email"] = m.group(1)
    for line in text.split("\n"):
        line = line.strip()
        mm = re.match(r"(所在单位|办公地点|职务|职称)\s*[:：]\s*(.+)$", line)
        if not mm:
            continue
        label, val = mm.group(1), mm.group(2).strip()
        if label == "所在单位":
            out.setdefault("institute_from_detail", [val])
        elif label == "办公地点":
            out.setdefault("office_address", val)
        elif label in ("职务", "职称"):
            # 职务多为行政头衔("中心主任"), 只在含职称词时收录
            t = re.search(r"(讲席|特聘|长聘)?(教授|副教授|助理教授|研究员|副研究员|讲师)", val)
            if t:
                out.setdefault("title", t.group(0))
    # jsxx(基本信息)子页有 职称/导师资格 —— 主页只有职务, 子页字段更全
    m = re.search(r'href="(/[^"]+/jsxx/\d+/jsxx/jsxx\.htm)"', html)
    if m:
        sub = re.match(r"(https?://[^/]+)", url).group(1) + m.group(1)
        try:
            sub_html, _, _ = fetch.fetch_text("GET", sub)
            sub_txt = re.sub(r"<[^>]+>", "\n", sub_html)
            sub_lines = [l.strip() for l in sub_txt.split("\n") if l.strip()]
            for i, line in enumerate(sub_lines):
                if "title" not in out:
                    mm = re.match(r"职称\s*[:：]\s*(.*)$", line)
                    if mm:
                        t = re.search(r"(讲席|特聘|长聘)?(教授|副教授|助理教授|研究员|副研究员|讲师)",
                                      mm.group(1) + " " + (sub_lines[i + 1] if i + 1 < len(sub_lines) else ""))
                        if t:
                            out["title"] = t.group(0)
                if "supervisor" not in out:
                    sup = [s for s in ("博士生导师", "硕士生导师") if s in line]
                    if sup:
                        out["supervisor"] = "博导" if "博士" in sup[0] else "硕导"
                if "email" not in out:
                    mm = re.match(r"电子邮箱\s*[:：]\s*(.+)$", line)
                    if mm:
                        e = normalize_email(mm.group(1))
                        if e:
                            out["email"] = e
        except Exception:
            pass
    return out

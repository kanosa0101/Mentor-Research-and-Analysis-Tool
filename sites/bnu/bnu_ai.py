"""北师大人工智能学院。
- 师资队伍 zgj/fgj/zj 频道：静态 hash 列表页，做全量名单
- 招生-培养导师 bssds/sssds 频道：每学科一篇文章，表格内按方向分组的导师名单
  （含指向师资页的绝对链接），按 URL 对齐给博导/硕导 + 方向
- 详情页：编辑器 HTML，h4「基本信息」下的 li 有 职称/研究方向/邮箱
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch

_HASH = re.compile(r"[0-9a-f]{32}\.htm$")
_NAME = re.compile(r"^[\u4e00-\u9fa5\s·]{2,5}$")


def _abs(href, base):
    if href.startswith("http"):
        return href
    return base.rsplit("/", 1)[0] + "/" + href.lstrip("./")


def _norm_name(nm):
    return re.sub(r"[\s\u3000]+", "", nm)


def _clean_name(nm):
    # 去掉"（派驻珠海校区）"这类括号注记和全角空格
    return _norm_name(re.sub(r"[（(][^）)]*[)）]", "", nm))


def _supervisor_articles(cfg, kind):
    """培养导师频道：返回 [(teacher_url, name, direction, subjects)]。"""
    out = []
    base = cfg["base_url"]
    for lu in cfg["list"][f"{kind}_channels"]:
        html, _, _ = fetch.fetch_text("GET", lu)
        soup = BeautifulSoup(html, "html.parser")
        articles = {_abs(a["href"], lu) for a in soup.select("a[href]")
                    if _HASH.search(str(a.get("href", "")))}
        for au in sorted(articles):
            ahtml, _, _ = fetch.fetch_text("GET", au)
            asoup = BeautifulSoup(ahtml, "html.parser")
            table = asoup.find("table")
            if not table:
                continue
            subjects = None
            direction = None
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if not cells:
                    continue
                first = cells[0]
                if re.match(r"^\d{6}", first):  # "081200计算机科学与技术" 学科行
                    subjects = first
                    continue
                m = re.match(r"^\d+\.[^\d\s].*", first)  # "01.计算机网络与区块链" 方向行
                if m:
                    direction = re.sub(r"^\d+\.", "", first)
                for a in tr.find_all("a"):
                    nm = _clean_name(a.get_text(strip=True))
                    href = str(a.get("href") or "")
                    if not nm or not _HASH.search(href):
                        continue
                    out.append({"url": _abs(href, au), "name": nm,
                                "supervisor": "博导" if kind == "bds" else "硕导",
                                "direction": direction, "subjects": subjects})
    return out


def iter_roster(cfg):
    people = {}
    # 1) 师资名单（正高/副高/中级）
    for lu in cfg["list"]["faculty_channels"]:
        html, meta, _ = fetch.fetch_text("GET", lu)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            href = str(a.get("href") or "")
            if not _HASH.search(href):
                continue
            nm = _clean_name(a.get_text(strip=True))
            if not nm or not _NAME.match(nm):
                continue
            url = _abs(href, lu)
            if url not in people:
                people[url] = {"name": nm, "url": url, "profile_url": url}
    # 2) 博导/硕导对齐 + 方向/学科
    for kind, sup_key in (("bds", "博导"), ("sds", "硕导")):
        if not cfg["list"].get(f"{kind}_channels"):
            continue
        for rec in _supervisor_articles(cfg, kind):
            key = rec["url"]
            if key in people:
                p = people[key]
            else:  # 导师不在师资频道（如双聘），以文章页为落点
                p = people.setdefault(key, {"name": rec["name"], "url": key,
                                            "profile_url": key})
            p.setdefault("supervisor", rec["supervisor"])
            if rec.get("direction"):
                p.setdefault("research_direction_raw", rec["direction"])
            if rec.get("subjects"):
                p.setdefault("subjects", rec["subjects"])
    return list(people.values()), None


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}

    def h_by_text(t):
        for h in soup.find_all(["h2", "h3", "h4"]):
            if re.sub(r"\s", "", h.get_text()) == t:
                return h
        return None

    # ---- 字段行：优先「基本信息」块，没有就在全文行里找（模板变体） ----
    lines = []
    h = h_by_text("基本信息")
    if h:
        ul = h.find_next("ul")
        lines = [li.get_text(" ", strip=True) for li in ul.find_all("li")] if ul else []
    if not lines:
        lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
    for line in lines:
        if "title" in out and "supervisor" in out and "email" in out \
                and "research_directions" in out:
            break
        # 一行可能同时含 职称 和 邮箱("职称：教授 博士生导师 邮箱：xx@yy"),
        # 各字段独立判断, 不能用 elif 链
        if "title" not in out and "职称" in line[:4]:
            m = re.search(r"职称[：:]\s*(.+)", line)
            v = m.group(1) if m else ""
            tm = re.search(r"(讲席|特聘|长聘|兼职|客座|荣誉)?(教授|副教授|助理教授|讲师|助教|"
                           r"研究员|副研究员|助理研究员|高级工程师|工程师|高级实验师|实验师|馆员)", v)
            if tm:
                out["title"] = tm.group(0)
            sup = sorted({("博导" if "博士" in s else "硕导")
                          for s in re.findall(r"(博士生导师|硕士生导师)", v)})
            if sup:
                out["supervisor"] = "、".join(sup)
        if "research_directions" not in out and line.startswith("研究方向"):
            out["research_directions"] = [
                x.strip() for x in re.split(r"[、，,;；]", line.split("：", 1)[-1])
                if x.strip()][:20]
        if "email" not in out and re.search(r"邮箱|Email", line, re.I):
            m = (re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", line)
                 or (re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                               lines[lines.index(line) + 1])
                     if line.rstrip("：:").endswith(("邮箱", "Email"))
                     and lines.index(line) + 1 < len(lines) else None))
            if m:
                out["email"] = m.group(0)
        if "phone" not in out and (line.startswith("办公电话") or line.startswith("电话")):
            out["phone"] = line.split("：", 1)[-1].strip()
        if "office_address" not in out and (line.startswith("办公地点") or line.startswith("办公地址")):
            out["office_address"] = line.split("：", 1)[-1].strip()

    # ---- 简介与研究方向栏目 ----
    def section_text(t):
        h = h_by_text(t)
        if not h:
            return None
        parts = []
        for sib in h.find_next_siblings():
            if sib.name in ("h1", "h2", "h3", "h4"):
                break
            txt = sib.get_text("\n", strip=True)
            if txt:
                parts.append(txt)
        return "\n".join(parts).strip() or None

    bio = section_text("个人简介") or section_text("教师简介") or section_text("研究概况")
    if bio and len(bio) > 30:
        out["bio_raw"] = bio
    if "research_directions" not in out:
        rd = section_text("研究方向")
        if rd and len(rd) > 2:
            out["research_directions"] = [
                x.strip() for x in re.split(r"[\n、，,;；]", rd) if x.strip()][:20]

    img = soup.select_one("p[style*=center] img") or soup.find("img", alt=True)
    if img and img.get("src"):
        src = str(img["src"])
        out["photo_url"] = src if src.startswith("http") else _abs(src, url)
    return out

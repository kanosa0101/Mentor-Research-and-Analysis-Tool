"""东南大学计算机科学与工程学院（cse.seu.edu.cn）。
师资三个频道（教师按职称/按研究方向/按系别）为服务端纯文本名单:
<h2>栏目标题</h2> + <div class="ry-md"><p class="ry-xm">姓名</p>...</div>。
教师无公开详情页链接 → 名单级入库（detail_url 落在按职称页, parse_detail 返回空）。
"""
import re

from bs4 import BeautifulSoup

from crawler import fetch

_P = "https://cse.seu.edu.cn"
_PAGES = {"title": f"{_P}/49355/list.htm",
          "direction": f"{_P}/49356/list.htm",
          "dept": f"{_P}/54820/list.htm",
          "dsxx": f"{_P}/dsxx/list.htm"}
_RANK = {"正高": "正高级", "副高": "副高级", "中级": "中级", "初级": "初级"}


def _norm(nm):
    return re.sub(r"[\s\u3000\xa0]+", "", nm)


def _soup(url):
    html, meta, _ = fetch.fetch_text("GET", url)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup, meta


def _sections(url):
    """返回 [(h2标题, [姓名...]), ...], 跳过标注(博士后)的教师。"""
    html, meta, _ = fetch.fetch_text("GET", url)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for h2 in soup.find_all("h2"):
        grid = h2.find_next_sibling("div", class_="ry-md")
        if grid is None:
            continue
        names = []
        for p in grid.select("p.ry-xm"):
            nm = _norm(p.get_text(strip=True))
            if re.match(r"^[\u4e00-\u9fa5·]{2,4}$", nm):
                nxt = p.find_next_sibling()
                if nxt is not None and "ry-bz" in " ".join(nxt.get("class") or []) \
                        and "博士后" in nxt.get_text():
                    continue  # 师资博士后不入导师库
                names.append(nm)
        out.append((_norm(h2.get_text()), names))
    return out, meta


def iter_roster(cfg):
    people = {}
    meta = None
    # 1) 按职称
    sections, meta = _sections(_PAGES["title"])
    for rank, names in sections:
        for nm in names:
            rec = people.setdefault(nm, {"name": nm, "url": _PAGES["title"],
                                         "profile_url": _PAGES["title"],
                                         "institutes": []})
            if rank and not rec.get("title"):
                rec["title"] = _RANK.get(rank, rank)
    # 2) 按研究方向
    sections, _ = _sections(_PAGES["direction"])
    for direction, names in sections:
        for nm in names:
            rec = people.get(nm)
            if rec and direction and not rec.get("research_direction_raw"):
                rec["research_direction_raw"] = direction
    # 3) 按系别
    sections, _ = _sections(_PAGES["dept"])
    for dept, names in sections:
        for nm in names:
            rec = people.get(nm)
            if rec and dept and dept not in rec["institutes"]:
                rec["institutes"].append(dept)
    # 4) 研究生导师(dsxx): h2=博导/硕导, 条目链 cs.seu.edu.cn/<py>/main.htm 个人主页
    soup, _ = _soup(_PAGES["dsxx"])
    for h2 in soup.find_all("h2"):
        sup = _norm(h2.get_text())
        grid = h2.find_next_sibling("div", class_="ry-md")
        if grid is None:
            continue
        for a in grid.select("a[href*='main.htm']"):
            nm = _norm(a.get_text(strip=True))
            href = str(a.get("href") or "")
            if not re.match(r"^[\u4e00-\u9fa5·]{2,4}$", nm) or "main.htm" not in href:
                continue
            u = href if href.startswith("http") else "https://cs.seu.edu.cn" + \
                (href if href.startswith("/") else "/" + href)
            rec = people.setdefault(nm, {"name": nm, "url": u, "profile_url": u,
                                         "institutes": []})
            if sup and not rec.get("supervisor"):
                rec["supervisor"] = "博导" if "博士" in sup else "硕导"
            rec["url"] = u          # 有个人主页的教师, 详情页用主页
            rec["profile_url"] = u
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    if "/main.htm" not in url:
        return {}  # 名单页无教师详情字段
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = [l.strip() for l in soup.get_text("\n", strip=True).split("\n") if l.strip()]
    out = {}
    for i, l in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        key = l.rstrip("：:")
        if key == "职称" and "title" not in out and nxt:
            from crawler.title_util import normalize_title
            t, _ = normalize_title(nxt)
            if t:
                out["title"] = t
        elif key in ("邮箱", "Email", "email") and "email" not in out and nxt:
            m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", nxt) \
                or re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", l)
            if m:
                out["email"] = m.group(0)
    # 简介: 取最长的中文段落
    paras = [l for l in lines if len(l) > 60 and re.search(r"[\u4e00-\u9fa5]", l)]
    if paras:
        out["bio_raw"] = max(paras, key=len)[:5000]
    body = " ".join(lines)
    m = re.search(r"主要研究方向[为是]([^。]{4,150})。", body)
    if m:
        out["research_direction_raw"] = m.group(1).strip()[:200]
    return out

import re

from bs4 import BeautifulSoup

from crawler import fetch

# 电子科大计算机(网络空间安全)学院: www.scse.uestc.edu.cn 网防(202 质询页,
# requests 视为成功——fetch 的 202+短响应特征降级 CDP)。师资列表 js_sz.jsp
# GET 筛选(FirstLetter=A..Z, fromWenCountNo=99 每页全量), 卡片 img alt=姓名 +
# span.name 第二个=职称; 详情 /info/1081/N.htm 学院文章页(瑞数? CDP 可过),
# 标签行 姓名/专业技术职务/系别/邮箱 + 【个人背景】【研究方向】段。
_BASE = "https://www.scse.uestc.edu.cn/js_sz.jsp"
_QUERY = ("urltype=tree.TreeTempUrl&wbtreeid=1081"
          "&Department=&JobTitle=&JobTitle2=&fromWenCountNo=99&FirstLetter={}")
_CARD = re.compile(
    r'href="(/info/1081/\d+\.htm)">\s*<div class="fls-pic"><img alt="([^"]+)"'
    r'[^>]*>.*?<span class="name">([^<]*)</span>\s*(?:<span class="name">([^<]*)</span>)?',
    re.S)
_TITLE = re.compile(r"(讲席|特聘|长聘)?(教授|副教授|助理教授|研究员|副研究员|讲师|工程师|实验师)")


def iter_roster(cfg):
    people = {}
    meta = None
    for L in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        url = f"{_BASE}?{_QUERY.format(L)}"
        try:
            text, meta, _ = fetch.fetch_text("GET", url)
        except Exception:
            continue
        for href, nm, t1, t2 in _CARD.findall(text or ""):
            nm = nm.strip()
            if not nm or not re.match(r"^[\u4e00-\u9fa5·A-Za-z\s·]{2,30}$", nm):
                continue
            full = "https://www.scse.uestc.edu.cn" + href
            rec = people.setdefault(nm, {"name": nm, "url": full, "profile_url": full,
                                         "institutes": []})
            # 卡片第二个 span.name 是职称(第一个与姓名重复)
            for cand in (t2, t1):
                if cand and _TITLE.fullmatch(cand.strip()) and "list_title" not in rec:
                    rec["list_title"] = cand.strip()
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    txt = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in txt.split("\n") if l.strip()]
    for line in lines:
        m = re.match(r"姓名\s*[:：]\s*([\u4e00-\u9fa5·A-Za-z\s]{2,30})$", line)
        if m and "name" not in out:
            out["name"] = m.group(1).strip()
        m = re.match(r"专业技术职务\s*[:：]\s*(.+)$", line)
        if m:
            t = _TITLE.search(m.group(1))
            if t:
                out["title"] = t.group(0)
        m = re.match(r"系别\s*[:：]\s*(.+)$", line)
        if m:
            out.setdefault("institutes", [m.group(1).strip()])
        m = re.match(r"邮\s*箱\s*[:：]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})$", line)
        if m and "email" not in out:
            out["email"] = m.group(1)
    # 【研究方向】段
    m = re.search(r"【研究方向】\s*\n(.+?)\n\s*【", txt, re.S)
    if m:
        rd = re.sub(r"\s+", " ", m.group(1)).strip()
        if rd:
            out["research_direction_raw"] = rd[:500]
    # 【个人背景】→ bio；本人自述"…教授，博导"可提导师资格
    m = re.search(r"【个人背景】\s*\n(.+?)\n\s*【", txt, re.S)
    if m:
        bio = re.sub(r"[ \t\r]+", " ", m.group(1)).strip()
        if len(bio) > 20:
            out["bio_raw"] = bio[:2000]
            if "email" not in out:
                e = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", bio)
                if e:
                    out["email"] = e.group(0)
    if "supervisor" not in out:
        seg = txt[:len(txt) // 3]
        sup = [s for s in ("博士生导师", "硕士生导师") if s in seg]
        if sup:
            out["supervisor"] = "、".join("博导" if "博士" in s else "硕导" for s in sup)
    return out

import re

from crawler import fetch

# 重大计算机: cs.cqu.edu.cn 挂瑞数(412), 且师资列表页 requests 返回 200 的 JS 壳
# ——必须显式 CDP 渲染。博导硕导页(szdw/bdsd.htm)渲染后是 rcname 链接列表,
# 按"硕士生导师"小节标题分博导/硕导两区。详情在 faculty.cqu.edu.cn(无 WAF,
# requests 可达)的 tsites 主页——index.htm 只有成果栏目, 个人信息(职称/导师/
# 邮箱)在 yjgk 子页。
BDS_URL = "https://cs.cqu.edu.cn/szdw/bdsd.htm"

_NAME = re.compile(r"^[\u4e00-\u9fa5·]{2,5}$")
_RC = re.compile(r'<a href="([^"]+)" class="rcname"[^>]*>([^<]{2,10})</a>')
_SUP_HEAD = re.compile(r"<(?:h\d|strong|em|div|span)[^>]*>\s*([\u4e00-\u9fa5]{2,8}导师)\s*<")
_TITLE_LINE = re.compile(
    r"^((?:讲席|特聘|长聘)?(?:教授|副教授|助理教授|研究员|副研究员|讲师|工程师|实验师))$")


def iter_roster(cfg):
    html, meta, _ = fetch.fetch_cdp(BDS_URL, wait_ms=5000, scroll=True)
    events = []
    for m in _SUP_HEAD.finditer(html):
        events.append((m.start(), "sup", m.group(1), None))
    for m in _RC.finditer(html):
        events.append((m.start(), "rc", m.group(2).strip(), m.group(1)))
    events.sort(key=lambda e: e[0])
    people = {}
    cur_sup = None
    for _, kind, a, b in events:
        if kind == "sup":
            cur_sup = a
            continue
        nm, href = a, b
        if not _NAME.match(nm):
            continue
        href = href.strip()
        if href.startswith("../"):
            # 学院 info 文章页(瑞数域)——CDP 可过, 但证书名不匹配, 统一走 https 主域
            href = "https://cs.cqu.edu.cn/" + href.lstrip("./")
        href = href.replace("http://faculty.cqu.edu.cn", "https://faculty.cqu.edu.cn") \
                   .replace("http://www.cs.cqu.edu.cn", "https://cs.cqu.edu.cn")
        rec = people.setdefault(nm, {"name": nm, "url": href, "profile_url": href,
                                     "institutes": [], "supervisor": []})
        if cur_sup and cur_sup not in rec["supervisor"]:
            rec["supervisor"].append(cur_sup)
        # 同人双链(info 文章页 + faculty 主页)时保留 faculty 主页作 detail
        if "faculty.cqu.edu.cn" in href and "faculty.cqu.edu.cn" not in rec["url"]:
            rec["url"] = rec["profile_url"] = href
    for rec in people.values():
        rec["supervisor"] = "、".join(
            ("博导" if "博士" in s else "硕导") for s in rec["supervisor"]) or None
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    from sites.tsites import parse_detail as tsites_parse

    out = {}
    m = re.search(r"<title>(?:[^<]*?)\s*([\u4e00-\u9fa5·]{2,5})\s*(?:--|—)", html)
    if m:
        out["name"] = m.group(1)
    # 个人信息在 yjgk 子页, 从主页导航找其 URL(栏目 ID 每人不同)
    yj = re.search(r'href="(/[\w-]+/zh_CN/yjgk/[\d/]+index\.htm)"', html) \
        or re.search(r'href="(yjgk/[\d/]+index\.htm)"', html)
    base = re.match(r"(https?://[^/]+/[^/]+)", url)
    info_html = ""
    if yj and base:
        yj_url = re.sub(r"(?<!:)/+", "/", base.group(1) + "/" + yj.group(1).lstrip("/"))
        try:
            info_html, _, _ = fetch.fetch_text("GET", yj_url)
        except Exception:
            info_html = ""
    if info_html:
        txt = re.sub(r"<script.*?</script>|<style.*?</style>", "", info_html, flags=re.S)
        txt = re.sub(r"<[^>]+>", "\n", txt)
        lines = [l.strip() for l in txt.split("\n") if l.strip()]
        sup = re.search(r"(博士生导师|硕士生导师)", "\n".join(lines[:40]))
        if sup:
            out["supervisor"] = "博导" if "博士" in sup.group(1) else "硕导"
        for line in lines[:60]:
            if "title" not in out and _TITLE_LINE.match(line):
                out["title"] = line
            m2 = re.match(r"联系方式\s*[:：]\s*([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", line)
            if m2:
                out["email"] = m2.group(1)
            m3 = re.match(r"所在单位\s*[:：]\s*(.+)$", line)
            if m3:
                out.setdefault("institute_from_detail", [m3.group(1).strip()])
        m4 = re.search(r"研究领域\s*当前位置[^\n]*\n(.+?)(?:\(C\) Copyright|版权所有)", txt, re.S)
        if m4:
            body = re.sub(r"\s+", " ", m4.group(1)).strip()
            if len(body) > 10:
                out["research_direction_raw"] = body[:500]
    # 委托通用 tsites 解析补漏(密文/简介等, 不覆盖已得字段)
    try:
        out.update({k: v for k, v in tsites_parse(cfg, html, url).items()
                    if k not in out})
    except Exception:
        pass
    return out

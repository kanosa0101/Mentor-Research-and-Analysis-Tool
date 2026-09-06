import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch

PERSON_PAGE = re.compile(r"/c\d+a\d+/page\.htm$")


def iter_roster(cfg):
    return walk_channels(cfg, cfg["list"]["channels"])


def walk_channels(cfg, channels):
    people = {}
    meta = None
    for ch in channels:
        url, cat = ch["url"], ch.get("cat")
        n = 0
        while n < 40:
            page_url = url if n == 0 else re.sub(r"list\.htm$", f"list{n+1}.htm", url)
            try:
                if cfg["list"].get("render"):
                    # 名单内嵌在页面 JS 里（如华东师大按职称分类按钮）, 需渲染展开
                    text, meta, _ = fetch.fetch_rendered(page_url, wait_ms=2000)
                else:
                    text, meta, _ = fetch.fetch_text("GET", page_url)
            except Exception:
                break
            if n > 0 and "没有找到" in text and len(text) < 3000:
                break
            for rec in parse_person_anchors(cfg, page_url, text):
                if cat:
                    rec["title"] = cat
                key = rec["name"]
                if key not in people:
                    people[key] = rec
            n += 1
            if not _has_next(text, page_url, n + 1):
                break
    return list(people.values()), meta


def _has_next(text, page_url, next_n):
    return f"list{next_n}.htm" in text


def parse_person_anchors(cfg, page_url, text):
    pattern = re.compile(cfg["list"].get("person_href") or r"/c\d+a\d+/page\.htm$")
    soup = BeautifulSoup(text, "html.parser")
    out = {}
    for a in soup.select("a[href]"):
        href = urljoin(page_url, a["href"])
        if not pattern.search(href):
            continue
        raw = re.sub(r"\s+", "", a.get("title") or a.get_text(strip=True) or "")
        name = re.sub(r"[（(][^)）]*[)）]", "", raw)
        if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name):
            continue
        rec = {"name": name, "url": href, "profile_url": href, "institutes": []}
        sup = [s for s in ("博导", "硕导") if s in raw]
        if sup:
            rec["supervisor"] = "、".join(sup)
        out.setdefault((name, href), rec)
    return list(out.values())


def parse_detail(cfg, html, url):
    return parse_wp_detail(cfg, html, url)


def _meta_fields(soup, out):
    """很多 WP 站把基本字段压进 <meta name="description">
    （如"姓名：陈娟 性别：女职称：副教授最高学历：研究生…Email：xx@yy"）,
    标签间无分隔符, 按已知标签切位置取值。仅在字段缺失时兜底。"""
    md = soup.find("meta", attrs={"name": "description"})
    if not md or not md.get("content"):
        return
    # 值和标签可能挤在一起且带空格("姓 名曾国荪职 称教授"), 去空白后按标签切
    mc = re.sub(r"[\s\u3000]+", "", md["content"])
    from crawler.email_util import normalize_email
    labels = ["姓名", "性别", "职称", "最高学历", "最高学位", "学历", "学位",
              "联系电话", "电话", "E-mail", "Email", "电子邮件", "邮箱",
              "研究方向", "学科", "学科专业", "导师类型", "详细情况", "单位",
              "通讯地址", "办公地点", "个人主页", "电子邮箱"]
    pos = {}
    for lb in labels:
        i = mc.find(lb + "：") if lb + "：" in mc else mc.find(lb + ":")
        if i < 0:
            i = mc.find(lb)
        if i >= 0:
            pos.setdefault(i, lb)
    order = sorted(pos.items())
    vals = {}
    for (i, lb), (j, _) in zip(order, order[1:] + [(len(mc), "")]):
        start = i + len(lb)
        start += 1 if start < j and mc[start] in "：:" else 0
        vals[lb] = mc[start:j]
    def v(*names):
        for n in names:
            if vals.get(n):
                return vals[n].strip()
        return None
    if "title" not in out and v("职称"):
        out["title"] = v("职称")
    if "phone" not in out and v("联系电话", "电话"):
        out["phone"] = v("联系电话", "电话")
    if "email" not in out:
        # 标签切分可能把下个标签(Wechat：/QQ：等)并进本值, 先按"标签词+冒号"截断
        val = re.split(r"(?i)(?:微信|We\s*Chat|QQ|电话|Tel|Phone|地址|Address)\s*[：:]",
                       v("E-mail", "Email", "电子邮件", "邮箱") or "")[0]
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])", val)
        if m:
            e = normalize_email(m.group(0))
            if e:
                out["email"] = e
    if "research_direction_raw" not in out and v("研究方向"):
        out["research_direction_raw"] = v("研究方向")[:200]


def parse_wp_detail(cfg, html, url):
    from crawler.email_util import normalize_email

    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one(".v_news_content") or soup.select_one("#vsb_content") \
        or soup.select_one(".wp_articlecontent")
    if box is None:
        # 华南理工等站正文只有一张介绍图片(无文本容器), 字段全靠 meta description
        out = {}
        _meta_fields(soup, out)
        if out and "bio_raw" not in out:
            md = soup.find("meta", attrs={"name": "description"})
            if md and md.get("content") and len(md["content"].strip()) > 30:
                out["bio_raw"] = md["content"].strip()
        return out
    lines = [l.strip() for l in box.get_text("\n", strip=True).split("\n") if l.strip()]
    out = {}
    LABEL = r"(姓\s*名|职\s*称|电\s*话|邮\s*箱|电子邮件|E\s*-\s*[Mm]ail|个人主页|主\s*页|领域|研究方向|联系邮箱)"
    label_re = re.compile(
        LABEL + r"\s*[:：]\s*([^\n，。；]{0,120})(?=\s*" + LABEL + r"\s*[:：]|$)", re.I)

    def handle(label, value, rest=()):
        k = re.sub(r"\s+", "", label).lower()
        v = value.strip()
        nxt = rest[0] if rest else ""
        if not v and not nxt:
            return
        if "姓" in k:
            out.setdefault("name", v or nxt)
        elif "职" in k and "称" in k:
            # 内联标签会把词拆碎成多行（"职称：/副/教授、博士生导师"）, 逐行拼回
            t = v
            for extra in rest:
                if re.search(r"教授|研究员|讲师|助教|工程师|实验师|馆员|院士", t):
                    break
                if re.match(LABEL, extra):
                    break
                t += extra
            out.setdefault("title", t)
            sup = [s for s in ("博导", "硕导") if s in t]
            if sup:
                out.setdefault("supervisor", "、".join(sup))
        elif "话" in k:
            out.setdefault("phone", v or nxt)
        elif "主页" in k:
            src = v or nxt
            a = re.search(r"https?://[^\s，。；]+", src) \
                or re.search(r"[\w.-]+\.(?:edu\.cn|com|cn|org|net)[^\s，。；]*", src)
            if a:
                h = a.group(0)
                out.setdefault("homepage", h if h.startswith("http") else "https://" + h)
        elif "领域" in k or "方向" in k:
            out.setdefault("research_direction_raw", v or nxt)
        else:
            e = normalize_email(v)
            if not e:
                e = normalize_email(v + " " + " ".join(rest))
            if not e:
                for tok in re.split(r"\s+", v):
                    e = normalize_email(tok)
                    if e:
                        break
            if e:
                out.setdefault("email", e)

    for i, line in enumerate(lines):
        for m in label_re.finditer(line):
            handle(m.group(1), m.group(2), lines[i + 1:i + 4])

    if "email" not in out:
        from urllib.parse import unquote
        for a in box.select('a[href^="mailto:"]'):
            # mailto 可能带多个 URL 编码的邮箱(同济: xx@yy%EF%BC%8Czz@ww)
            for tok in re.split(r"[,;，；\s]+", unquote(a["href"][7:])):
                e = normalize_email(tok)
                if e:
                    out["email"] = e
                    break
            if "email" in out:
                break
    if "email" not in out:
        flat = box.get_text("", strip=True)
        for m in re.finditer(r"[@＃]|[(（{\[]\s*at\s*[)）\]}]", flat, re.I):
            lo, hi = max(0, m.start() - 30), min(len(flat), m.start() + 41)
            seg = flat[lo:hi]
            # 中文标签与邮箱在 get_text("") 下粘连成一个 token("系方式：a@b.c"),
            # 先正则剥出纯邮箱再归一, 否则 normalize 的 ASCII \w 拒收
            dm = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])", seg)
            e = normalize_email(dm.group(0)) if dm else normalize_email(seg)
            if e:
                out["email"] = e
                break
    out["bio_raw"] = "\n".join(lines) or None
    _meta_fields(soup, out)
    if "email" not in out and out.get("bio_raw"):
        # 简介里的"E-Mail：xxx"碎片形态(华南理工: E / -mail： / 值 跨三行)——剥空白后按标签取
        b = re.sub(r"\s+", "", out["bio_raw"])
        b = re.split(r"(?i)(?:微信|WeChat|QQ|电话|Tel|Phone|地址|Address)[:：]", b)[0]
        m = re.search(
            r"(?:E-?[Mm]ail|电子邮件|电子邮箱|邮箱)[:：]"
            r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9]))", b)
        if m:
            e = normalize_email(m.group(1))
            if e:
                out["email"] = e
    if "title" not in out and out.get("bio_raw"):
        head = " ".join(lines[:2])
        m = re.search(r"(长聘教轨|讲席|特聘|副)?(助理教授|副教授|教授|研究员|讲师)", head)
        if m:
            out["title"] = m.group(0)
            sup = [s for s in ("博导", "硕导") if s in head]
            if sup:
                out.setdefault("supervisor", "、".join(sup))
    return out

import re

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email
from sites.wp import parse_wp_detail, parse_person_anchors

# buaa 详情页字段卡片在 div.detail2_t_r（每个字段一个 span），不在 v_news_content 里；
# 页脚 foot_box2 的 scse@buaa.edu.cn 是学院公邮，只解析卡片即天然排除。
_CARD_LABEL = r"(姓\s*名|职\s*称|座\s*机|电\s*话|电\s*子\s*邮箱|电\s*子邮件|邮\s*箱|办公地址|个人主页)"
_CARD_RE = re.compile(_CARD_LABEL + r"\s*[:：]\s*(.*)", re.I)

# 名录分页是目录形态 qtjs/1.htm..N.htm（wp.walk_channels 只认 listN.htm），
# jcrc1 杰出人才无分页单页 50 人。翻页直到 404/无新条目。
_FIRST = re.compile(r"^(.*/)([a-z0-9]+)\.htm$")


def _card_fields(soup, out):
    card = soup.select_one(".detail2_t_r")
    if card is None:
        return
    for span in card.find_all(["span", "p", "div"]):
        line = span.get_text(strip=True)
        m = _CARD_RE.match(line)
        if not m:
            continue
        label, v = m.group(1), m.group(2).strip()
        k = re.sub(r"\s+", "", label)
        if "姓" in k:
            out.setdefault("name", v)
        elif "称" in k:
            out.setdefault("title", v)
        elif "机" in k or "话" in k:
            out.setdefault("phone", v)
        elif "主页" in k:
            if v.startswith("http"):
                out.setdefault("homepage", v)
        elif "邮箱" in k or "mail" in k.lower():
            e = normalize_email(v)
            if e:
                out.setdefault("email", e)


def iter_roster(cfg):
    people = {}
    meta = None
    for ch in cfg["list"]["channels"]:
        url = ch["url"]
        m = _FIRST.match(url)
        prefix, stem = m.group(1), m.group(2)
        n = 1
        while n < 30:
            page_url = url if n == 1 else f"{prefix}{stem}/{n}.htm"
            try:
                text, meta, _ = fetch.fetch_text("GET", page_url)
            except Exception:
                break
            recs = parse_person_anchors(cfg, page_url, text)
            if not recs and n > 1:
                break
            fresh = 0
            for rec in recs:
                if ch.get("cat") and not rec.get("title"):
                    rec["title"] = ch["cat"]
                if rec["name"] not in people:
                    people[rec["name"]] = rec
                    fresh += 1
            if fresh == 0:
                break
            n += 1
    return list(people.values()), meta


def parse_detail(cfg, html, url):
    out = parse_wp_detail(cfg, html, url)
    _card_fields(BeautifulSoup(html, "html.parser"), out)
    return out

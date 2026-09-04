from urllib.parse import urljoin

from bs4 import BeautifulSoup

from crawler import fetch

SECTION_HEADERS = {
    "教育背景", "工作履历", "社会兼职", "研究领域", "研究方向", "研究概况",
    "学术成果", "奖励与荣誉", "代表性论文", "教学工作", "讲授课程", "学术报告",
}


def iter_roster(cfg):
    text, meta, _ = fetch.fetch_text("GET", cfg["list"]["url"])
    soup = BeautifulSoup(text, "html.parser")
    people = []
    for dl in soup.select("dl"):
        head = dl.select_one("dt h4")
        inst = head.get_text(strip=True) if head else ""
        rank = None
        for el in dl.find_all(["h3", "li"]):
            if el.name == "h3":
                rank = el.get_text(strip=True)
                continue
            if el.name != "li":
                continue
            a = el.select_one("h2 a[href]")
            if a is None:
                continue
            name = a.get_text(strip=True)
            url_ = urljoin(cfg["list"]["url"], a["href"])
            ps = [p.get_text(strip=True) for p in el.select(".text p")]
            rec = {"name": name, "url": url_, "institutes": [inst] if inst else []}
            rec["profile_url"] = url_
            if ps:
                rec["list_title"] = ps[0] or None
                rec["list_phone"] = ps[1] if len(ps) > 1 else None
                rec["list_email"] = ps[2] if len(ps) > 2 else None
            if rank:
                rec["rank"] = rank
            people.append(rec)
    return people, meta


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one(".v_news_content") or soup.select_one("#vsb_content")
    if main is None:
        raise ValueError("main content not found")
    lines = [l.strip() for l in main.get_text("\n", strip=True).split("\n") if l.strip()]
    labeled = {}
    for l in lines[:15]:
        if "：" in l:
            k, _, v = l.partition("：")
            k = k.strip()
            if k in ("姓名", "职称", "电话", "邮箱", "电子邮件", "E-mail", "email"):
                labeled[k] = v.strip()
    out = {
        "name": labeled.get("姓名"),
        "title": labeled.get("职称"),
        "email": labeled.get("邮箱") or labeled.get("电子邮件") or labeled.get("E-mail") or labeled.get("email"),
        "phone": labeled.get("电话"),
    }
    out["bio_raw"] = "\n".join(lines) or None
    rd = []
    in_rd = False
    for l in lines:
        if l in SECTION_HEADERS:
            in_rd = l in ("研究领域", "研究方向")
            continue
        if in_rd and l:
            rd.append(l)
    if rd:
        out["research_directions"] = rd
    out["institute_from_detail"] = []
    return out

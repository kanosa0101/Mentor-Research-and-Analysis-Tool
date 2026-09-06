import re

from bs4 import BeautifulSoup
from urllib.parse import urljoin

from crawler import fetch
from crawler.email_util import normalize_email

# csee.hnu.edu.cn(注意域名是 csee 不是 cs)自研教师系统: teacher/syjs/1..6 是
# 按职称分类的卡片表格页(教授/副教授/副教授(教学)/助理教授/教授(教学)/特聘研究员)。
# 卡片: <A href="/people/<id>"><img alt="姓名"> + <td>姓名<br/>职称</td>
#       + <td>研究方向</td> + <td>邮箱</td>——列表级四件套齐全。
# 详情页 /people/<id> 是 <table> 字段(中文名/职称/电子邮件/研究方向/所属机构) + 简介。
_CARD = re.compile(r'<A href="(/people/[a-z0-9-]+)"[^>]*>.*?alt="([^"]+)"', re.I | re.S)


def iter_roster(cfg):
    people = {}
    meta = None
    for ch in cfg["list"]["channels"]:
        try:
            text, meta, _ = fetch.fetch_text("GET", ch["url"])
        except Exception:
            continue
        soup = BeautifulSoup(text or "", "html.parser")
        for tr in soup.select("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            a = tds[0].find("a", href=re.compile(r"^/people/"))
            if a is None:
                continue
            img = a.find("img", attrs={"alt": True})
            name = (img.get("alt") if img else tds[1].get_text()).strip()
            name = re.sub(r"\s+", "", name)
            if not re.match(r"^[\u4e00-\u9fa5·]{2,5}$", name):
                continue
            info = tds[1].get_text("\n", strip=True).split("\n")
            rec = {"name": name, "url": urljoin(ch["url"], a["href"]),
                   "profile_url": urljoin(ch["url"], a["href"]),
                   "institutes": []}
            if len(info) > 1 and re.search(r"教授|讲师|研究员", info[1]):
                rec["title"] = info[1].strip()
            if ch.get("cat") and "title" not in rec:
                rec["title"] = ch["cat"]
            # 研究方向列 + 联系方式列
            if len(tds) > 2 and tds[2].get_text(strip=True):
                rec["research_direction_raw"] = tds[2].get_text(" ", strip=True)[:300]
            if len(tds) > 3:
                e = normalize_email(tds[3].get_text(" ", strip=True))
                if e:
                    rec["email"] = e
            if name not in people:
                people[name] = rec
    return list(people.values()), meta


_LABEL_RE = re.compile(r"^(中文名|学历|职称|联系电话|电子邮件|研究方向|联系地址|所属机构)\s*[:：]\s*(.*)$")


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    tbl = max(soup.find_all("table"), key=lambda t: len(t.get_text()), default=None)
    if tbl is not None and "中文名" in tbl.get_text():
        for line in tbl.get_text("\n", strip=True).split("\n"):
            m = _LABEL_RE.match(line.strip())
            if not m:
                continue
            k, v = m.group(1), m.group(2).strip()
            if k == "职称" and v:
                out.setdefault("title", v)
            elif k == "电子邮件":
                e = normalize_email(v)
                if e:
                    out.setdefault("email", e)
            elif k == "研究方向" and v:
                out.setdefault("research_direction_raw", v[:300])
            elif k == "所属机构" and v:
                out.setdefault("institute_from_detail", [v])
        # 简介: 表格后的长中文段落(含"导师。"等自述)
        body = soup.get_text("\n", strip=True)
        paras = [p.strip() for p in body.split("\n") if len(p.strip()) > 80
                 and not re.search(r"备案|copyright|版权", p, re.I)]
        if paras:
            out["bio_raw"] = re.sub(r"\s+", "", paras[0])[:2000]
    if not out.get("supervisor"):
        # 教师介绍段落自述"现为计算机学院通信工程系教授、博士生导师"(在 bio_raw
        # 截取段落之外), 全页紧模式提取——hnu 页面无导航误配(dry-run +22 全为真自述)
        from crawler.supervisor_util import extract_supervisor
        sup = extract_supervisor(soup.get_text("\n", strip=True))
        if sup:
            out["supervisor"] = sup
    return out

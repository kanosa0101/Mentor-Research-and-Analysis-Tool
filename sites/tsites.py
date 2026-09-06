import re

from bs4 import BeautifulSoup

from crawler import fetch
from crawler.email_util import normalize_email


def iter_roster(cfg):
    people = {}
    meta = None
    urls = list(cfg["list"].get("urls") or [])
    tpl = cfg["list"].get("page_url_template")
    if tpl:
        urls += [tpl.format(n=n) for n in range(1, cfg["list"].get("pages", 1) + 1)]
    pattern = re.compile(cfg["list"]["person_href"])
    for lu in urls:
        html, meta, _ = fetch.fetch_rendered(
            lu, wait_ms=cfg["list"].get("wait_ms", 3000),
            scroll=cfg["list"].get("scroll", True))
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("a[href]"):
            text = re.sub(r"\s+", "", str(a.get_text(strip=True) or ""))
            nm = text or re.sub(r"\s+", "", str(a.get("title") or ""))
            if not re.match(r"^[一-龥·]{2,4}$", nm):
                continue
            href = str(a.get("href") or "")
            if href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http"):
                continue
            if not pattern.search(href):
                continue
            key = (nm, re.sub(r"\d+", "N", href))
            if key not in people:
                people[key] = {"name": nm, "url": href, "profile_url": href,
                               "institutes": []}
    return list(people.values()), meta


_TITLE_RE = re.compile(
    r"(讲席|特聘|长聘|兼职|客座|荣誉)?(教授|副教授|助理教授|讲师|助教|"
    r"研究员|副研究员|助理研究员|高级工程师|教授级高级工程师|工程师|"
    r"高级实验师|实验师|馆员)(（[^）]{1,10}）)?")

_ENC_LABELS = (("email", ("邮箱", "email", "e-mail", "mail")),
               ("phone", ("电话", "手机", "传真")),
               ("office_address", ("地址", "地点", "房间")))


def decrypt_encrypted_fields(soup, html, url):
    """tsites 系统把邮箱/电话等放在 <span _tsites_encrypt_field> 里存密文，
    前端 JS 再请求 /system/resource/tsites/tsitesencrypt.jsp 服务端解密。
    直接调同一接口还原，返回 {field: value}。"""
    m = re.search(r"_tsites_com_view_mode_type_=(\d+)", html)
    if not m:
        return {}
    mode = m.group(1)
    origin = re.match(r"https?://[^/]+", url).group(0)
    out = {}
    for span in soup.select("span[_tsites_encrypt_field]"):
        cipher = span.get_text(strip=True)
        if not cipher or not re.fullmatch(r"[0-9a-fA-F]+", cipher):
            continue
        # 标签可能在同一 li/p 内（模板A），也可能在更外层（模板B label 与密文分节点）。
        # 只用"恰好包含这一个密文"的容器做标签载体，防止爬到含多个字段的父容器串味。
        label = ""
        for p in span.parents:
            if p.name not in ("li", "p", "div"):
                break
            if len(p.select("span[_tsites_encrypt_field]")) > 1:
                break
            label = p.get_text(" ", strip=True).replace(cipher, "").lower()
            if any(k in label for _, kws in _ENC_LABELS for k in kws):
                break
        field = None
        for f, kws in _ENC_LABELS:
            if any(k in label for k in kws):
                field = f
                break
        # 部分模板(西电 faculty HH6)父容器无标签文字, 语义直接写在 span id 里
        if not field:
            sid = span.get("id", "")
            if "tsemail" in sid:
                field = "email"
            elif "tscontact" in sid or "tsphone" in sid:
                field = "phone"
        if field == "office_address" and "邮编" in label:
            continue
        if not field or field in out:
            continue
        api = (f"{origin}/system/resource/tsites/tsitesencrypt.jsp"
               f"?id={span.get('id', '')}&content={cipher}&mode={mode}")
        try:
            raw, _, _ = fetch.fetch_text("GET", api)
            val = re.sub(r"<[^>]+>", "", raw).strip()
            import json as _json
            try:
                val = _json.loads(val).get("content") or val
            except Exception:
                pass
            val = val.strip()
        except Exception:
            continue
        if val:
            # 部分模板 tscontact 解密出的实际是邮箱, 按值形态纠偏
            if field == "phone" and normalize_email(val):
                out.setdefault("email", val)
                continue
            out[field] = val
    return out


def _header_block(soup):
    """定位页头信息块：最小的同时含 所在单位 与 (职称|学科|导师) 的 div。"""
    node = soup.find(string=re.compile("所在单位"))
    if not node:
        return ""
    p = node.parent
    best = ""
    for _ in range(6):
        if p is None or p.name == "body":
            break
        t = p.get_text("\n", strip=True)
        if "所在单位" in t and re.search(r"职称|学科|导师", t):
            best = t
            break
        p = p.parent
    return best


def _section_text(soup, titles):
    """按栏目标题（个人简介/研究方向…）取该栏目正文。标题常带英文后缀
    （如"个人简介<span>Personal Profile</span>"），匹配时忽略英文部分。"""
    for el in soup.find_all(["h1", "h2", "h3", "div", "span"]):
        t = el.get_text(strip=True)
        t2 = re.sub(r"[A-Za-z0-9\s]+", "", t)
        if not any(t2 == x or (t2.startswith(x) and len(t2) <= len(x) + 4) for x in titles):
            continue
        par = el.parent
        if par is None:
            continue
        text = par.get_text("\n", strip=True)
        text = re.sub(r"^\s*" + re.escape(t) + r"\s*", "", text)
        if len(text) > 20:
            return text
    return None


def parse_detail(cfg, html, url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}

    enc = decrypt_encrypted_fields(soup, html, url)
    for span in soup.select("span[_tsites_encrypt_field]"):
        span.decompose()  # 防止密文混进正文行
    out.update(enc)

    name_el = soup.select_one("div.name") or soup.find("h1")
    # 西电等模板的 h1 是栏目标签（"个人信息"），不是人名，防止误当规范名
    _GENERIC_NAMES = {"个人信息", "个人主页", "教师主页", "首页", "个人资料", "个人简介"}
    if name_el:
        nm = re.split(r"[\s—(（]", name_el.get_text(" ", strip=True), 1)[0].strip()
        if re.match(r"^[一-龥·]{2,4}$", nm) and nm not in _GENERIC_NAMES:
            out["name"] = nm

    header = _header_block(soup)
    lines = [l for l in header.split("\n") if l.strip()] if header else []
    if not lines:
        # 变体模板没有"所在单位"字段块，退化为取姓名容器附近的正文行
        name_el = soup.select_one("div.name") or soup.find("h1")
        anchor = name_el if name_el is not None else soup.body
        if anchor is not None:
            par = anchor.parent
            lines = [l for l in par.get_text("\n", strip=True).split("\n") if l.strip()][:15]
    head = "\n".join(lines[:30])

    def _label_value(label):
        for l in lines:
            if l.strip().startswith(label):
                v = l.split("：", 1)[-1].split(":", 1)[-1].strip()
                if v and v != l.strip():
                    return v
        return None

    # 导师资格也可能只出现在姓名栏（模板B：陈先来 — 博士生导师、硕士生导师）
    sup_text = head + "\n" + (name_el.get_text() if name_el else "")
    sup = [s for s in ("博士生导师", "硕士生导师") if s in sup_text]
    if sup:
        out["supervisor"] = "、".join("博导" if "博士" in s else "硕导" for s in sup)

    m = re.search(r"职称[：:]\s*([一-龥]{2,8})", head)
    if m:
        out["title"] = m.group(1)
    else:
        nm = out.get("name", "")
        start = next((i for i, l in enumerate(lines) if nm and nm in l), -1)
        cand = (lines[start + 1:start + 4] if start >= 0 else lines[:4]) or lines
        for l in cand:
            m2 = _TITLE_RE.fullmatch(l.strip())
            if m2:
                out["title"] = m2.group(0)
                break
        if "title" not in out:
            v = _label_value("职务")
            if v and _TITLE_RE.fullmatch(v):
                out["title"] = v
    if "title" not in out:
        # scu 等模板信息块独立于头区: <div class="bs bs-1"><p>职务：教授</p>…<p>所在单位：…</p></div>
        for p in soup.select("div.bs p, div.bsbx p"):
            m = re.match(r"^(?:职称|职务)\s*[:：]\s*(.+)$", p.get_text(" ", strip=True))
            if m and _TITLE_RE.fullmatch(m.group(1).strip()):
                out["title"] = m.group(1).strip()
                break

    v = _label_value("所在单位")
    if v:
        out["institute_from_detail"] = [v]
    subj = _label_value("招生学科") or _label_value("学科")
    if subj:
        out["subjects"] = subj
    if "office_address" not in out:
        v = _label_value("办公地点") or _label_value("办公室")
        if v:
            out["office_address"] = v

    rd = _section_text(soup, ["研究方向", "科学研究", "研究领域"])
    if rd:
        rd = re.split(r"科研项目|论文成果|著作成果|教学成果|查看全部", rd)[0].strip()
        if rd:
            out["research_directions"] = [
                x.strip() for x in re.split(r"[\n、，,;；]", rd) if x.strip()][:20]
    bio = _section_text(soup, ["个人简介", "教师简介", "简介"])
    if bio:
        bio = re.split(r"其他联系方式|科研项目|论文成果", bio)[0].strip()
        if len(bio) > 30:
            out["bio_raw"] = bio
    if "email" not in out:
        # 标签形态兜底(全页扫描): "Email: x@y" / "电子邮箱：x@y" 同行带值，
        # 或标签行/值跨行(西电模板 <p>电子邮箱：</p><p>值</p>)。
        # 值可能是 mailto 锚文本混淆("hchgao AT xidian.edu.cn")，normalize_email 会还原
        for el in soup.find_all(string=re.compile(r"电子?邮箱|E\s*-?\s*[Mm]ail", re.I)):
            ls = (el.string or "").strip()
            m = re.match(r"^电子?邮箱\s*[:：]\s*(.+)$", ls, re.I) or \
                re.match(r"^E\s*-?\s*[Mm]ail\s*[:：]\s*(.+)$", ls, re.I)
            if not m and re.match(r"^电子?邮箱\s*[:：]?$", ls, re.I):
                nxt = el.find_next_sibling()
                if nxt is None and el.parent is not None:
                    nxt = el.parent.find_next_sibling()
                if nxt is not None:
                    m = re.match(r"^电子?邮箱\s*[:：]?\s*(.+)$",
                                 f"邮箱：{nxt.get_text(strip=True)}", re.I)
            if m:
                e = normalize_email(m.group(1))
                if e:
                    out["email"] = e
                    break
    if "email" not in out:
        # mailto href 兜底(西电 web.xidian 模板: <a href="mailto:x@y">x AT y</a>, 锚文本混淆但 href 是明文)
        for a in soup.select('a[href^="mailto:"]'):
            e = normalize_email(a["href"][7:])
            if e:
                out["email"] = e
                break
    if "email" not in out:
        # 裸 <p> 明文兜底(西交 gr.xjtu 模板无任何标签)。全页唯一邮箱直接采用；
        # 多个时仅当恰好一个与站点同校域(xjtu.edu.cn 等)——个人 QQ/163 并存时取官方域
        uniq = {normalize_email(e) for e in re.findall(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9])", soup.get_text(" ", strip=True))} - {None}
        if len(uniq) == 1:
            out["email"] = uniq.pop()
        elif uniq:
            host = re.match(r"https?://([^/]+)", url).group(1)
            parts = host.split(".")
            base_dom = "." + ".".join(parts[-3:]) if host.endswith(("edu.cn", "com.cn", "gov.cn", "ac.cn")) else "." + ".".join(parts[-2:])
            same = [e for e in uniq if e.lower().endswith(base_dom)]
            if len(same) == 1:
                out["email"] = same[0]
    return out

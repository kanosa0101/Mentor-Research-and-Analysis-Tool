import json

from crawler import fetch


def _get_json(url, refresh=False):
    text, meta, _ = fetch.fetch_text("GET", url, refresh=refresh)
    return json.loads(text), meta


def _names(items):
    out = []
    for x in items or []:
        if isinstance(x, dict):
            if x.get("name"):
                out.append(x["name"])
        elif x:
            out.append(str(x))
    return out


def iter_roster(cfg):
    d, meta = _get_json(cfg["list"]["url"])
    people = []
    for t in d.get("teachers", []):
        tid = t["id"]
        people.append({
            "name": (t.get("name") or "").strip(),
            "url": f"{cfg['base_url']}/api/teacher/{tid}",
            "profile_url": f"{cfg['base_url']}/faculty/detail/{tid}",
            "institutes": [],
            "aliases": [t["name_en"]] if t.get("name_en") else [],
        })
    return people, meta


def parse_detail(cfg, html, url):
    t = json.loads(html)["teacher"]
    out = {"name": (t.get("name") or "").strip() or None}
    titles = _names(t.get("teacherTitles"))
    out["title"] = "、".join(titles) if titles else None
    research = _names(t.get("teacherResearchs"))
    out["research_directions"] = research
    out["source_updated_at"] = (t.get("updatedAt") or "")[:10] or None
    img = t.get("image")
    if isinstance(img, dict):
        img = img.get("url") or img.get("path")
    if isinstance(img, str) and img:
        out["photo_url"] = img if img.startswith("http") else cfg["base_url"] + img
    sections = {}
    for s in t.get("introduction") or []:
        title = (s.get("title") or "").strip()
        content = (s.get("content") or "").strip()
        if title:
            sections[title] = content
    out["email"] = sections.get("电子邮箱") or None
    out["phone"] = sections.get("办公电话") or None
    out["office_address"] = sections.get("通讯地址") or None
    bio = "\n".join(f"【{k}】{v}" for k, v in sections.items() if v)
    out["bio_raw"] = bio or None
    out["institute_from_detail"] = []
    return out

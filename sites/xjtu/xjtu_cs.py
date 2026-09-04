"""西安交大教师主页系统（gr.xjtu.edu.cn）。
列表数据不走前端渲染（requestUrl 是 http 混合内容被浏览器拦截），
直接调 tsites 门户数据接口 getsitelistcontent.jsp 拿全量 JSON；
详情页是 tsites 主页，解析直接委托 sites/tsites.py。
"""
import json
import urllib.parse

from crawler import fetch
from sites import tsites

_API = "https://gr.xjtu.edu.cn/system/resource/tsites/getsitelistcontent.jsp"
_PAGE = 12


def iter_roster(cfg):
    people = []
    seen = set()
    startnum = 0
    total = None
    page = 1
    while total is None or startnum < total:
        q = {
            "collegeId": 1025, "disciplineId": 0, "honorId": 1025, "py": "",
            "requestUrl": "http://gr.xjtu.edu.cn/zwzhmh/units_teacherlist.jsp",
            "comType": "collegeTeacher", "treeid": 1021, "ispreview": "false",
            "lang": "zh_CN", "viewmode": 8, "viewid": 1095238,
            "siteOwner": 2105667170,
            "start": page, "end": page * _PAGE,
            "startnum": startnum, "endnum": startnum + _PAGE,
        }
        url = _API + "?" + urllib.parse.urlencode(q)
        text, _, _ = fetch.fetch_text("GET", url)
        try:
            data = json.loads(text)
        except Exception:
            break
        if not data or not (data.get("data") or []):
            break
        total = data.get("totalCount", total)
        for r in data["data"]:
            u = r.get("url") or ""
            nm = (r.get("showName") or r.get("name") or "").strip()
            if not u or not nm or u in seen:
                continue
            seen.add(u)
            rec = {"name": nm, "url": u, "profile_url": u}
            if r.get("email"):
                rec["email"] = r["email"]
            if r.get("job"):
                rec["title"] = r["job"]
            if r.get("unit"):
                rec["institutes"] = [r["unit"]]
            if r.get("discipline"):
                rec["subjects"] = r["discipline"]
            if r.get("officeLocation"):
                rec["office_address"] = r["officeLocation"]
            people.append(rec)
        startnum += _PAGE
        page += 1
        if total and len(people) >= total:
            break
    return people, None


def parse_detail(cfg, html, url):
    return tsites.parse_detail(cfg, html, url)

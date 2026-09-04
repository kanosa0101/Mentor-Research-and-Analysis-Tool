"""四川大学教师主页系统（faculty.scu.edu.cn）。
教师名单内嵌在列表页 <script> 的 ImageScale(...).addimg(照片,主页URL,姓名,uid)
调用里（21 页），对 raw html 正则提取；详情页是 tsites 主页，委托 sites/tsites.py。
"""
import re

from crawler import fetch
from sites import tsites

_ADDIMG = re.compile(
    r'addimg\(\s*"([^"]*)"\s*,\s*"([^"]*/zh_CN/index\.htm)"\s*,\s*"([^"]+)"')

_LIST = ("https://faculty.scu.edu.cn/xyjs.jsp?id=1035&lang=zh_CN&PAGENUM={n}"
         "&totalpage=21&st=0&urltype=tsites.CollegeTeacherList&wbtreeid=1012")


def iter_roster(cfg):
    people = {}
    seen = set()
    tpl = cfg["list"].get("page_url_template")
    n_pages = int(cfg["list"].get("pages", 1))
    for n in range(1, n_pages + 1):
        url = tpl.format(n=n)
        html, _, _ = fetch.fetch_text("GET", url)
        for pic, home, nm in _ADDIMG.findall(html):
            u = home if home.startswith("http") else "https://faculty.scu.edu.cn" + home
            nm = nm.strip()
            if not nm or u in seen:
                continue
            seen.add(u)
            rec = {"name": nm, "url": u, "profile_url": u}
            if pic and not pic.endswith("defaultteacherimg.png"):
                rec["photo_url"] = ("https://faculty.scu.edu.cn" + pic
                                    if pic.startswith("/") else pic)
            people[u] = rec
    return list(people.values()), None


def parse_detail(cfg, html, url):
    return tsites.parse_detail(cfg, html, url)

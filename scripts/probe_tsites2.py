import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

PAGES = {
    "scu": "https://faculty.scu.edu.cn/xyjs.jsp?id=1035&lang=zh_CN&st=0&urltype=tsites.CollegeTeacherList&wbtreeid=1012",
    "csu": "https://cse.csu.edu.cn/szdw/jsml.htm",
    "bnu": "https://ai.bnu.edu.cn/zszl/yjszs/pyds/bssds/index.htm",
    "xjtu": "https://gr.xjtu.edu.cn/units_teacherlist.jsp?id=1025&lang=zh_CN&st=0&urltype=tsites.CollegeTeacherList&wbtreeid=1021",
}

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, proxy={"server": "direct://"})
    for sid, u in PAGES.items():
        try:
            pg = b.new_page()
            try:
                pg.goto(u, timeout=45000, wait_until="networkidle")
            except Exception:
                pg.wait_for_timeout(4000)
            pg.wait_for_timeout(2500)
            html = pg.content()
            Path(f"cache/ts_{sid}.html").write_text(html, encoding="utf-8")
            info = pg.evaluate("""() => {
                const links = [...document.querySelectorAll('a[href]')]
                  .map(a => ({h: a.href, t: (a.getAttribute('title') || a.textContent || '').trim().replace(/\\s+/g, '')}))
                  .filter(x => x.t.length >= 2 && x.t.length <= 4 && /[\\u4e00-\\u9fa5]/.test(x.t)
                       && !/学院|概况|队伍|教师$|名录|导航|首页|更多/.test(x.t));
                return {n: links.length, sample: links.slice(0, 5)};
            }""")
            print(f"### {sid} len={len(html)} cjk_links={info['n']}")
            for s in info["sample"]:
                print(f"    {s['t'][:6]} -> {s['h'][:95]}")
            pg.close()
        except Exception as e:
            print(f"### {sid} ERR {type(e).__name__}: {repr(e)[:70]}")
    b.close()

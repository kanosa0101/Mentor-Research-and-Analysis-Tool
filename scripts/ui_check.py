"""UI 验证：console 错误、DOM 断言、截图（列表页 + 详情页）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
OUT = Path(__file__).resolve().parent.parent / "cache"

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE + "/index.html", wait_until="networkidle")
    page.wait_for_timeout(1200)
    # 断言
    assert page.locator("header.top").count() == 1, "sticky header 缺失"
    count = page.locator("#count").inner_text()
    print("count:", count)
    info = page.locator("#pager .info").inner_text()
    print("pager info:", info)
    rows = page.locator("#tbl tbody tr").count()
    print("rows on page:", rows)
    # 筛选器工作
    page.select_option("#f-school", "csu")
    page.wait_for_timeout(400)
    info2 = page.locator("#pager .info").inner_text()
    print("csu filter:", info2)
    page.select_option("#f-school", "")
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / "ui_index.png"))
    # 详情页
    page.goto(BASE + "/p/csu-cs-chenxianlai.html", wait_until="networkidle")
    page.wait_for_timeout(600)
    print("detail crumb:", page.locator(".crumb").inner_text())
    page.screenshot(path=str(OUT / "ui_detail.png"), full_page=False)
    print("console errors:", errors[:5] if errors else "NONE")
    b.close()

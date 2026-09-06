"""UI 验证：console 错误、DOM 断言、截图（列表页 + 看板 + 详情页 + 跟进写回流）。

用法：python scripts/ui_check.py [base_url]   默认 http://localhost:8000
写回相关断言需要 serve.py 在线；测试产生的跟进记录最后会清理。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(__file__).resolve().parent.parent / "cache"
# 从干净状态开跑（服务端每请求重读文件，删掉即净空；页内旧 OUT 不受影响因为页面随后新开）
OF = Path(__file__).resolve().parent.parent / "data" / "outreach.yaml"
OF.unlink(missing_ok=True)

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    # ---- 列表页 ----
    page.goto(BASE + "/index.html", wait_until="networkidle")
    page.wait_for_timeout(1200)
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
    # 跟进列：serve 在线时表头存在且行内有 star
    assert page.locator("th.c-outreach").count() == 1, "跟进列缺失"
    star = page.locator("[data-star]").first
    star_id = star.get_attribute("data-star")
    page.evaluate("""async (id) => { await fetch('/api/outreach/' + id, {method:'DELETE'}); }""", star_id)
    star.click()
    page.wait_for_timeout(500)
    assert page.locator(".otag.o-interested").count() >= 1, "标意向后 otag 未出现"
    print("index star -> interested ok")
    page.select_option("#f-school", "")
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / "ui_index.png"))

    # ---- 看板 ----
    page.goto(BASE + "/board.html", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    assert page.locator("#hint").is_hidden(), "serve 在线时 hint 不应显示"
    assert page.locator(".col").count() == 5, "看板应有 5 列"
    assert page.locator(f'.cardo[data-id="{star_id}"]').count() == 1, "标意向的人应出现在看板第一列"
    # 搜索添加
    page.fill("#addq", "中南大学")
    page.wait_for_timeout(400)
    n_res = page.locator("#addres .ar").count()
    print("board search hits:", n_res)
    # 拖拽：JS 派发 HTML5 DnD 事件到第二列（已发信）
    page.evaluate("""() => {
      const card = document.querySelector('.cardo');
      const dt = new DataTransfer();
      card.dispatchEvent(new DragEvent('dragstart', {dataTransfer: dt, bubbles: true}));
      const col = document.querySelectorAll('.col')[1];
      col.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true}));
      col.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true}));
    }""")
    page.wait_for_timeout(600)
    in_col2 = page.evaluate(
        """async (id) => (await (await fetch('/api/outreach')).json())[id]?.status""", star_id)
    assert in_col2 == "emailed", f"拖拽换列未写回: {in_col2}"
    print("board drag -> emailed ok")
    # 邮箱复制按钮存在性（剪贴板权限在 headless 下不验内容）
    n_copy = page.locator("[data-copy]").count()
    print("copy buttons on board:", n_copy)
    page.screenshot(path=str(OUT / "ui_board.png"))

    # ---- 详情页 ----
    # 详情页含官网外链照片，networkidle 会被拖死——用 domcontentloaded
    page.goto(BASE + f"/p/{star_id}.html", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    print("detail crumb:", page.locator(".crumb").inner_text())
    assert page.locator("#ob-hint").is_hidden(), "serve 在线时详情页不应显示只读提示"
    page.select_option("#ob-status", "replied")
    page.fill("#ob-notes", "ui_check 测试备注")
    page.click("#ob-save")
    page.wait_for_timeout(600)
    assert "已保存" in page.locator("#ob-msg").inner_text(), "保存无确认"
    hist = page.locator("#ob-history .h-item").count()
    print("history items:", hist)
    assert hist >= 3, "历史条数不足"
    page.screenshot(path=str(OUT / "ui_detail.png"), full_page=False)
    # 移出（清理 + 断言）
    page.on("dialog", lambda d: d.accept())
    page.click("#ob-remove")
    page.wait_for_timeout(500)
    left = page.evaluate("""async (id) => !!(await (await fetch('/api/outreach')).json())[id]""", star_id)
    assert not left, "移出看板后 outreach 仍有残留"
    print("detail remove -> cleaned ok")

    print("console errors:", errors[:5] if errors else "NONE")
    assert not errors, f"console 有错误: {errors[:3]}"
    b.close()
    print("UI CHECK ALL GREEN")

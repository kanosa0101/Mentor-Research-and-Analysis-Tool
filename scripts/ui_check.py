"""UI 回归：启动独立临时跟进服务，绝不读写真实 outreach.yaml。"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from scripts.serve import create_server


def check(BASE, OUT):
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(BASE) else route.fulfill(status=200, body="", content_type="image/png"))
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
        assert page.evaluate('!window.MENTOR_SEARCH'), '初次打开不应加载简介全文'
        page.fill('#q', '计算机视觉')
        page.wait_for_function('window.MENTOR_SEARCH && view.length > 0')
        assert page.evaluate('view.every(p=>p.search_text.includes("计算机视觉") || window.MENTOR_SEARCH[p.page].includes("计算机视觉"))')
        page.fill('#q', '')
        page.locator('summary').filter(has_text='方向').click()
        page.locator('[data-fid="_unknown"]').check()
        assert page.evaluate('view.length === DATA.filter(p=>!(p.facets||[]).length).length')
        page.locator('[data-fid="_unknown"]').uncheck()
        page.locator('summary').filter(has_text='方向').click()
        print('full research search + unknown direction ok')
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
        page.select_option('#f-outreach', 'interested')
        assert page.locator('#tbl tbody tr').count() == 1
        page.select_option('#f-outreach', '')
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
        page.fill('#ob-next', '阅读代表作')
        page.fill('#ob-due', '2026-01-01')
        page.fill('#ob-tags', '优先, 待补材料')
        page.click("#ob-save")
        page.wait_for_timeout(600)
        assert "已保存" in page.locator("#ob-msg").inner_text(), "保存无确认"
        hist = page.locator("#ob-history .h-item").count()
        print("history items:", hist)
        assert hist >= 3, "历史条数不足"
        page.screenshot(path=str(OUT / "ui_detail.png"), full_page=False)
        page.goto(BASE + '/board.html', wait_until='networkidle')
        page.locator('#only-due').check()
        assert page.locator('.cardo').count() == 1
        assert '阅读代表作' in page.locator('.cardo').inner_text()
        with page.expect_download() as download:
            page.click('#backup')
        fixture_backup = OUT / 'ui_backup_fixture.json'
        download.value.save_as(str(fixture_backup))
        page.on('dialog', lambda d: d.accept())
        page.locator('#backup-file').set_input_files(str(fixture_backup))
        page.wait_for_timeout(700)
        assert page.locator('.cardo').count() == 1
        page.goto(BASE + '/index.html', wait_until='networkidle')
        page.fill('#f-tag', '优先')
        assert page.locator('#tbl tbody tr').count() == 1
        page.goto(BASE + f'/p/{star_id}.html', wait_until='domcontentloaded')
        page.wait_for_timeout(800)
        assert page.input_value('#ob-next') == '阅读代表作'
        print('private tags + next step + due filter + browser backup/restore ok')
        # 移出（清理 + 断言）
        page.click("#ob-remove")
        page.wait_for_timeout(500)
        left = page.evaluate("""async (id) => !!(await (await fetch('/api/outreach')).json())[id]""", star_id)
        assert not left, "移出看板后 outreach 仍有残留"
        print("detail remove -> cleaned ok")

        # ---- 对比页 ----
        page.goto(BASE + "/index.html", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.evaluate("localStorage.removeItem('compare_sel'); SEL.clear(); updateCmpBtn();")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        cbs = page.locator("[data-sel]")
        cbs.nth(0).check()
        cbs.nth(1).check()
        btn = page.locator("#cmpbtn")
        assert btn.is_visible(), "勾选后对比按钮未出现"
        assert "2" in btn.inner_text(), "对比按钮计数不为 2"
        page.screenshot(path=str(OUT / "ui_index_sel.png"))
        btn.click()
        page.wait_for_url("**/compare.html")
        page.wait_for_timeout(800)
        assert page.locator("#cmp th.pcol").count() == 2, "对比页应有 2 列"
        nrows = page.locator("#cmp tbody tr").count()
        print("compare rows:", nrows)
        assert nrows >= 12, "对比行数不足"
        page.screenshot(path=str(OUT / "ui_compare.png"))
        page.evaluate("localStorage.removeItem('compare_sel')")
        print("compare page ok")

        mobile = b.new_page(viewport={'width': 390, 'height': 844})
        mobile.goto(BASE + '/board.html', wait_until='networkidle')
        assert mobile.locator('.col').count() == 5
        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth')
        mobile.screenshot(path=str(OUT / 'ui_mobile.png'))
        mobile.goto(BASE + '/index.html', wait_until='networkidle')
        assert mobile.locator('#tbl tbody tr').count() == 50
        assert mobile.evaluate('document.documentElement.scrollWidth <= innerWidth'), '手机列表出现整页横向溢出'
        mobile.close()

        static = b.new_page()
        static.on('pageerror', lambda e: errors.append(str(e)))
        static.goto((Path(__file__).resolve().parent.parent / 'site/index.html').as_uri())
        assert static.locator('#tbl tbody tr').count() == 50
        static.fill('#q', '计算机视觉')
        static.wait_for_function('window.MENTOR_SEARCH && view.length > 0')
        static.close()
        print('mobile board + file:// research search ok')
        page.goto(BASE + '/notices.html', wait_until='domcontentloaded')
        assert page.locator('article').count() > 0
        page.select_option('#school', 'pku/cs')
        assert page.locator('article:visible').count() > 0
        assert '待核验' in page.locator('article:visible').first.inner_text()
        print('official notice pilot + school filter ok')

        print("console errors:", errors[:5] if errors else "NONE")
        assert not errors, f"console 有错误: {errors[:3]}"
        b.close()
        print("UI CHECK ALL GREEN")


def main():
    out = Path(__file__).resolve().parent.parent / 'cache'
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mentor-ui-') as tmp:
        server = create_server(outreach=Path(tmp) / 'outreach.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            check('http://127.0.0.1:' + str(server.server_port), out)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()

"""具体项目的临时导师核验范围验收；全部数据和私人写入位于临时目录。"""
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawler.discovery_util import empty, save_review
from scripts.build_site import SITE, template_environment, write_html
from scripts.serve import create_server


def main():
    out = Path('cache/checklist')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        site = root / 'site'
        (site / 'p').mkdir(parents=True)
        for name in ['discovery-core.js', 'discovery.js', 'ui.css']:
            shutil.copy2(SITE / name, site / name)
        write_html(site / 'discovery.html', template_environment().get_template('discovery.html.j2').render())
        mentors = [{'page': 'fixture-cs-' + state, 'name': '测试' + state, 'school': 'fixture', 'dept': 'cs', 'school_name': '测试学校', 'dept_name': '计算机系', 'supervisor': '硕士生导师', 'email': 'mentor@example.edu', 'unit_groups': ['computer']} for state in ['pass', 'fail']]
        ids = {mentor['page'] for mentor in mentors}
        for pid in ids:
            (site / 'p' / (pid + '.html')).write_text('<p>临时测试导师</p>', encoding='utf-8')
        (site / 'data.js').write_text('window.MENTOR_DATA=' + json.dumps(mentors, ensure_ascii=False) + ';', encoding='utf-8')
        (site / 'compare-data.js').write_text('window.MENTOR_COMPARE={};', encoding='utf-8')
        private = root / 'private'
        private.mkdir()
        data = empty()
        data['preferences'].update(year=2027, degree='master', route='exam', keep_unknown=False)
        data['preferences']['modes'].update(opportunity='hard', eligibility='hard')
        for state in ['pass', 'fail']:
            data, _ = save_review(data, {'mentor_id': 'fixture-cs-' + state, 'year': 2027, 'degree': 'master', 'route': 'exam', 'opportunity': state, 'eligibility': state, 'source_url': 'https://example.edu/legacy', 'quote': '旧通用范围结论', 'confirmed': True}, ids)
        path = private / 'discovery.yaml'
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf-8')
        initial = path.read_bytes()
        server = create_server(site=site, outreach=private / 'outreach.yaml', port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        generic = 'school=fixture&dept=cs&year=2027&degree=master&route=exam'
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={'width': 390, 'height': 844})
                    errors, posts = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: posts.append(request.post_data) if request.method == 'POST' else None)
                    for scope in ['track=special&program=085400%7C菁英班', 'track=special&program=085400%7C工程专项', 'track=special', 'track=ordinary&program=085400%7C电子信息']:
                        page.goto(base + '/discovery.html?' + generic + '&' + scope, wait_until='networkidle')
                        page.wait_for_function('window.DISCOVERY_READY === true')
                        assert page.locator('[data-candidate]').count() == 2, '具体项目不能借旧pass加分或旧fail硬排除'
                        assert page.evaluate('view.every(row=>row.result.score===2&&!row.result.review)')
                        assert '核验尚未区分该项目，需对照原文' in page.locator('#project-context').inner_text()
                        assert '旧通用范围结论' not in page.locator('#candidate-list').inner_text()
                        assert page.locator('[data-review]').first.is_disabled()
                        assert page.locator('#review-save').is_disabled()
                        assert page.locator('#mode-opportunity').is_disabled()
                        assert page.locator('#mode-eligibility').is_disabled()
                        assert '即使取消保留' in page.locator('#project-filter-hint').inner_text()
                        policy = page.locator('[data-candidate] a').filter(has_text='学校与招生要求').first.get_attribute('href')
                        assert ('track=special' if 'track=special' in scope else 'track=ordinary') in policy
                        if 'program=' in scope:
                            assert 'program=085400' in policy
                        page.evaluate('document.querySelector("[data-review]").dispatchEvent(new MouseEvent("click",{bubbles:true}));document.querySelector("#review-form").dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}))')
                        page.click('#clear-unit-context')
                        assert page.locator('[data-candidate]').count() == 2
                        assert page.evaluate('view.every(row=>row.result.checks.filter(c=>["opportunity","eligibility"].includes(c.key)).every(c=>c.state==="unknown"))')
                        assert not page.locator('#project-context').is_hidden()
                        assert page.evaluate('!("track" in readCriteria())&&!("program" in readCriteria())')
                        assert posts == [], '此范围不得提交旧核验POST'
                        assert path.read_bytes() == initial
                    page.screenshot(path=str(out / 'discovery-project-scope-mobile.png'), full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#generic-discovery').get_attribute('href') == 'discovery.html'
                    with page.expect_download() as download:
                        page.click('#discovery-backup')
                    backup = root / 'scope-backup.json'
                    download.value.save_as(str(backup))
                    assert json.loads(backup.read_text(encoding='utf-8')) == {'version': 1, 'discovery': data}, '备份只包含原有通用条件和旧记录，不能序列化临时项目scope'
                    assert path.read_bytes() == initial and posts == []
                    page.goto(base + '/discovery.html?' + generic + '&track=ordinary', wait_until='networkidle')
                    page.wait_for_function('window.DISCOVERY_READY === true')
                    assert page.locator('[data-candidate]').count() == 1
                    assert page.locator('[data-review]').first.is_enabled()
                    page.locator('[data-review]').first.click()
                    page.fill('#review-quote', '更新通用范围结论')
                    page.locator('#review-confirmed').check()
                    page.click('#review-save')
                    page.wait_for_function('document.querySelector("#discovery-message").textContent.includes("已保存")')
                    assert len(posts) == 1 and 'program' not in posts[0] and 'track' not in posts[0]
                    assert path.read_bytes() != initial
                    assert not errors, errors
                    print('PASS: transient programme/special unknown/no legacy rank/filter/review/POST/clear-scope/links; ordinary save unchanged')
                finally:
                    browser.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == '__main__':
    main()

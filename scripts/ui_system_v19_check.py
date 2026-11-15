"""Read-only multi-page visual acceptance with isolated private paths."""
import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.serve import create_server

PAGES = [
    ('start', 'start.html', 'window.START_READY'),
    ('admissions', 'admissions.html?school=bit&dept=cs&year=2027&degree=master&route=exam&track=ordinary', 'window.ADMISSIONS_READY'),
    ('discovery', 'discovery.html', 'window.DISCOVERY_READY'),
    ('opportunities', 'opportunities.html', None),
    ('notices', 'notices.html', None),
    ('detail', 'p/bit-cs-daiqiangqiang.html', None),
    ('compare', 'compare.html', None),
    ('desk', 'desk.html', None),
    ('applications', 'applications.html', None),
    ('board', 'board.html', None),
    ('local', 'local.html', None),
    ('index', 'index.html', None),
    ('coverage', 'coverage.html', None),
    ('release', 'release.html', None),
]

MEASURE = """() => {
 const visible=e=>!!(e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden');
 const info=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {text:e.textContent.trim().slice(0,70),size:parseFloat(s.fontSize),family:s.fontFamily,height:Math.round(r.height),width:Math.round(r.width)}};
 const styles=getComputedStyle(document.documentElement),body=getComputedStyle(document.body);
 const h1=[...document.querySelectorAll('h1')].filter(visible).map(info);
 const headings=[...document.querySelectorAll('h2,h3')].filter(visible).slice(0,20).map(info);
 const controls=[...document.querySelectorAll('main button,main input:not([type=checkbox]):not([type=radio]):not([type=hidden]),main select,.wrap button,.wrap input:not([type=checkbox]):not([type=radio]),.wrap select')].filter(visible).slice(0,150).map(info);
 const overflowing=[...document.querySelectorAll('main *, .wrap *')].filter(e=>{const r=e.getBoundingClientRect();return visible(e)&&r.width&&r.right>innerWidth+2&&!e.closest('.tblcard,.table-scroll,.proof-scroll')}).slice(0,10).map(e=>({tag:e.tagName,id:e.id,class:e.className}));
 return {body:{size:parseFloat(body.fontSize),family:body.fontFamily},h1,headings,controls,viewport:innerWidth,page_width:document.documentElement.scrollWidth,page_height:document.documentElement.scrollHeight,visible_chars:document.body.innerText.length,overflowing,tokens:{body:styles.getPropertyValue('--text-body').trim(),heading:styles.getPropertyValue('--heading-page').trim(),small:styles.getPropertyValue('--text-small').trim()},cards:[...document.querySelectorAll('.results-card,.policy-card,.opportunity-card')].slice(0,4).map(info)};
}"""


def check(base, output, baseline=False):
    output.mkdir(parents=True, exist_ok=True)
    result = {'baseline': baseline, 'private_mutations': False, 'cases': [], 'failures': []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 950})
                context.add_init_script("localStorage.setItem('compare_sel',JSON.stringify(['bit-cs-daiqiangqiang','bit-cs-danchun']))")
                for name, path, ready in PAGES:
                    page = context.new_page()
                    errors, writes = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    def readonly(route):
                        if route.request.method not in ('GET', 'HEAD', 'OPTIONS'):
                            writes.append(route.request.url)
                            route.abort()
                        elif route.request.url.startswith(base):
                            route.continue_()
                        else:
                            route.fulfill(status=200, body='', content_type='image/png')
                    page.route('**/*', readonly)
                    response = page.goto(base + '/' + path, wait_until='networkidle', timeout=45000)
                    if ready:
                        page.wait_for_function(ready, timeout=20000)
                    row = dict(page=name, width=width, status=response.status, final_path=urlsplit(page.url).path,
                               **page.evaluate(MEASURE))
                    page.screenshot(path=str(output/f'{name}-{width}.png'))
                    summary = page.locator('main details>summary:visible, .wrap details>summary:visible').first
                    if summary.count():
                        before = summary.evaluate('(s)=>s.parentElement.open')
                        summary.focus()
                        summary.press('Enter')
                        toggled = summary.evaluate('(s)=>s.parentElement.open') != before
                        summary.press('Enter')
                        row['keyboard_details'] = toggled and summary.evaluate('(s)=>s.parentElement.open') == before
                    else:
                        row['keyboard_details'] = None
                    page.evaluate('document.activeElement?.blur()')
                    page.keyboard.press('Control+Home')
                    page.locator('body').click(position={'x': 1, 'y': 1})
                    page.keyboard.press('Tab')
                    row['keyboard_focus'] = page.evaluate("() => {const e=document.activeElement,s=getComputedStyle(e);return {tag:e.tagName,outline:s.outlineStyle,width:s.outlineWidth,text:e.textContent.trim().slice(0,60)}}")
                    row.update(page_errors=errors, write_requests=writes)
                    failures = []
                    if response.status != 200: failures.append('page did not load')
                    if row['final_path'] != '/' + path.split('?')[0]: failures.append('page redirected; intended screen not verified')
                    if row['page_width'] > width+1: failures.append('page horizontal overflow')
                    if errors: failures.append('page script errors')
                    if writes: failures.append('unexpected write request')
                    if not baseline:
                        if not row['tokens']['body']: failures.append('shared type tokens absent')
                        elif row['body']['size'] != float(row['tokens']['body'].removesuffix('px')): failures.append('body size differs from shared token')
                        if 'sans-serif' not in row['body']['family']: failures.append('body is not sans-serif')
                        expected = float(row['tokens']['heading'].removesuffix('px')) if row['tokens']['heading'] else None
                        if not row['h1']: failures.append('missing page heading')
                        elif expected and any(h['size'] != expected or h['family'] != row['body']['family'] for h in row['h1']): failures.append('page heading differs from type system')
                        if any(c['size'] < 13 for c in row['controls']): failures.append('visible form text below 13px')
                        if row['keyboard_details'] is False: failures.append('details inaccessible by keyboard')
                        if row['keyboard_focus']['tag']=='BODY' or row['keyboard_focus']['outline']=='none': failures.append('keyboard focus not visible')
                    row['failures'] = failures
                    result['cases'].append(row)
                    result['failures'].extend(dict(page=name, width=width, reason=f) for f in failures)
                    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
                    print(json.dumps({'page': name, 'width': width, 'failures': failures}, ensure_ascii=False), flush=True)
                    page.close()
                context.close()
        finally:
            browser.close()
    result['passed'] = not result['failures']
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    if not baseline:
        assert result['passed'], result['failures']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT/'cache/v19/ui-system')
    args = parser.parse_args()
    if args.base:
        check(args.base.rstrip('/'), args.output, args.baseline)
        return
    with tempfile.TemporaryDirectory(prefix='mentor-v19-visual-') as temporary:
        server = create_server(outreach=Path(temporary)/'outreach.yaml', workflow=Path(temporary)/'workflow.yaml', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            check('http://127.0.0.1:'+str(server.server_port), args.output, args.baseline)
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    main()

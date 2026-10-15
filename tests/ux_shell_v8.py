from pathlib import Path
from playwright.sync_api import sync_playwright
import json,sys,tempfile,shutil
from urllib.parse import urlsplit
from jinja2 import Environment,FileSystemLoader
BASE='http://127.0.0.1:18768'
env=Environment(loader=FileSystemLoader('site/templates'),autoescape=True)
prefs={'year':None,'degree':'any','route':'unknown','topics':[],'schools':[],'keep_unknown':True,'modes':{'research':'hard','qualification':'soft','email':'soft','opportunity':'soft','eligibility':'soft'}}
with sync_playwright() as pw:
 b=pw.chromium.launch(headless=True);page=b.new_page(viewport={'width':390,'height':844})
 page.route('**/api/discovery',lambda r:r.fulfill(json={'preferences':prefs,'reviews':{}}))
 if '--baseline' not in sys.argv:
  page.route('**/discovery.html*',lambda r:r.fulfill(body=env.get_template('discovery.html.j2').render(),content_type='text/html'))
 page.goto(BASE+'/discovery.html');page.wait_for_function('window.DISCOVERY_READY')
 box=page.locator('#apply-criteria').bounding_box()
 assert box['y']+box['height']<844, f'Primary action below viewport: {box}'
 assert page.locator('.site-header nav > a').count()==4
 page.screenshot(path='cache/ux_v8/shell/discovery-initial-390.png')
 page.locator('.site-tools summary').focus();page.keyboard.press('Enter')
 assert page.locator('.site-tools-menu').is_visible()
 page.keyboard.press('Enter')
 page.screenshot(path='cache/ux_v8/shell/discovery-initial-390.png')
 page.locator('.site-tools summary').focus();page.keyboard.press('Enter')
 assert page.locator('.site-tools-menu').is_visible()
 page.keyboard.press('Enter')
 # Applied summary must expose filters even when the advanced form is collapsed.
 page.locator('#advanced-criteria summary').click()
 page.select_option('#intent-group','control')
 page.wait_for_function("view.length < window.MENTOR_DATA.length")
 assert '自动化与控制' in page.locator('#intent-summary').inner_text()
 assert page.locator('#criteria-dirty').is_hidden()
 group_summary=page.locator('#intent-summary').inner_text()
 page.select_option('#mode-email','hard');page.locator('#keep-unknown').uncheck()
 assert page.locator('#intent-summary').inner_text()==group_summary
 assert page.locator('#criteria-dirty').is_visible()
 page.locator('#apply-criteria').click();page.wait_for_function("document.querySelector('#criteria-dirty').hidden")
 applied_summary=page.locator('#intent-summary').inner_text()
 assert '公开邮箱：必须' in applied_summary
 assert '不保留必须条件待核实的候选' in applied_summary
 page.locator('#advanced-criteria summary').click()
 assert page.locator('#intent-summary').inner_text()==applied_summary
 # Rendering more candidates cannot read unsubmitted form values.
 page.evaluate("document.querySelector('#intent-group').value='computer';render()")
 assert page.locator('#intent-summary').inner_text()==applied_summary
 page.goto(BASE+'/discovery.html');page.wait_for_function('window.DISCOVERY_READY')
 summary=page.locator('#intent-summary').inner_text()
 page.locator('#intent-topics').fill('graph')
 assert page.locator('#intent-summary').inner_text()==summary
 assert page.locator('#criteria-dirty').is_visible()
 page.locator('#apply-criteria').click();page.wait_for_function("document.querySelector('#criteria-dirty').hidden")
 assert page.locator('#discovery-count').bounding_box()['y']<844
 assert 'graph' in page.locator('#intent-summary').inner_text()
 assert page.locator('.research-preview').count()>0
 page.locator('[data-compare]').first.click()
 assert len(page.evaluate("JSON.parse(localStorage.getItem('compare_sel'))"))==1
 assert page.locator('#compare-selection').is_visible()
 page.locator('[data-compare]').nth(1).click()
 assert '2' in page.locator('#compare-selection').inner_text()
 assert page.locator('#compare-open').get_attribute('href')=='compare.html'
 page.locator('[data-compare]').first.click()
 assert len(page.evaluate("JSON.parse(localStorage.getItem('compare_sel'))"))==1
 for i in range(2,7):page.locator('[data-compare]').nth(i).click()
 assert len(page.evaluate("JSON.parse(localStorage.getItem('compare_sel'))"))==5
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.screenshot(path='cache/ux_v8/shell/discovery-after-390.png')
 page.set_viewport_size({'width':1440,'height':900});page.goto(BASE+'/discovery.html');page.wait_for_function('window.DISCOVERY_READY')
 assert page.locator('#apply-criteria').bounding_box()['y']<900
 page.screenshot(path='cache/ux_v8/shell/discovery-after-1440.png')
 # All API traffic is mocked; tests never touch real private records.
 page.route('**/api/**',lambda r:r.fulfill(json={'ok':False}))
 data=json.loads(Path('site/data.js').read_text(encoding='utf8').split(' = ',1)[1].rstrip(';\n'))
 detail=dict(data[0],provenance={},bio_raw='')
 pages={'compare.html':env.get_template('compare.html.j2').render(),'detail.html':env.get_template('detail.html.j2').render(p=detail),'index.html':env.get_template('index.html.j2').render(profs=data,schools=[],depts=[],titles=[],institutes=[],inst_count=0,fresh='',stale=0)}
 for name,html in pages.items():
  url='/p/detail.html' if name=='detail.html' else '/'+name
  page.route('**'+url,lambda r,request,html=html:r.fulfill(body=html,content_type='text/html'))
 page.evaluate('localStorage.setItem("compare_sel",JSON.stringify(window.MENTOR_DATA.slice(0,5).map(p=>p.page)))')
 for width in [390,1440]:
  page.set_viewport_size({'width':width,'height':844 if width==390 else 900})
  for name in pages:
   page.goto(BASE+('/p/detail.html' if name=='detail.html' else '/'+name));page.wait_for_load_state('networkidle')
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(name,width)
   page.screenshot(path=f'cache/ux_v8/shell/{name[:-5]}-after-{width}.png')
   if name=='detail.html':
    assert not page.locator('#obox').get_attribute('open')
    assert not page.locator('#ob-status').is_visible()
    page.locator('#obox summary').click()
    assert page.locator('#ob-status').is_visible()
   if name=='compare.html':
    assert page.locator('[data-rm]').count()==5
    assert page.locator('.compare-contact').count()==5
    assert page.get_by_text('明确研究方向',exact=True).count()==1
    assert page.get_by_text('检索标签（自动提取）',exact=True).count()==1
 page.goto(BASE+'/compare.html');page.locator('#clear-selection').click()
 assert '0 / 5' in page.locator('#selection-summary').inner_text()
 assert page.locator('#hint').is_visible()
 # Unsupported scope retains unknown and never allows review POST.
 page.goto(BASE+'/discovery.html?school=bit&dept=cs&year=2027&degree=master&route=exam&track=special&program=085400%7Ctest')
 page.wait_for_function('window.DISCOVERY_READY')
 href=page.locator('.results-card .actions a').first.get_attribute('href')
 assert all(key in href for key in ['school=bit','dept=cs','year=2027','track=special','program='])
 assert page.locator('[data-review]').first.is_disabled()
 assert page.locator('#project-context').is_visible()
 assert '招生机会：待核实（项目范围暂不应用规则）' in page.locator('#intent-summary').inner_text()
 assert '不据此排除候选' in page.locator('#intent-summary').inner_text()
 # File mode uses rendered source in an isolated temporary folder, without API writes.
 with tempfile.TemporaryDirectory(prefix='mentor-ux-shell-') as tmp:
  folder=Path(tmp)
  for file in ['data.js','compare-data.js','search.js','discovery.js','discovery-core.js','ui.css']:shutil.copyfile(Path('site')/file,folder/file)
  (folder/'discovery.html').write_text(env.get_template('discovery.html.j2').render(),encoding='utf8')
  page.goto((folder/'discovery.html').as_uri());page.wait_for_function('window.DISCOVERY_READY')
  assert page.locator('#save-criteria').is_disabled()
  assert page.locator('#apply-criteria').is_enabled()
  assert page.locator('.results-card').count()>0
 b.close()
print('shell UX regression passed')

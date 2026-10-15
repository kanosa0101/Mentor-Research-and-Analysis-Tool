"""Read-only public UI flow; generated HTML and private API state stay temporary."""
import json,shutil,sys,tempfile,threading
from pathlib import Path
from jinja2 import Environment,FileSystemLoader
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.serve import create_server

def main():
 out=ROOT/'cache/policy_v21/east/ui';out.mkdir(parents=True,exist_ok=True)
 baseline='--baseline' in sys.argv
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);site=root/'site';site.mkdir()
  for name in ['data.js','compare-data.js','discovery-core.js','discovery.js','ui.css','ui.js','search.js']:
   if (ROOT/'site'/name).exists():shutil.copyfile(ROOT/'site'/name,site/name)
  env=Environment(loader=FileSystemLoader(ROOT/'site/templates'))
  (site/'discovery.html').write_text(env.get_template('discovery.html.j2').render(),encoding='utf8')
  server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0);threading.Thread(target=server.serve_forever,daemon=True).start()
  base=f'http://127.0.0.1:{server.server_port}';results=[]
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch()
    for width in [1440,390]:
     page=browser.new_page(viewport={'width':width,'height':1000 if width==1440 else 844});errors=[]
     page.on('pageerror',lambda e:errors.append(str(e)))
     page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else r.fulfill(status=200,body=''))
     page.goto(base+'/discovery.html',wait_until='domcontentloaded');page.wait_for_function('window.DISCOVERY_READY')
     page.locator('.school-picker').scroll_into_view_if_needed();page.screenshot(path=str(out/f'{"before" if baseline else "after"}-{width}-picker.png'))
     assert page.locator('#school-options input').count()==39
     page.fill('#school-search','上海');assert page.locator('.school-option:visible').count()>=2
     if baseline:
      results.append({'width':width,'baseline_school_search':True,'select_results_present':page.locator('#select-visible-schools').count(),'console_errors':errors});page.close();continue
     page.click('#select-visible-schools');selected=page.locator('#intent-schools option:checked').count();assert selected>=2
     page.click('#clear-school-search');assert page.input_value('#school-search')=='';assert page.locator('.school-option:visible').count()==39
     assert page.locator('#intent-schools option:checked').count()==selected
     page.fill('#school-search','no-such-school');assert page.locator('#select-visible-schools').is_disabled()
     page.click('#clear-school-search')
     school_id=page.locator('#school-options input:not(:checked)').first.get_attribute('value')
     box=page.locator(f'#school-options input[value="{school_id}"]')
     box.focus();box.press('Space');assert page.locator('#intent-schools option:checked').count()==selected+1
     box.press('Space');assert page.locator('#intent-schools option:checked').count()==selected
     page.evaluate('reviewDirty=true')
     page.once('dialog',lambda dialog:dialog.dismiss());box.click()
     assert not box.is_checked();assert page.locator('#intent-schools option:checked').count()==selected
     page.once('dialog',lambda dialog:dialog.dismiss());page.click('#clear-schools')
     assert page.locator('#intent-schools option:checked').count()==selected
     page.evaluate('reviewDirty=false')
     assert page.locator('.school-option').first.evaluate('(node)=>node.getBoundingClientRect().height')>=44
     page.locator('#school-chips button').first.click();assert page.locator('#intent-schools option:checked').count()==selected-1
     page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
     assert page.locator('[data-candidate]').count()>0
     schools=page.evaluate('[...new Set(view.map(r=>r.p.school))]');assert len(schools)==selected-1
     first=page.locator('[data-candidate]').first.get_attribute('data-candidate')
     page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled');assert page.locator('[data-candidate]').first.get_attribute('data-candidate')==first
     page.click('#clear-schools');assert page.locator('#intent-schools option:checked').count()==0
     page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
     assert page.evaluate('view.length')==7173
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
     page.locator('#discovery-results').scroll_into_view_if_needed();page.screenshot(path=str(out/f'after-{width}-results.png'))
     page.goto(base+'/discovery.html?school=zju&dept=cs&year=2027&degree=master&route=exam',wait_until='domcontentloaded');page.wait_for_function('window.DISCOVERY_READY')
     assert page.locator('#intent-schools option:checked').count()==1
     assert page.locator('#intent-schools option:checked').get_attribute('value')=='zju'
     page.fill('#school-search','上海');page.click('#select-visible-schools');assert 'dept=' not in page.url
     page.click('#apply-criteria');page.wait_for_function('!document.querySelector("#apply-criteria").disabled')
     assert page.evaluate('view.some(r=>r.p.school!=="zju")')
     assert not errors,errors
     results.append({'width':width,'multi_select_search_clear_chips':True,'keyboard_space':True,'cancel_unsaved_review_preserves_selection':True,'touch_row_min44':True,'url_context_compatible':True,'stable_repeat':True,'no_horizontal_overflow':True,'console_errors':errors});page.close()
    browser.close()
   assert not list((root/'private').glob('*')), 'browsing must not create private files'
   (out/('baseline-results.json' if baseline else 'results.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
   print(json.dumps(results))
  finally:server.shutdown();server.server_close()
if __name__=='__main__':main()

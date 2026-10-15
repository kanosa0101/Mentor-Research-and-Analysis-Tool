"""Policy-only unit discovery regression on actual generated public data; isolated private files."""
import json,shutil,sys,tempfile,threading
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.serve import create_server

def main():
 out=ROOT/'cache/policy_v18/product_audit/discovery_units';out.mkdir(parents=True,exist_ok=True)
 raw=(ROOT/'site/admissions-data.js').read_text(encoding='utf-8');data=json.loads(raw[raw.index('=')+1:].strip().rstrip(';'))
 units={u['dept']:u for u in data['units'] if u['school']=='tju'}
 assert all(d in units for d in ['software','cyber','ai']), 'Wait for integration build with actual three TJU units'
 assert all(units[d]['count']==0 and units[d]['roster_pending'] for d in ['software','cyber','ai'])
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);site=root/'site';site.mkdir()
  for name in ['discovery.html','discovery.js','discovery-core.js','ui.css','data.js','search.js','compare-data.js','admissions-data.js']:
   shutil.copy2(ROOT/'site'/name,site/name)
  server=create_server(site=site,outreach=root/'private/outreach.yaml',port=0);threading.Thread(target=server.serve_forever,daemon=True).start()
  results=[];failures=[]
  try:
   with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True)
    for dept,kind in [('software','known'),('cyber','known'),('ai','known'),('missing-v18','unknown'),('software','catalog503'),('cs','existing')]:
     for width in [1440,390]:
      page=browser.new_page(viewport={'width':width,'height':1000 if width==1440 else 844});errors=[];requests=[]
      page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url) if 'admissions-data.js' in r.url else None)
      if kind=='catalog503':page.route('**/admissions-data.js*',lambda route:route.fulfill(status=503,body='offline'))
      q=urlencode(dict(school='tju',dept=dept,year=2027,degree='phd',route='assessment',track='ordinary',notes='private-sentinel-v18',topic='private-topic-v18'))
      page.goto(f'http://127.0.0.1:{server.server_port}/discovery.html?{q}',wait_until='networkidle');page.wait_for_function('window.DISCOVERY_READY === true')
      context=page.locator('#unit-context').inner_text();links=page.locator('a[href]').evaluate_all('(rows)=>rows.map(a=>a.getAttribute("href"))');overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
      row={'dept':dept,'kind':kind,'width':width,'context':context,'catalog_requests':requests,'errors':errors,'overflow':overflow,'public_admissions_links':[x for x in links if x.startswith('admissions.html')]}
      if kind=='known':
       roster=page.locator('#unit-roster-direct')
       if roster.count()!=1 or roster.get_attribute('href')!=units[dept]['roster_url']:failures.append(f'{dept}/{width}: no direct verified faculty entry')
       if not ('天津大学' in context and units[dept]['dept_name'] in context and units[dept]['roster_pending'] in context):failures.append(f'{dept}/{width}: known policy-only unit not named/pending')
       if len(requests)!=1:failures.append(f'{dept}/{width}: expected one lazy catalog load')
       title=page.evaluate('g=>projectGoalText({goal_snapshot:g})',dict(school_id='tju',dept_id=dept,year=2027,degree='phd',route='assessment',track='ordinary',program_code='',program_name=''))
       row['project_goal_text']=title
       if units[dept]['dept_name'] not in title:failures.append(f'{dept}/{width}: project goal raw dept id')
      elif kind=='existing':
       if requests:failures.append(f'{dept}/{width}: existing teacher page loaded catalog')
       if '计算机科学与技术学院' not in context:failures.append(f'{dept}/{width}: existing context changed')
      else:
       if page.locator('#unit-roster-direct').count():failures.append(f'{dept}/{width}/{kind}: unverified faculty entry shown')
       if '当前导师库暂无该单位记录' not in context:failures.append(f'{dept}/{width}/{kind}: unknown fallback missing')
       if kind=='catalog503' and ('已接入' in context or '名册尚未采集' in context):failures.append(f'{width}: failed catalog asserted connection')
       if not page.locator('#unit-context a[href^="admissions.html"]').count():failures.append(f'{dept}/{width}/{kind}: no return link')
      if errors:failures.append(f'{dept}/{width}: JS errors')
      if overflow:failures.append(f'{dept}/{width}: horizontal overflow')
      if any('private-sentinel' in x or 'private-topic' in x or 'notes=' in x or 'topic=' in x for x in row['public_admissions_links']):failures.append(f'{dept}/{width}: private input leaked in public links')
      (out/f'{dept}_{kind}_{width}.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
      if kind in ['known','catalog503']:page.screenshot(path=str(out/f'{dept}_{kind}_{width}.png'))
      results.append(row);page.close()
    browser.close()
  finally:server.shutdown();server.server_close()
 (out/'results.json').write_text(json.dumps({'payload_units':len(data['units']),'cases':results,'failures':failures},ensure_ascii=False,indent=2),encoding='utf-8')
 assert not failures,'\n'.join(failures)
 print('PASS: actual 3 TJU policy-only units, unknown/503 fallback, existing-unit lazy loading, goal names, links, 1440/390')
if __name__=='__main__':main()

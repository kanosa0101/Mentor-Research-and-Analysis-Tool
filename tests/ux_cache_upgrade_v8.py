"""Reuse one browser context with warm v0.8 asset caches before loading v0.9 templates."""
import json,re,shutil,tempfile,threading
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from jinja2 import Environment,FileSystemLoader
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'cache/ux_v9/integration';OUT.mkdir(parents=True,exist_ok=True)
env=Environment(loader=FileSystemLoader(ROOT/'site/templates'),autoescape=True)
for template in (ROOT/'site/templates').glob('*.j2'):
 for asset in re.findall(r'<script src="([^"]+)"',template.read_text(encoding='utf8')):
  assert asset.endswith('?v=20261015-9'),(template.name,asset)
assert 'ui.css?v=20261015-9' in (ROOT/'site/templates/_ui_head.html.j2').read_text(encoding='utf8')
assert 'search.js?v=20261015-9' in (ROOT/'site/templates/index.html.j2').read_text(encoding='utf8')
prefs={'year':None,'degree':'any','route':'unknown','topics':[],'schools':[],'keep_unknown':True,'modes':{'research':'hard','qualification':'soft','email':'soft','opportunity':'soft','eligibility':'soft'}}
with tempfile.TemporaryDirectory(prefix='mentor-cache-upgrade-') as tmp:
 folder=Path(tmp)
 for path in (ROOT/'site').glob('*.js'):shutil.copyfile(path,folder/path.name)
 shutil.copyfile(ROOT/'site/ui.css',folder/'ui.css')
 (folder/'discovery.html').write_text(env.get_template('discovery.html.j2').render(),encoding='utf8')
 scripts=['data.js','discovery-core.js','discovery.js','search.js','compare-data.js','admissions-data.js','admissions-core.js','admissions.js','desk.js','workflow.js']
 (folder/'warm.html').write_text('<link rel="stylesheet" href="ui.css?v=20261015-8">'+''.join(f'<script src="{name}?v=20261015-8"></script>' for name in scripts),encoding='utf8')
 state={'old':True};requests=[]
 class Handler(SimpleHTTPRequestHandler):
  def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(folder),**kwargs)
  def log_message(self,*args):pass
  def do_GET(self):
   requests.append(self.path)
   path=urlsplit(self.path).path
   if path=='/api/discovery':
    body=json.dumps({'preferences':prefs,'reviews':{}}).encode();self.send_response(200);self.end_headers();self.wfile.write(body);return
   if state['old'] and path.endswith(('.js','.css')):
    body=("window.OLD_ASSETS=(window.OLD_ASSETS||0)+1;" if path.endswith('.js') else 'body{background:rgb(255,0,255)!important}').encode()
    self.send_response(200);self.send_header('Cache-Control','public, max-age=31536000');self.send_header('Content-Type','text/javascript' if path.endswith('.js') else 'text/css');self.end_headers();self.wfile.write(body);return
   super().do_GET()
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':390,'height':844})
   base=f'http://127.0.0.1:{server.server_port}'
   page.goto(base+'/warm.html');page.wait_for_load_state('networkidle');assert page.evaluate('OLD_ASSETS')==len(scripts)
   state['old']=False;page.goto(base+'/discovery.html');page.wait_for_function('window.DISCOVERY_READY',timeout=5000)
   assert page.locator('.research-preview').count()>0
   assert page.evaluate('getComputedStyle(document.body).backgroundColor')!='rgb(255, 0, 255)'
   page.fill('#intent-topics','graph');page.click('#apply-criteria');page.wait_for_function("document.querySelector('#intent-summary').textContent.includes('graph')")
   assert any(url.startswith('/search.js?v=') for url in requests)
   assert any(url.startswith('/compare-data.js?v=') for url in requests)
   assert page.evaluate('window.OLD_ASSETS === undefined')
   page.screenshot(path=str(OUT/'cache-upgrade-390.png'));browser.close()
  (OUT/'cache-upgrade-requests.json').write_text(json.dumps(requests,indent=2),encoding='utf8')
  print('PASS: warm legacy JS/CSS cache upgraded in same browser context, including dynamic search/compare data')
 finally:server.shutdown();server.server_close();thread.join()

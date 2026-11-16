"""Exercise online account/library/project/material UI using isolated data directories."""
import ipaddress,json,shutil,ssl,sys,tempfile,threading
from datetime import datetime,timedelta,timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from scripts import serve_public,build_site
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'cache/online-ux/flow';out.mkdir(parents=True,exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='ui-',dir=out))
shutil.copytree(ROOT/'site',root/'site')
(root/'data').mkdir()
for name in ['opportunities.json','admissions.yaml','admissions_entries.yaml','admissions_checks.json','schools.yaml']:
 shutil.copyfile(ROOT/'data'/name,root/'data'/name)
# Render directly from current source templates; do not modify the shared generated pages.
env=build_site.template_environment()
for name in ['start','desk','applications','account','local','opportunities','board']:
 (root/'site'/f'{name}.html').write_text(env.get_template(name+'.html.j2').render(),encoding='utf8')
(root/'site/discovery.html').write_text(build_site.render_discovery_page(root/'site',env),encoding='utf8')
# Exercise the same HTTPS protocol and Secure cookie behavior used in production.
key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'127.0.0.1')]);now=datetime.now(timezone.utc)
cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256())
cert_path,key_path=root/'test-cert.pem',root/'test-key.pem';cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM));key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
server=serve_public.create_server(root,'127.0.0.1',0);tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert_path,key_path);server.socket=tls.wrap_socket(server.socket,server_side=True,do_handshake_on_connect=False)
threading.Thread(target=server.serve_forever,daemon=True).start();base=f'https://127.0.0.1:{server.server_port}'
result={'isolated_root':str(root),'protocol':'https','certificate':'self-signed test fixture; browser trust errors ignored only for this isolated fixture','checks':[]}
try:
 with sync_playwright() as pw:
  browser=pw.chromium.launch(args=["--explicitly-allowed-ports="+str(server.server_port)]);ctx=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':980});page=ctx.new_page();errors=[];requests=[]
  page.on('pageerror',lambda error:errors.append(str(error)));page.on('request',lambda request:requests.append(request.url))
  page.goto(base+'/account.html?next=/applications.html?mentor=bit-cs-danchun%26school=bit%26dept=cs',wait_until='networkidle')
  page.locator('[data-account-mode=register]').click();page.locator('#account-username').fill('ux_flow_user');page.locator('#account-password').fill('test-password-long-a');page.locator('#account-confirm').fill('test-password-long-a');page.locator('#account-submit').click();page.wait_for_url(lambda url:'/applications.html?' in url);page.wait_for_function('window.WORKFLOW_READY')
  page.locator('#project-name').fill('我的申请');assert page.locator('#project-goal-details').get_attribute('open') is None
  page.screenshot(path=str(out/'create-desktop.png'),full_page=True)
  result['create_button_bottom']=page.locator('#project-save').bounding_box()['y']+page.locator('#project-save').bounding_box()['height']
  page.locator('#project-save').click();page.wait_for_function('Object.keys(WORKFLOW.projects).length===1&&!actionBusy');project=page.evaluate('Object.keys(WORKFLOW.projects)[0]')
  assert page.locator('#filter-project').input_value()==project;assert page.evaluate('chosen.communication')==['bit-cs-danchun'];assert page.evaluate('chosen.material')==['bit-cs-danchun'];assert 'project='+project in page.url
  assert page.locator('#project-next').is_visible();result['checks'].append('project_creation_keeps_project_and_mentor_and_next_actions')
  page.locator('#project-next [data-section=material]').click();assert page.locator('#material-projects').evaluate('(n)=>[...n.selectedOptions].map(o=>o.value)')==[project]
  page.locator('#material-file').set_input_files({'name':'CV.txt','mimeType':'text/plain','buffer':b'private application material'})
  page.locator('#material-title').fill('申请简历')
  page.evaluate("""()=>{window.uxFetch=window.fetch;window.uxUploads=0;window.fetch=(url,options)=>String(url).includes('/api/materials/upload')?(window.uxUploads++,new Promise(resolve=>window.uxFail=()=>resolve(new Response(JSON.stringify({error:'测试：网络失败，请重试'}),{status:503,headers:{'Content-Type':'application/json'}})))):window.uxFetch(url,options)}""")
  page.locator('#material-save').click();assert page.locator('#material-save').inner_text()=='正在上传…';assert page.locator('#workspace').evaluate('(n)=>n.disabled')
  page.locator('#material-form').dispatch_event('submit');assert page.evaluate('window.uxUploads')==1
  page.evaluate('window.uxFail()');page.wait_for_function('!actionBusy');assert page.locator('#material-title').input_value()=='申请简历';assert page.locator('#material-file').evaluate('(n)=>n.files.length')==1;assert not page.evaluate('Object.keys(WORKFLOW.materials).length');result['checks'].append('upload_busy_blocks_duplicate_and_failure_keeps_file_and_fields')
  page.evaluate('()=>{window.fetch=window.uxFetch}');page.locator('#material-save').click();page.wait_for_function('Object.keys(WORKFLOW.materials).length===1&&!actionBusy')
  assert page.locator('#filter-project').input_value()==project;assert page.evaluate('Object.values(WORKFLOW.materials)[0].project_ids')==[project];assert page.evaluate('Object.values(WORKFLOW.materials)[0].mentor_ids')==['bit-cs-danchun'];result['checks'].append('upload_uses_current_project_and_mentor_without_reselecting')
  page.locator('.section-tabs [data-section=communication]').click();assert page.locator('#communication-project').input_value()==project;assert page.evaluate('chosen.communication')==['bit-cs-danchun'];assert page.locator('#communication-kind').input_value()=='note'
  page.locator('#communication-subject').fill('第一次联系');page.locator('#communication-content').fill('已咨询老师的研究安排')
  page.locator('#communication-save').click();page.wait_for_function('Object.keys(WORKFLOW.communications).length===1&&!actionBusy');assert page.evaluate('Object.values(WORKFLOW.communications)[0].project_id')==project;assert page.evaluate('Object.values(WORKFLOW.communications)[0].kind')=='note';result['checks'].append('communication_uses_context_without_researching_mentor_or_claiming_sent')
  assert not [url for url in requests if '/api/workflow/material-tasks' in url];result['checks'].append('hidden_preparation_panel_makes_no_requests')
  page.locator('.section-tabs [data-section=preparation]').click();page.wait_for_function('document.querySelector("#preparation-list").textContent.length>0');page.wait_for_timeout(300)
  assert len([url for url in requests if '/api/workflow/material-tasks' in url])==1;result['checks'].append('opening_preparation_loads_once')
  page.locator('.section-tabs [data-section=material]').click()
  for width in (320,390,1440):
   page.set_viewport_size({'width':width,'height':980});page.evaluate('scrollTo(0,0)');assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(out/f'materials-{width}.png'),full_page=True)
  page.set_viewport_size({'width':390,'height':980});page.evaluate('scrollTo(0,0)');result['mobile_file_top']=page.locator('#material-file').bounding_box()['y'];result['mobile_upload_bottom']=page.locator('#material-save').bounding_box()['y']+page.locator('#material-save').bounding_box()['height'];assert result['mobile_upload_bottom']<980;assert page.locator('#material-details').get_attribute('open') is None
  result['checks'].append('material_layout_320_390_1440_without_horizontal_overflow')
  multi=page.evaluate("""async()=>{const r=await fetch('/api/workflow/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'多导师项目',mentor_ids:['bit-cs-danchun','bit-cs-dinggangyi']})});if(!r.ok)throw new Error(await r.text());return (await r.json()).id}""")
  page.goto(base+'/applications.html?section=communication&project='+multi,wait_until='networkidle');page.wait_for_function('window.WORKFLOW_READY');assert not page.evaluate('chosen.communication');assert not page.evaluate('chosen.material');result['checks'].append('multiple_mentors_require_explicit_choice')
  assert not errors,errors;result['passed']=True;result['no_page_errors']=True;browser.close()
finally:
 server.shutdown();server.server_close();(out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False))

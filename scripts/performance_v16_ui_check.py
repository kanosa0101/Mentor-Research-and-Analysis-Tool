"""Real filtering/comparison/navigation flows with bounded public transfers."""
import argparse
import json
import sys
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import serve_public


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base')
    parser.add_argument('--output',default=str(ROOT/'cache/v16/performance-ui'))
    args=parser.parse_args();output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    server=None
    if not args.base:
        server=serve_public.create_server(ROOT,'127.0.0.1',0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=args.base.rstrip('/') if args.base else f'http://127.0.0.1:{server.server_port}';cases=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            for width in (1440,390):
                context=browser.new_context(viewport={'width':width,'height':900});page=context.new_page();errors=[];requests=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda req:requests.append(req.url))
                start=time.monotonic();page.goto(base+'/discovery.html',wait_until='load');page.wait_for_function('window.DISCOVERY_READY')
                ready=round((time.monotonic()-start)*1000)
                page.locator('#intent-topics').fill('计算机视觉')
                with page.expect_response(lambda response:'/api/mentor-search?' in response.url and response.status==200):
                    page.locator('#apply-criteria').click()
                page.wait_for_function('!document.getElementById("apply-criteria").disabled')
                assert page.locator('[data-candidate]').count()>1
                for index in range(2):page.locator('[data-compare]').nth(index).click()
                page.goto(base+'/compare.html',wait_until='load');page.locator('.pcol').nth(1).wait_for()
                assert page.locator('.pcol').count()==2
                page.screenshot(path=str(output/f'compare-{width}.png'))
                page.go_back(wait_until='load');page.wait_for_function('window.DISCOVERY_READY')
                assert page.locator('#intent-topics').input_value()=='计算机视觉'
                assert not any('/search.js' in u or '/compare-data.js' in u or '/data.js' in u for u in requests)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.screenshot(path=str(output/f'discovery-{width}.png'))
                assert not errors,errors
                cases.append({'width':width,'initial_ready_ms':ready,'search_api':True,'compare_subset':True,'back_restores_filters':True,'no_full_search_or_compare_assets':True,'page_errors':errors})
                context.close()
            browser.close()
    finally:
        if server:
            server.shutdown();server.server_close();thread.join(timeout=5)
    (output/'results.json').write_text(json.dumps({'passed':True,'cases':cases},indent=2),encoding='utf-8')
    print(json.dumps(cases))


if __name__=='__main__':main()

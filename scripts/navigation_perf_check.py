"""Measure real navigation readiness and cache transfers without private writes."""
import argparse
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(); output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    results=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        context=browser.new_context(viewport={'width':390,'height':844});page=context.new_page()
        errors=[];page.on('pageerror',lambda error: errors.append(str(error)))
        for repeat in (False,True):
            for name,ready in [('start','window.START_READY'),('discovery','window.DISCOVERY_READY'),
                               ('admissions','window.ADMISSIONS_DATA'),('notices','document.querySelector("#count")?.textContent')]:
                started=time.monotonic()
                page.goto(args.base.rstrip('/')+'/'+name+'.html',wait_until='load',timeout=90000)
                page.wait_for_function(ready,timeout=30000)
                row={'page':name,'repeat':repeat,'ready_ms':round((time.monotonic()-started)*1000),
                     'resources':page.evaluate('performance.getEntriesByType("resource").map(r=>({name:r.name.split("/").pop(),bytes:r.transferSize,decoded:r.decodedBodySize,ms:Math.round(r.duration)}))')}
                results.append(row);output.write_text(json.dumps({'results':results,'page_errors':errors},indent=2),encoding='utf-8')
                print(name,repeat,row['ready_ms'],flush=True)
        browser.close()
    assert not errors,errors


if __name__=='__main__':main()

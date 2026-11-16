"""Anonymous GET-only cold-open and same-session navigation measurements.

Fresh Chromium processes isolate browser caches/connections; OS DNS state is not
reset. No request interception: the browser keeps normal HTTP cache semantics.
Every sample (including failures) and every completed resource timing is saved.
"""
import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

READY = {'start.html':'window.START_READY', 'discovery.html':'window.DISCOVERY_READY',
         'admissions.html':'window.ADMISSIONS_READY', 'opportunities.html':'window.opportunityModeReady || (typeof opportunityModeReady!=="undefined" && opportunityModeReady)'}
GUARD = """(() => {
  performance.setResourceTimingBufferSize(1000);
  window.__auditBlocked=[];window.__auditLcp=[];
  const check=method=>{if(!['GET','HEAD'].includes(String(method||'GET').toUpperCase())){
    window.__auditBlocked.push(String(method));throw new Error('Read-only audit blocked a write');}};
  const fetch=window.fetch;window.fetch=function(input,options={}){check(options.method||input?.method);return fetch.call(this,input,options);};
  const open=XMLHttpRequest.prototype.open;XMLHttpRequest.prototype.open=function(method,...args){check(method);return open.call(this,method,...args);};
  navigator.sendBeacon=()=>{check('BEACON');return false;};
  HTMLFormElement.prototype.submit=function(){check('FORM');};
  document.addEventListener('submit',e=>{e.preventDefault();window.__auditBlocked.push('FORM');},true);
  try{new PerformanceObserver(list=>window.__auditLcp.push(...list.getEntries().map(e=>({startTime:e.startTime,size:e.size})))).observe({type:'largest-contentful-paint',buffered:true});}catch{}
})();"""


def aggregate(samples):
    groups={}
    for row in samples:
        key=row['kind']+':'+row['path']
        group=groups.setdefault(key,{'samples':0,'passed':0,'ready_seconds':[]})
        group['samples']+=1;group['passed']+=bool(row.get('passed'))
        if row.get('ready_seconds') is not None:
            group['ready_seconds'].append(row['ready_seconds'])
    for group in groups.values():
        values=group['ready_seconds']
        group['ready_statistics']=dict(min=min(values),median=statistics.median(values),max=max(values)) if values else None
    return groups


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',default='https://8.213.137.82:8443')
    parser.add_argument('--rounds',type=int,default=3)
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'cache/v1116/public-performance')
    parser.add_argument('--width',type=int,default=1440)
    parser.add_argument('--height',type=int,default=1000)
    args=parser.parse_args()
    if not 1<=args.rounds<=10:
        parser.error('rounds must be 1..10')
    args.output.mkdir(parents=True,exist_ok=True)
    report=dict(started_at=datetime.now(timezone.utc).isoformat(),origin=args.base.rstrip('/'),
        viewport=dict(width=args.width,height=args.height),rounds=args.rounds,samples=[],
        definition='Each round: fresh-browser start + same-session nav/return; separate fresh-browser discovery. OS DNS cache unchanged. No account writes.',
        timing_note='TLS is included in connect_ms. TTFB includes connection; request_to_first_byte is network+server wait, not pure server CPU.')

    def save():
        report['summary']=aggregate(report['samples'])
        (args.output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

    with sync_playwright() as pw:
        for round_index in range(1,args.rounds+1):
            for session,paths in [('journey',['start.html','discovery.html','admissions.html','opportunities.html','start.html']),
                                  ('discovery-cold',['discovery.html'])]:
                browser=pw.chromium.launch(args=['--no-proxy-server'])
                context=browser.new_context(viewport=report['viewport'])
                context.add_init_script(GUARD)
                page=context.new_page();active=None;owners={};network_owners={}
                cdp=context.new_cdp_session(page);cdp.send('Network.enable')

                def requested(request):
                    owners[request]=active
                    if active is not None and request.method not in ('GET','HEAD'):
                        active['unexpected_writes'].append({'url':request.url,'method':request.method})

                def failed(request):
                    owner=owners.get(request)
                    if owner is not None:owner['failed_requests'].append({'url':request.url,'error':request.failure})

                def network_started(event):
                    network_owners[event['requestId']]=active

                def network_response(event):
                    owner=network_owners.get(event['requestId'])
                    if owner is not None:
                        response=event['response']
                        owner['responses'].append({key:response.get(key) for key in ('url','status','mimeType','protocol',
                            'connectionId','connectionReused','fromDiskCache','fromServiceWorker','remoteIPAddress','remotePort','timing')})
                        if response['status']>=400:
                            owner['http_errors'].append({'url':response['url'],'status':response['status']})

                page.on('request',requested);page.on('requestfailed',failed)
                page.on('pageerror',lambda error:active['page_errors'].append(str(error)) if active is not None else None)
                cdp.on('Network.requestWillBeSent',network_started);cdp.on('Network.responseReceived',network_response)
                try:
                    for index,path in enumerate(paths):
                        kind='cold' if index==0 else 'warm_return' if index==len(paths)-1 else 'navigation'
                        active=dict(round=round_index,session=session,path=path,kind=kind,observed_at=datetime.now(timezone.utc).isoformat(),
                                    page_errors=[],failed_requests=[],http_errors=[],unexpected_writes=[],responses=[])
                        report['samples'].append(active)
                        started=time.perf_counter()
                        try:
                            if index==0:
                                response=page.goto(report['origin']+'/'+path,wait_until='domcontentloaded',timeout=45000)
                            else:
                                with page.expect_navigation(wait_until='domcontentloaded',timeout=45000) as navigation:
                                    page.locator('.site-header nav a[href="'+path+'"]').click()
                                response=navigation.value
                            active['html_status']=response.status
                            page.wait_for_function(READY[path],timeout=25000)
                            active['ready_seconds']=round(time.perf_counter()-started,3)
                            active['anonymous_verified']=page.evaluate('async()=>{await OnlineAccount.ready;return OnlineAccount.state.authenticated===false;}')
                            page.wait_for_timeout(500)  # Collect late timing entries; excluded from ready_seconds.
                            active['performance']=page.evaluate("""()=>{
                              const n=performance.getEntriesByType('navigation')[0],resources=performance.getEntriesByType('resource');
                              return {navigation:n.toJSON(),resources:resources.map(r=>r.toJSON()),paint:performance.getEntriesByType('paint').map(e=>e.toJSON()),
                                lcp:window.__auditLcp,blocked_writes:window.__auditBlocked,segments:{
                                  dns_ms:n.domainLookupEnd-n.domainLookupStart,connect_ms:n.connectEnd-n.connectStart,
                                  tls_ms:n.secureConnectionStart?n.connectEnd-n.secureConnectionStart:null,
                                  request_to_first_byte_ms:n.responseStart-n.requestStart,ttfb_ms:n.responseStart-n.startTime,
                                  response_body_ms:n.responseEnd-n.responseStart,dom_content_loaded_ms:n.domContentLoadedEventEnd},
                                html_transfer_bytes:n.transferSize,resource_transfer_bytes:resources.reduce((s,r)=>s+r.transferSize,0),
                                cached_resources:resources.filter(r=>r.transferSize===0&&r.decodedBodySize>0).length,
                                full_discovery_fallback:resources.some(r=>/discovery-data\\.js/.test(r.name)),
                                viewport_width:innerWidth,scroll_width:document.documentElement.scrollWidth};
                            }""")
                            if round_index==1:
                                filename=f'{session}-{index}-{path[:-5]}-{args.width}.png'
                                page.evaluate('scrollTo(0,0)');page.screenshot(path=str(args.output/filename))
                                active['screenshot']=filename
                            active['passed']=bool(response.ok and active['anonymous_verified'] and not active['page_errors'] and
                                not active['failed_requests'] and not active['http_errors'] and not active['unexpected_writes'] and not active['performance']['blocked_writes'])
                        except Exception as error:
                            active.update(passed=False,error=type(error).__name__,message=str(error)[:500],elapsed_seconds=round(time.perf_counter()-started,3))
                            try:
                                active['navigation_on_failure']=page.evaluate('performance.getEntriesByType("navigation").map(n=>n.toJSON())')
                            except Exception:
                                active['navigation_on_failure']=[]
                        finally:
                            save();print(round_index,session,path,active.get('ready_seconds'),active['passed'],flush=True)
                finally:
                    browser.close();save()
    report['completed_at']=datetime.now(timezone.utc).isoformat()
    report['passed']=all(row.get('passed') for row in report['samples'])
    save()
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())

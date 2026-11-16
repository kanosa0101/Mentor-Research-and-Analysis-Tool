import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts import public_performance_v1116 as measurement


@pytest.mark.parametrize('attempt_write',[False,True])
def test_measurement_retains_all_rounds_timing_cache_and_blocks_writes(tmp_path,monkeypatch,attempt_write):
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):
            requests.append(('GET',self.path))
            if self.path=='/api/auth/me':
                content=b'{"authenticated":false,"csrf_token":"FIXTURE_NOT_CAPTURED"}'
                mime='application/json'
            elif self.path=='/fixture.css':
                content=b'body{color:#234;font:16px sans-serif}'
                mime='text/css'
            else:
                nav=''.join(f'<a href="{path}">{path}</a>' for path in measurement.READY)
                guarded="try{fetch('/api/write',{method:'POST'});}catch{}" if attempt_write else ''
                content=('<html><head><link rel="stylesheet" href="/fixture.css"></head><body><header class="site-header"><nav>'+nav+
                    '</nav></header><h1>Public performance fixture</h1><script>window.START_READY=true;window.DISCOVERY_READY=true;window.ADMISSIONS_READY=true;window.opportunityModeReady=true;'
                    'window.OnlineAccount={state:{},ready:fetch("/api/auth/me").then(r=>r.json()).then(d=>Object.assign(OnlineAccount.state,d))};'+guarded+'</script></body></html>').encode()
                mime='text/html; charset=utf-8'
            self.send_response(200);self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(content)))
            if self.path=='/fixture.css':self.send_header('Cache-Control','public,max-age=3600')
            self.end_headers();self.wfile.write(content)
        def do_POST(self):
            requests.append(('POST',self.path));self.send_response(500);self.send_header('Content-Length','0');self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    monkeypatch.setattr(sys,'argv',['measure','--base',f'http://127.0.0.1:{server.server_port}','--rounds','1','--output',str(tmp_path)])
    try:
        assert measurement.main()==int(attempt_write)
    finally:
        server.shutdown();server.server_close()
    report=json.loads((tmp_path/'result.json').read_text(encoding='utf-8'))
    assert len(report['samples'])==6 and all(row['anonymous_verified'] for row in report['samples'])
    assert {row['kind'] for row in report['samples']}=={'cold','navigation','warm_return'}
    assert all('request_to_first_byte_ms' in row['performance']['segments'] for row in report['samples'])
    assert any(row['performance']['cached_resources']>0 for row in report['samples'] if row['kind']=='navigation')
    assert all(method=='GET' for method,_ in requests)
    assert 'FIXTURE_NOT_CAPTURED' not in json.dumps(report)
    if attempt_write:
        assert all(row['performance']['blocked_writes']==['POST'] for row in report['samples'])
        assert not report['passed']
    else:
        assert report['passed'] and all(row['responses'] for row in report['samples'])

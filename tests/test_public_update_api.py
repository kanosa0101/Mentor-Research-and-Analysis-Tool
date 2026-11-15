"""Local update authorization, serialization and public snapshot HTTP contracts."""
import http.client
import json
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts import serve, serve_public
from crawler import public_snapshot


class UpdateAPITests(unittest.TestCase):
    def test_local_update_is_explicit_same_origin_and_blocks_concurrent_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'site').mkdir(); (root/'data').mkdir()
            private = root/'data/workflow.yaml'; private.write_text('private snapshot')
            server = serve.create_server(root/'site', root/'data/outreach.yaml', 0, private)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            entered, finish = threading.Event(), threading.Event()
            def request(path, method='GET', body=None, headers=None):
                with closing(http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)) as connection:
                    connection.request(method,path,body,headers or {})
                    response=connection.getresponse(); return response.status,json.loads(response.read())
            def job(*args):
                entered.set(); finish.wait(5); return {'id':'a'*64}
            try:
                with patch.object(serve,'ROOT',root), patch.object(serve.public_update,'update',side_effect=job) as update:
                    self.assertEqual(request('/api/public-data')[1]['mode'],'local');update.assert_not_called()
                    self.assertEqual(request('/api/public-data/update','POST','{}',{'Content-Type':'application/json','Origin':'https://other.test'})[0],403)
                    self.assertEqual(request('/api/public-data/update','POST','{}')[0],415)
                    headers={'Content-Type':'application/json'}
                    self.assertEqual(request('/api/public-data/update','POST',json.dumps({'id':'a'*64}),headers)[0],202)
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(request('/api/public-data/update','POST',json.dumps({'id':'a'*64}),headers)[0],409)
                    self.assertEqual(request('/api/workflow/projects','POST','{}',headers)[0],503)
                    self.assertEqual(request('/api/workflow')[0],503)
                    self.assertTrue(request('/api/public-data')[1]['busy'])
                    finish.set()
                    for _ in range(100):
                        if not serve._public_update['busy']:break
                        time.sleep(.01)
                    self.assertEqual(request('/api/public-data')[1]['result']['id'],'a'*64)
                    update.assert_called_once()
                self.assertEqual(private.read_text(),'private snapshot')
            finally:
                finish.set();server.shutdown();server.server_close();thread.join()
                serve._public_update.update(busy=False,message='',result=None)

    def test_online_site_retires_client_update_and_archives_even_when_present(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'VERSION').write_text('1.5.0')
            for name in public_snapshot.FIXED | {'data/professors/demo/cs/name.yaml'}:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
            (root/'data/workflow.yaml').write_text('private snapshot')
            expected=public_snapshot.build(root)
            (root/'site').mkdir()
            (root/'site/public-data.js').write_text('retired-client-script')
            server=serve_public.create_server(root,'127.0.0.1',0)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                for path in ('/api/public-data', expected['archive'], '/public-data.js'):
                    for method in ('GET', 'HEAD'):
                        with closing(http.client.HTTPConnection('127.0.0.1',server.server_port)) as connection:
                            connection.request(method,path);response=connection.getresponse()
                            self.assertEqual(response.status,410)
                            raw=response.read()
                            self.assertNotIn(b'private snapshot',raw)
                            self.assertNotIn(b'retired-client-script',raw)
                            self.assertEqual(response.getheader('Cache-Control'),'no-store')
                            if method=='HEAD':self.assertEqual(raw,b'')
                for path in ('/api/public-data/check','/api/public-data/update'):
                    with closing(http.client.HTTPConnection('127.0.0.1',server.server_port)) as connection:
                        connection.request('POST',path,'{}',{'Content-Type':'application/json'})
                        response=connection.getresponse();self.assertEqual(response.status,410);response.read()
                self.assertEqual((root/'data/workflow.yaml').read_text(),'private snapshot')
            finally:
                server.shutdown();server.server_close();thread.join()

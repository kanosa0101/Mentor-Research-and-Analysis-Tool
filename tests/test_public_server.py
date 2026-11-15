import http.client
import gzip
import json
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from scripts import serve_public


class PublicServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mentor-public-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.site / 'p').mkdir()
        for name, body in [('opportunities.html', '<h1>Public opportunities</h1>'),
                           ('start.html', '<h1>Application start</h1>'),
                           ('review.html', '<h1>Local review only</h1>'),
                           ('review.js', 'localReview=true;'),
                           ('ui.css', 'body{color:green}'), ('data.js', 'window.DATA=[];'),
                           ('p/mentor.html', '<h1>Public mentor</h1>')]:
            (self.site / name).write_text(body, encoding='utf-8')
        (self.root / 'data').mkdir()
        (self.root / 'data/opportunities.json').write_text(json.dumps({'version': 1, 'opportunities': []}), encoding='utf-8')
        (self.root / 'data/workflow.yaml').write_text('private-secret', encoding='utf-8')
        (self.root / 'secret.html').write_text('private-secret', encoding='utf-8')
        (self.site / 'private.yaml').write_text('private-secret', encoding='utf-8')
        self.server = serve_public.create_server(self.root, '127.0.0.1', 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, method='GET', body=None, headers=None):
        with closing(http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)) as connection:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_public_pages_health_redirect_and_head(self):
        code, headers, body = self.request('/')
        self.assertEqual(code, 302)
        self.assertEqual(headers['Location'], '/start.html')
        for path, content_type in [('/opportunities.html', 'text/html'), ('/p/mentor.html', 'text/html'),
                                   ('/data.js?v=1', 'text/javascript'), ('/ui.css', 'text/css')]:
            code, headers, body = self.request(path)
            self.assertEqual(code, 200, path)
            self.assertTrue(headers['Content-Type'].startswith(content_type))
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertTrue(body)
            self.assertEqual(self.request(path, 'HEAD')[2], b'')
        self.assertEqual(json.loads(self.request('/health')[2]), {'ok': True, 'mode': 'public'})

    def test_opportunities_include_monitoring_and_explicit_public_mode(self):
        (self.root / 'cache').mkdir()
        monitoring = {'status': 'partial', 'summary': {'sources_error': 1}}
        (self.root / 'cache/opportunities_live.json').write_text(json.dumps(monitoring), encoding='utf-8')
        code, headers, body = self.request('/api/opportunities')
        self.assertEqual(code, 200)
        result = json.loads(body)
        self.assertEqual(result['mode'], 'public')
        self.assertEqual(result['monitoring']['status'], 'partial')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn(b'private-secret', body)

    def test_gzip_negotiation_and_head_length(self):
        original = ('window.DATA="导师资料";\n' * 1000).encode('utf-8')
        (self.site / 'large.js').write_bytes(original)
        code, headers, body = self.request('/large.js', headers={'Accept-Encoding': 'br, gzip;q=0.8'})
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Encoding'], 'gzip')
        self.assertEqual(headers['Vary'], 'Accept-Encoding')
        self.assertEqual(gzip.decompress(body), original)
        self.assertLess(len(body), len(original))
        _, head, empty = self.request('/large.js', 'HEAD', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(empty, b'')
        self.assertEqual(head['Content-Length'], headers['Content-Length'])
        self.assertEqual(head['Content-Encoding'], 'gzip')
        for accepted in ['', 'identity', 'gzip;q=0, *;q=1']:
            _, identity, raw = self.request('/large.js', headers={'Accept-Encoding': accepted})
            self.assertNotIn('Content-Encoding', identity)
            self.assertEqual(identity['Vary'], 'Accept-Encoding')
            self.assertEqual(raw, original)
        self.assertNotIn('Content-Encoding', self.request('/health', headers={'Accept-Encoding': 'gzip'})[1])

    def test_no_private_api_files_directories_or_encoded_traversal(self):
        for path in ['/api/workflow', '/api/workflow/backup', '/api/discovery', '/api/outreach',
                     '/data/workflow.yaml', '/../secret.html', '/%2e%2e/secret.html',
                     '/p/%2e%2e/%2e%2e/secret.html', '/%252e%252e/secret.html',
                     '/%2e%2e%5csecret.html', '/p\\..\\secret.html', '/%00data.js',
                     '/data.js:secret', '/private.yaml', '/p/', '/p', '/.git/config',
                     '/cache/opportunities_live.json', '/review.html', '/review.js', '/does-not-exist.html']:
            with self.subTest(path=path):
                code, _, body = self.request(path)
                self.assertEqual(code, 404)
                self.assertNotIn(b'private-secret', body)
                self.assertNotIn(b'Directory listing', body)

    def test_mutations_are_rejected_and_never_touch_private_files(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for method in ['POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS']:
            for path in ['/api/opportunities', '/api/workflow/projects', '/data.js']:
                code, headers, body = self.request(path, method, b'{"name":"must-not-save"}')
                self.assertEqual(code, 405)
                self.assertEqual(headers['Allow'], 'GET, HEAD')
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_file_and_directory_symlinks_are_never_served(self):
        link = self.site / 'linked.html'
        folder = self.site / 'linked'
        try:
            link.symlink_to(self.root / 'secret.html')
            folder.symlink_to(self.root, target_is_directory=True)
        except OSError:
            # Windows may require a symlink privilege; exercise the same guard over HTTP.
            link.unlink(missing_ok=True)
            link.write_text('private-secret', encoding='utf-8')
            folder.mkdir(exist_ok=True)
            (folder / 'secret.html').write_text('private-secret', encoding='utf-8')
            native = Path.is_symlink
            with patch.object(Path, 'is_symlink', lambda p: p in (link, folder) or native(p)):
                self.assertEqual(self.request('/linked.html')[0], 404)
                self.assertEqual(self.request('/linked/secret.html')[0], 404)
        else:
            self.assertEqual(self.request('/linked.html')[0], 404)
            self.assertEqual(self.request('/linked/secret.html')[0], 404)

    def test_invalid_public_data_returns_no_internal_details(self):
        (self.root / 'data/opportunities.json').write_text('broken', encoding='utf-8')
        code, _, body = self.request('/api/opportunities')
        self.assertEqual(code, 503)
        self.assertEqual(json.loads(body)['mode'], 'public')
        self.assertNotIn(str(self.root).encode(), body)


if __name__ == '__main__':
    unittest.main()

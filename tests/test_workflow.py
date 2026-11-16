import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
from unittest.mock import patch

from test_maintenance import ROOT, script


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.site = self.root / 'site'
        (self.site / 'p').mkdir(parents=True)
        self.pid = 'test-cs-example'
        (self.site / 'p' / (self.pid + '.html')).write_text('fixture')
        self.outreach = self.root / 'private' / 'outreach.yaml'
        self.serve = script('serve')
        self.server = self.serve.create_server(site=self.site, outreach=self.outreach, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.http = build_opener(ProxyHandler({}))

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, method='GET'):
        raw = json.dumps(body).encode() if body is not None else None
        req = Request(self.base + path, data=raw, method=method,
                      headers={'Content-Type': 'application/json'})
        try:
            with self.http.open(req) as r:
                return r.status, json.load(r)
        except HTTPError as e:
            with e:
                return e.code, json.load(e)

    def test_unknown_professor_and_malformed_bodies_rejected(self):
        self.assertEqual(self.request('/api/outreach/test-cs-missing', {}, 'PATCH')[0], 404)
        for body in [[], {'notes': 123}, {'due_date': '2026-02-30'}, {'tags': 'wrong'}, {'status': 'fake'}]:
            self.assertEqual(self.request('/api/outreach/' + self.pid, body, 'PATCH')[0], 400)
        self.assertFalse(self.outreach.exists())

    def test_next_step_and_private_tags_persist(self):
        body = {'status': 'interested', 'next_action': '阅读代表作再联系',
                'due_date': '2026-10-20', 'tags': ['优先', '机器学习'], 'notes': '私人备注'}
        code, result = self.request('/api/outreach/' + self.pid, body, 'PATCH')
        self.assertEqual(code, 200)
        for k, v in body.items():
            self.assertEqual(result[k], v)
        self.assertEqual(self.request('/api/outreach')[1][self.pid]['next_action'], body['next_action'])
        self.assertFalse((self.site / 'outreach.yaml').exists())

    def test_cross_origin_restore_does_not_modify_private_data(self):
        self.request('/api/outreach/' + self.pid, {'status': 'replied', 'notes': '保留'}, 'PATCH')
        before = self.outreach.read_bytes()
        req = Request(self.base + '/api/restore', data=b'{"version":1,"outreach":{}}', method='POST',
                      headers={'Content-Type': 'text/plain', 'Origin': 'https://untrusted.example'})
        try:
            with self.http.open(req) as r:
                code = r.status
        except HTTPError as e:
            with e:
                code = e.code
        self.assertEqual(code, 403)
        self.assertEqual(before, self.outreach.read_bytes())

    def test_backup_restore_roundtrip_and_invalid_restore_does_not_write(self):
        self.request('/api/outreach/' + self.pid, {'status': 'replied', 'notes': '原始记录'}, 'PATCH')
        code, backup = self.request('/api/backup')
        self.assertEqual(code, 200)
        original = self.outreach.read_bytes()
        self.request('/api/outreach/' + self.pid, {'notes': '修改'}, 'PATCH')
        before_restore = self.outreach.read_bytes()
        self.assertEqual(self.request('/api/restore', backup, 'POST')[0], 200)
        self.assertEqual(self.outreach.read_bytes(), original)
        self.assertTrue(any(p.read_bytes() == before_restore for p in (self.outreach.parent / 'backups').glob('*.yaml')))
        broken = {'version': 1, 'outreach': {'unknown-cs-example': {'status': 'interested'}}}
        self.assertEqual(self.request('/api/restore', broken, 'POST')[0], 400)
        self.assertEqual(self.outreach.read_bytes(), original)


class BuildTests(unittest.TestCase):
    def test_generated_freshness_badge_contains_count_not_path(self):
        build = script('build_site')
        from crawler.model import Professor, Provenance
        from datetime import date, timedelta
        env = build.template_environment()
        p = Professor(slug='example',name='测试',school='test',dept='cs',detail_url='https://example.org',
                      provenance={'name': Provenance(source='https://example.org',fetched_at=(date.today()-timedelta(days=31)).isoformat())})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sites/test').mkdir(parents=True)
            (root / 'sites/test/cs.yaml').write_text('school: test\ndept: cs')
            (root / 'site/p').mkdir(parents=True)
            (root / 'site/p/orphan.html').write_text('old')
            for name in ('ui.css', 'discovery-core.js', 'discovery.js', 'browser-library-core.js', 'browser-library.js',
                         'admissions-core.js', 'material-actions.js', 'opportunities-core.js', 'workflow.js'):
                (root / 'site' / name).write_bytes((ROOT / 'site' / name).read_bytes())
            with patch.object(build, 'ROOT', root), patch.object(build, 'SITE', root / 'site'), \
                    patch.object(build, 'template_environment', return_value=env), \
                    patch.object(build.store, 'load_all', return_value={'example': p}):
                build.main()
            html = (root / 'site/index.html').read_text(encoding='utf-8')
            self.assertIn('来源超过 30 天或未知：1 人', html)
            self.assertNotIn(str(root), html)

    def test_public_payload_is_small_searchable_and_has_no_private_fields(self):
        build = script('build_site')
        p = {'name': '测试', 'page': 'test-cs-example', 'bio_raw': '前言' * 900 + '罕见研究主题',
             'research_direction_raw': '计算机视觉', 'provenance': {'bio_raw': {'source': 'https://example.org', 'fetched_at': '2026-09-06'}},
             'ai': {'large': 'x' * 1000}}
        rec = build.list_record(p)
        self.assertNotIn('bio_raw', rec)
        self.assertNotIn('ai', rec)
        self.assertNotIn('罕见研究主题', rec['search_text'])
        self.assertIn('罕见研究主题', build.search_record(p))
        self.assertLess(len(json.dumps(rec)), len(json.dumps(p)))

    def test_detail_template_escapes_external_text(self):
        build = script('build_site')
        env = build.template_environment()
        p = {'page': 'test-cs-example', 'name': '<script>alert(1)</script>', 'school': 'test', 'dept': 'cs',
             'status': 'roster', 'institutes': [], 'bio_raw': '<img src=x onerror=alert(2)>',
             'provenance': {}, 'detail_url': 'https://example.org'}
        html = env.get_template('detail.html.j2').render(p=p)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)


class PreflightTests(unittest.TestCase):
    def test_invalid_fixture_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data/professors/test/cs').mkdir(parents=True)
            (root / 'site/p').mkdir(parents=True)
            (root / 'data/professors/test/cs/bad.yaml').write_text('name: invalid')
            (root / 'data/schools.yaml').write_text('schools: []')
            (root / 'site/index.html').write_text('const DATA = [];\n')
            (root / '.gitignore').write_text('cache/\n__pycache__/\n*.pyc\ndata/outreach.yaml\ndata/letters/')
            r = subprocess.run([sys.executable, str(ROOT / 'scripts/preflight.py'), '--root', str(root)],
                               capture_output=True, encoding='utf-8', errors='replace')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn('schema:', r.stdout)


if __name__ == '__main__':
    unittest.main()

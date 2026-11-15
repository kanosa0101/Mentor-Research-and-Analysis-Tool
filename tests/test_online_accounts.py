import http.client
import json
import sqlite3
import ssl
import ipaddress
import tempfile
import threading
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from crawler import online_accounts
from scripts import serve_public


class AccountsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'site/p').mkdir(parents=True)
        for name in ('start.html', 'desk.html', 'account.html'):
            (self.root / 'site' / name).write_text('<h1>Online</h1>')
        self.server = serve_public.create_server(self.root, '127.0.0.1', 0)
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)

    def request(self, path, method='GET', body=None, session=None, headers=None):
        values = dict(headers or {})
        if body is not None:
            values.setdefault('Content-Type', 'application/json')
            values.setdefault('Origin', self.origin)
            body = json.dumps(body).encode()
        if session:
            values.setdefault('Cookie', session[0])
            values.setdefault('X-CSRF-Token', session[1]['csrf_token'])
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=20)
        try:
            connection.request(method, path, body, values)
            response = connection.getresponse()
            raw = response.read()
            result = json.loads(raw) if raw and response.getheader('Content-Type', '').startswith('application/json') else raw
            return response.status, dict(response.getheaders()), result
        finally:
            connection.close()

    def register(self, username='student_a'):
        status, headers, body = self.request('/api/auth/register', 'POST', {'username': username, 'password': 'a-good-password-123'})
        self.assertEqual(status, 200, body)
        self.assertIn('Secure', headers['Set-Cookie'])
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertEqual(headers['Content-Security-Policy'], "frame-ancestors 'none'")
        return headers['Set-Cookie'].split(';')[0], body

    def test_session_login_logout_and_private_isolation(self):
        first, second = self.register(), self.register('student_b')
        self.assertNotEqual(first[1]['user']['id'], second[1]['user']['id'])
        self.assertEqual(self.request('/api/auth/me', session=first)[2]['user']['username'], 'student_a')
        empty = {'version': 1, 'targets': [], 'bookmarks': [], 'todos': []}
        self.assertEqual(self.request('/api/library', 'PUT', {'revision': 0, 'library': empty}, first)[0], 200)
        self.assertEqual(self.request('/api/library', session=second)[2], {'revision': 0, 'library': None})
        self.assertEqual(self.request('/api/library')[0], 401)
        self.assertEqual(self.request('/api/workflow')[0], 401)
        self.assertEqual(self.request('/api/auth/logout', 'POST', {}, first)[0], 200)
        self.assertFalse(self.request('/api/auth/me', session=first)[2]['authenticated'])
        status, _, login = self.request('/api/auth/login', 'POST', {'username': 'student_a', 'password': 'a-good-password-123'})
        self.assertEqual(status, 200)
        self.assertEqual(login['user']['id'], first[1]['user']['id'])
        self.assertNotEqual(login['csrf_token'], first[1]['csrf_token'])
        with self.server.accounts.connect() as db:
            stored = db.execute('SELECT password FROM users').fetchone()[0]
            token = db.execute('SELECT token_hash FROM sessions').fetchone()[0]
        self.assertNotIn('a-good-password-123', stored)
        self.assertNotIn(first[0].split('=')[1], token)

    def test_csrf_origin_and_invalid_session(self):
        first = self.register()
        for headers in ({'Origin': 'https://attacker.invalid'}, {'X-CSRF-Token': ''}, {'X-CSRF-Token': 'é'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.request('/api/auth/logout', 'POST', {}, first, headers)[0], 403)
        self.assertEqual(self.request('/api/auth/register', 'POST', {'username': 'new_user', 'password': 'password-12345'}, headers={'Origin': 'https://attacker.invalid'})[0], 403)
        self.assertFalse(self.request('/api/auth/me', headers={'Cookie': 'mentor_session=' + 'x' * 43})[2]['authenticated'])
        self.assertTrue(self.request('/api/auth/me', session=first)[2]['authenticated'])

    def test_password_change_revokes_all_other_devices(self):
        first = self.register()
        status, headers, data = self.request('/api/auth/login', 'POST', {'username': 'student_a', 'password': 'a-good-password-123'})
        second = headers['Set-Cookie'].split(';')[0], data
        status, headers, changed = self.request('/api/auth/password', 'POST', {'current_password': 'a-good-password-123', 'new_password': 'a-new-good-password'}, first)
        self.assertEqual(status, 200)
        self.assertFalse(self.request('/api/auth/me', session=first)[2]['authenticated'])
        self.assertFalse(self.request('/api/auth/me', session=second)[2]['authenticated'])
        self.assertTrue(self.request('/api/auth/me', session=(headers['Set-Cookie'].split(';')[0], changed))[2]['authenticated'])
        self.assertEqual(self.request('/api/auth/login', 'POST', {'username': 'student_a', 'password': 'a-good-password-123'})[0], 400)

    def test_rate_limit_and_validation(self):
        self.register()
        for _ in range(8):
            self.assertEqual(self.request('/api/auth/login', 'POST', {'username': 'student_a', 'password': 'incorrect-password'})[0], 400)
        self.assertEqual(self.request('/api/auth/login', 'POST', {'username': 'student_a', 'password': 'incorrect-password'})[0], 429)
        self.assertEqual(self.request('/api/auth/register', 'POST', {'username': '../escape', 'password': 'password-12345'})[0], 400)
        self.assertEqual(self.request('/api/auth/register', 'POST', {'username': 'new_user', 'password': 'short'})[0], 400)

    def test_expired_session_and_database_failure_fail_closed(self):
        first = self.register()
        with self.server.accounts.connect() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.request('/api/workflow', session=first)[0], 401)
        with patch.object(online_accounts.Accounts, 'session', side_effect=sqlite3.OperationalError('internal secret path')):
            code, _, body = self.request('/api/auth/me', session=first)
            self.assertEqual(code, 503)
            self.assertNotIn('secret', str(body))

    def test_cloud_library_conflict_and_bad_payload_do_not_overwrite(self):
        first = self.register()
        empty = {'version': 1, 'targets': [], 'bookmarks': [], 'todos': []}
        self.assertEqual(self.request('/api/library', 'PUT', {'revision': 0, 'library': empty}, first)[0], 200)
        self.assertEqual(self.request('/api/library', 'PUT', {'revision': 0, 'library': empty}, first)[0], 409)
        bad = dict(empty, bookmarks=[{'id': 'x', 'created_at': '2026-11-15', 'kind': 'mentor', 'title': 'x', 'url': 'https://evil.invalid/'}])
        self.assertEqual(self.request('/api/library', 'PUT', {'revision': 1, 'library': bad}, first)[0], 400)
        self.assertEqual(self.request('/api/library', session=first)[2], {'revision': 1, 'library': empty})

    def test_private_pages_download_retirement_and_legacy_activity(self):
        code, headers, _ = self.request('/desk.html?mentor=ruc-info-dongjinhao')
        self.assertEqual(code, 302)
        self.assertIn('/account.html?next=', headers['Location'])
        first = self.register()
        self.assertEqual(self.request('/desk.html', session=first)[0], 200)
        self.assertEqual(self.request('/download/mentor-assistant-v1.10.0-local.zip')[0], 410)
        self.assertEqual(self.request('/local.html?id=legacy-activity')[1]['Location'], '/opportunities.html?id=legacy-activity')

    def test_http_external_binding_never_accepts_accounts_and_redirect_is_safe(self):
        self.server.server_address = ('0.0.0.0', self.server.server_port)
        self.assertEqual(self.request('/api/auth/register', 'POST', {'username': 'student_a', 'password': 'a-good-password-123'})[0], 403)
        self.assertFalse((self.root / 'var/accounts').exists())
        self.server.https_origin = 'https://example.edu:8443'
        self.assertEqual(self.request('/start.html?q=school')[1]['Location'], 'https://example.edu:8443/start.html?q=school')
        self.assertEqual(self.request('/start.html%0d%0aX-Test:bad')[0], 404)
        self.assertEqual(self.request('/health')[0], 200)

    def test_real_tls_registration_cookie_and_session(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')])
        now = datetime.now(timezone.utc)
        cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(key, hashes.SHA256())
        cert_path, key_path = self.root / 'test-cert.pem', self.root / 'test-key.pem'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        server = serve_public.create_server(self.root, '127.0.0.1', 0)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
        server.server_address = ('0.0.0.0', server.server_port)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        client = http.client.HTTPSConnection('127.0.0.1', server.server_port, context=ssl.create_default_context(cafile=str(cert_path)), timeout=20)
        try:
            client.request('POST', '/api/auth/register', json.dumps({'username': 'tls_student', 'password': 'secure-password-123'}), {'Origin': f'https://127.0.0.1:{server.server_port}', 'Content-Type': 'application/json'})
            response = client.getresponse(); body = json.loads(response.read())
            self.assertEqual(response.status, 200)
            cookie = response.getheader('Set-Cookie')
            self.assertIn('Secure', cookie)
            client.request('GET', '/api/auth/me', headers={'Cookie': cookie.split(';')[0]})
            response = client.getresponse()
            self.assertEqual(json.loads(response.read())['user']['id'], body['user']['id'])
        finally:
            client.close(); server.shutdown(); server.server_close(); worker.join(5)

    def test_outreach_delete_consumes_json_on_reused_connection(self):
        (self.root / 'site/p/test-mentor.html').write_text('<h1>Mentor</h1>')
        account = self.register()
        self.assertEqual(self.request('/api/outreach/test-mentor', 'PATCH', {'status': 'interested'}, account)[0], 200)
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        try:
            headers = {'Cookie': account[0], 'X-CSRF-Token': account[1]['csrf_token'], 'Origin': self.origin, 'Content-Type': 'application/json'}
            connection.request('DELETE', '/api/outreach/test-mentor', '{}', headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['cleared'])
            connection.request('GET', '/api/outreach', headers={'Cookie': account[0]})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {})
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()

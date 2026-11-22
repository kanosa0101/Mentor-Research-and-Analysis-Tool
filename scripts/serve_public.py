"""Online site: public information and authenticated, account-isolated workflows."""
import argparse
import gzip
import json
import re
import ssl
import sqlite3
import sys
import hmac
import threading
from http.cookies import SimpleCookie
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs, urlencode

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import opportunity_util, push_util
from crawler.static_assets import AssetCache, send as send_asset
from crawler.public_catalog import selected as selected_mentors, search as search_mentors
from crawler.public_discovery import candidates as mentor_candidates
from crawler import online_accounts
from crawler.online_workspace import Workspace

_accounts_lock = threading.Lock()
PRIVATE_API = re.compile(r'/api/(?:workflow(?:/.*)?|discovery(?:/.*)?|outreach(?:/.*)?|backup|restore|library|materials(?:/.*)?)$')
COOKIE = 'mentor_session'

CONTENT_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                 '.css': 'text/css; charset=utf-8'}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    disable_nagle_algorithm = True
    server_version = 'MentorPublic/1.0'
    sys_version = ''

    def __init__(self, *args, root=ROOT, **kwargs):
        self.root = Path(root).absolute()
        self.site = self.root / 'site'
        super().__init__(*args, **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def reply(self, status, body=b'', content_type='application/json; charset=utf-8', headers=None):
        compressible = len(body) > 1024 and (content_type.startswith('text/') or content_type.startswith('application/json'))
        compressed = compressible and self.accepts_gzip()
        if compressed:
            body = gzip.compress(body, compresslevel=5, mtime=0)
        self.send_response(status)
        self.send_header('Content-Type', (headers or {}).get('Content-Type', content_type))
        self.send_header('Content-Length', str(len(body)))
        if compressible:
            self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Cache-Control', (headers or {}).get('Cache-Control', 'no-store' if content_type.startswith('application/json') else 'no-cache'))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "frame-ancestors 'none'")
        for key, value in (headers or {}).items():
            if key not in ('Content-Type', 'Cache-Control', 'X-Content-Type-Options'):
                self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def accepts_gzip(self):
        encodings = {}
        for item in self.headers.get('Accept-Encoding', '').lower().split(','):
            name, *parameters = item.strip().split(';')
            quality = 1.0
            for parameter in parameters:
                key, _, value = parameter.partition('=')
                if key.strip() == 'q':
                    try:
                        quality = float(value.strip())
                    except ValueError:
                        quality = 0
            encodings[name.strip()] = quality if 0 <= quality <= 1 else 0
        return encodings.get('gzip', encodings.get('*', 0)) > 0

    def json(self, status, value):
        self.reply(status, json.dumps(value, ensure_ascii=False).encode('utf-8'))

    def online_transport(self):
        """Never accept accounts on the externally bound HTTP information service."""
        if isinstance(self.connection, ssl.SSLSocket):
            return True
        try:
            return self.server.server_address[0] in ('127.0.0.1', '::1') and urlsplit('http://' + self.headers.get('Host', '')).hostname in ('localhost', '127.0.0.1', '::1')
        except ValueError:
            return False

    def accounts(self):
        with _accounts_lock:
            if not hasattr(self.server, 'accounts'):
                self.server.accounts = online_accounts.Accounts(self.root)
        return self.server.accounts

    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
            return cookie[COOKIE].value if COOKIE in cookie else ''
        except Exception:
            return ''

    def online_session(self, quiet=True):
        token = self.session_token()
        try:
            return self.accounts().session(token) if self.online_transport() and token else None
        except (OSError, sqlite3.Error):
            if not quiet:
                raise
            return None

    def online_body(self, limit=2_000_000):
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise ValueError('请求长度无效') from None
        if self.headers.get('Transfer-Encoding') or size <= 0 or size > limit:
            raise ValueError('请求为空或超过大小限制')
        self._online_body_read = True
        return json.loads(self.rfile.read(size))

    def online_reject(self, code, message):
        if not getattr(self, '_online_body_read', False):
            self.drain_small_body()
        self.close_connection = True
        return self.reply(code, json.dumps({'error': message}, ensure_ascii=False).encode(), headers={'Connection': 'close'})

    def retired_client(self, path):
        if path == '/public-data.js' or path == '/api/public-data' or path.startswith('/api/public-data/'):
            self.online_reject(410, '资料由网站自动更新，无需下载或安装客户端更新')
            return True
        return False

    def online_origin(self):
        scheme = 'https' if isinstance(self.connection, ssl.SSLSocket) else 'http'
        return scheme + '://' + self.headers.get('Host', '')

    def online_cookie(self, token, max_age=online_accounts.SESSION_SECONDS):
        return f'{COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax; Secure'

    def authenticated_reply(self, token, payload):
        return self.reply(200, json.dumps(payload, ensure_ascii=False).encode(), headers={'Set-Cookie': self.online_cookie(token)})

    def online_request(self, method):
        self._online_body_read = False
        path = urlsplit(self.path).path
        if not self.online_transport():
            return self.online_reject(403, '账号与私人记录仅通过 HTTPS 网站访问')
        try:
            session = self.online_session(quiet=False)
        except (OSError, sqlite3.Error):
            return self.online_reject(503, '账号存储暂不可用，请稍后重试')
        if method == 'GET' and path == '/api/auth/me':
            return self.json(200, session or {'authenticated': False, 'user': None})
        mutation = method not in ('GET', 'HEAD')
        if mutation:
            if self.headers.get('Origin') != self.online_origin() or self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
                return self.online_reject(403, '请从本站页面提交操作')
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                return self.online_reject(415, '请求须为 application/json')
        anonymous = method == 'POST' and path in ('/api/auth/login', '/api/auth/register')
        if not anonymous:
            if not session:
                return self.online_reject(401, '请先登录账号')
            if mutation and not hmac.compare_digest(self.headers.get('X-CSRF-Token', '').encode(), session['csrf_token'].encode()):
                return self.online_reject(403, '登录状态已变化，请刷新后重试')
        try:
            if anonymous:
                token, payload = self.accounts().credentials(self.online_body(4096), self.client_address[0], path.endswith('/register'))
                return self.authenticated_reply(token, payload)
            if path == '/api/auth/logout' and method == 'POST':
                self.online_body(4096)
                self.accounts().logout(self.session_token())
                return self.reply(200, b'{"authenticated":false,"user":null}', headers={'Set-Cookie': self.online_cookie('', 0)})
            if path == '/api/auth/password' and method == 'POST':
                self.accounts().attempt(self.client_address[0], 'password:' + session['user']['id'])
                token, payload = self.accounts().change_password(session, self.online_body(4096))
                return self.authenticated_reply(token, payload)
            if path == '/api/library' and method in ('GET', 'PUT'):
                return self.json(200, self.accounts().library(session['user']['id'], self.online_body(1_100_000) if method == 'PUT' else None))
            if path.startswith('/api/auth/'):
                return self.online_reject(404, '未知账号接口')
            # Workflow routing deliberately excludes the historical directory scanner and public updater.
            if self.path != path:
                return self.online_reject(400, '账号接口不接受查询参数')
            workspace = Workspace(self, self.accounts().user_root(session['user']['id']))
            if path.startswith('/api/materials/'):
                workspace.materials(method)
            else:
                workspace.handle(method)
            return workspace.flush()
        except online_accounts.RateLimited as error:
            return self.online_reject(429, str(error))
        except online_accounts.Conflict as error:
            return self.online_reject(409, str(error))
        except KeyError:
            return self.online_reject(404, '记录不存在')
        except (ValueError, UnicodeError, TypeError) as error:
            return self.online_reject(400, str(error))
        except (OSError, sqlite3.Error):
            return self.online_reject(503, '账号存储暂不可用，请稍后重试')

    def do_GET(self):
        try:
            raw = urlsplit(self.path)
            path = unquote(raw.path, errors='strict')
        except (UnicodeError, ValueError):
            return self.json(400, {'error': 'Invalid path'})
        if raw.scheme or raw.netloc or not path.startswith('/') or re.search(r'[\x00-\x1f\x7f]', path) or any(c in path for c in ('\\', ':', '%')):
            return self.json(404, {'error': 'Not found'})
        if self.server.https_origin and not isinstance(self.connection, ssl.SSLSocket) and path not in ('/health', '/api/health') and not path.startswith('/.well-known/acme-challenge/'):
            return self.reply(302, headers={'Location': self.server.https_origin + raw.path + ('?' + raw.query if raw.query else '')})
        if self.retired_client(path):
            return
        if path.startswith('/api/auth/') or PRIVATE_API.fullmatch(path):
            return self.online_request('GET')
        if path in ('/health', '/api/health'):
            return self.json(200, {'ok': True, 'mode': 'public'})
        if path == '/api/mentor-candidates':
            try:
                return self.json(200, mentor_candidates(self.root, parse_qs(raw.query, keep_blank_values=True)))
            except (OSError, ValueError, KeyError, TypeError):
                return self.json(400, {'error': '导师筛选请求无效，请检查条件后重试'})
        if path == '/api/mentors':
            try:
                ids = parse_qs(raw.query).get('ids', [''])[0]
                return self.json(200, {'mentors': selected_mentors(self.root, ids.split(',') if ids else [])})
            except (OSError, ValueError, KeyError):
                return self.json(400, {'error': '无法读取所选导师资料，请重试'})
        if path == '/api/mentor-search':
            try:
                params=parse_qs(raw.query)
                return self.json(200, search_mentors(self.root,json.loads(params.get('terms',['[]'])[0]),params.get('school',[])))
            except (OSError, ValueError, KeyError, TypeError):
                return self.json(400, {'error':'研究资料查询失败，请重试'})
        if re.fullmatch(r'/\.well-known/acme-challenge/[A-Za-z0-9_-]{20,200}', path):
            token = self.root / 'var/acme' / path.lstrip('/')
            if token.is_file() and not token.is_symlink():
                return self.reply(200, token.read_bytes(), 'text/plain')
            return self.reply(404)
        if path == '/api/push/config':
            cfg = push_util.config(self.root)
            return self.json(200, {'enabled': bool(cfg), 'public_key': cfg.get('public_key'), 'origin': cfg.get('origin')})
        if path == '/api/updates':
            return self.json(200, {'events': push_util.recent(self.root)})
        if re.fullmatch(r'/download/mentor-assistant-v\d+\.\d+\.\d+-local\.zip(?:\.sha256)?', path):
            return self.reply(410, '本站仅提供在线服务，请打开网站登录使用。'.encode(), 'text/plain; charset=utf-8', headers={'Link': '</start.html>; rel="alternate"'})
        if path == '/api/opportunities':
            try:
                payload = opportunity_util.public_catalog(opportunity_util.observed(self.root))
            except (OSError, ValueError, KeyError, TypeError):
                return self.json(503, {'error': '公开活动资料暂不可用', 'mode': 'public'})
            return self.json(200, dict(payload, mode='online' if self.online_session() else 'public'))
        if path.startswith('/api/'):
            return self.json(404, {'error': 'Public server has no private workspace API', 'mode': 'public'})
        if path == '/':
            return self.reply(302, headers={'Location': '/start.html'})
        if path in ('/review.html', '/review.js', '/review-worker.js'):
            return self.json(404, {'error': 'Maintenance console is local only'})
        if path == '/local.html':
            incoming = parse_qs(raw.query)
            activity = incoming.get('id', [''])[0]
            if re.fullmatch(r'[A-Za-z0-9_-]{1,160}', activity):
                return self.reply(302, headers={'Location': '/opportunities.html?' + urlencode({'id': activity})})
            context = {key: values[0] for key, values in incoming.items()
                       if key in ('mentor', 'school', 'dept', 'year', 'degree', 'route', 'track', 'program', 'discovery_return')
                       and len(values) == 1 and len(values[0]) <= 2000
                       and not re.search(r'[\x00-\x1f\x7f]', values[0])}
            destination = '/desk.html' + ('?' + urlencode(context) if context else '')
            return self.reply(302, headers={'Location': destination})
        if path in ('/desk.html', '/applications.html', '/board.html') and not self.online_session():
            destination = '/account.html?' + urlencode({'next': self.path})
            return self.reply(302, headers={'Location': destination})
        parts = path[1:].split('/')
        if any(not part or part.startswith('.') for part in parts):
            return self.json(404, {'error': 'Not found'})
        candidate = self.site.joinpath(*parts)
        content_type = CONTENT_TYPES.get(candidate.suffix)
        if re.fullmatch(r'/admissions/[a-z0-9][a-z0-9_-]*\.json', path):
            content_type = 'application/json; charset=utf-8'
        try:
            chain = [self.site, *(self.site.joinpath(*parts[:i]) for i in range(1, len(parts) + 1))]
            if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in chain):
                return self.json(404, {'error': 'Not found'})
            if not candidate.resolve().is_relative_to(self.site.resolve()) or not content_type or not candidate.is_file():
                return self.json(404, {'error': 'Not found'})
            return send_asset(self, candidate, content_type, self.server.asset_cache, self.accepts_gzip())
        except (OSError, ValueError):
            return self.json(404, {'error': 'Not found'})

    do_HEAD = do_GET

    def drain_small_body(self):
        # Drain only small bodies so closing does not reset the response on Windows.
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if 0 < size <= 16384:
                self.connection.settimeout(1)
                self.rfile.read(size)
        except (ValueError, OSError):
            pass

    def read_only(self):
        self.drain_small_body()
        self.close_connection = True
        self.reply(405, b'{"error":"Read-only public server","mode":"public"}',
                   headers={'Allow': 'GET, HEAD', 'Connection': 'close'})

    def do_POST(self):
        path = urlsplit(self.path).path
        if self.retired_client(path):
            return
        if path.startswith('/api/auth/') or PRIVATE_API.fullmatch(path):
            return self.online_request('POST')
        if self.path not in ('/api/push/subscribe', '/api/push/unsubscribe', '/api/push/test'):
            return self.read_only()
        cfg = push_util.config(self.root)
        if not cfg or not isinstance(self.connection, ssl.SSLSocket) or self.headers.get('Origin') != cfg.get('origin'):
            self.close_connection = True
            return self.json(403, {'error': '请在 HTTPS 站点自行订阅通知'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384 or self.headers.get_content_type() != 'application/json':
                raise ValueError('请求格式错误')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('请求格式错误')
            if self.path.endswith('/subscribe'):
                result = push_util.subscribe(self.root, body)
            elif self.path.endswith('/unsubscribe'):
                push_util.unsubscribe(self.root, body)
                result = {'removed': True}
            else:
                result = push_util.test_notification(self.root, body)
            return self.json(200, result)
        except (ValueError, KeyError, TypeError):
            self.close_connection = True
            return self.json(400, {'error': '订阅请求无效，或订阅凭据不匹配；请重新订阅'})
        except Exception as error:
            print('Notification service failure:', type(error).__name__,
                  getattr(getattr(error, 'response', None), 'status_code', None), file=sys.stderr)
            return self.json(503, {'error': '通知服务暂时不可用，请稍后重试'})

    def do_PATCH(self):
        if PRIVATE_API.fullmatch(urlsplit(self.path).path):
            return self.online_request('PATCH')
        return self.read_only()

    def do_PUT(self):
        if urlsplit(self.path).path == '/api/library':
            return self.online_request('PUT')
        return self.read_only()

    def do_DELETE(self):
        if PRIVATE_API.fullmatch(urlsplit(self.path).path):
            return self.online_request('DELETE')
        return self.read_only()

    do_OPTIONS = read_only


def create_server(root=ROOT, host='0.0.0.0', port=8080, https_origin=None):
    if https_origin:
        target = urlsplit(https_origin)
        if target.scheme != 'https' or not target.hostname or target.username or target.password or target.path not in ('', '/') or target.query or target.fragment:
            raise ValueError('HTTPS origin must be a canonical HTTPS origin')
        https_origin = https_origin.rstrip('/')
    server = ThreadingHTTPServer((host, port), partial(Handler, root=root))
    server.asset_cache = AssetCache()
    server.https_origin = https_origin
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--cert', type=Path)
    parser.add_argument('--key', type=Path)
    parser.add_argument('--https-origin', help='Canonical HTTPS site for HTTP page redirects')
    args = parser.parse_args()
    server = create_server(host=args.host, port=args.port, https_origin=args.https_origin)
    if args.cert and args.key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    print(f'Online site: {"https" if args.cert and args.key else "http"}://{args.host}:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

"""Read-only public site. Private workspace APIs are deliberately not registered."""
import argparse
import gzip
import json
import re
import ssl
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler import opportunity_util, push_util
from crawler import public_snapshot

CONTENT_TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
                 '.css': 'text/css; charset=utf-8'}


class Handler(BaseHTTPRequestHandler):
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
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        if compressible:
            self.send_header('Vary', 'Accept-Encoding')
        if compressed:
            self.send_header('Content-Encoding', 'gzip')
        self.send_header('Cache-Control', 'no-store' if content_type.startswith('application/json') else 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        for key, value in (headers or {}).items():
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

    def do_GET(self):
        try:
            raw = urlsplit(self.path)
            path = unquote(raw.path, errors='strict')
        except (UnicodeError, ValueError):
            return self.json(400, {'error': 'Invalid path'})
        if raw.scheme or raw.netloc or not path.startswith('/') or any(c in path for c in ('\\', '\x00', ':', '%')):
            return self.json(404, {'error': 'Not found'})
        if path in ('/health', '/api/health'):
            return self.json(200, {'ok': True, 'mode': 'public'})
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
        if path == '/api/public-data':
            descriptor = public_snapshot.latest(self.root)
            return self.json(200 if descriptor else 503, dict(descriptor or {}, mode='public'))
        if re.fullmatch(r'/api/public-data/archive/[a-f0-9]{64}', path):
            archive = self.root / 'cache/public_snapshots' / (path.rsplit('/', 1)[-1] + '.zip')
            if archive.is_file() and not archive.is_symlink():
                return self.reply(200, archive.read_bytes(), 'application/zip')
            return self.json(409, {'error': '该资料版本已更新，请重新检查'})
        if path == '/api/opportunities':
            try:
                payload = opportunity_util.observed(self.root)
            except (OSError, ValueError, KeyError, TypeError):
                return self.json(503, {'error': '公开活动资料暂不可用', 'mode': 'public'})
            return self.json(200, dict(payload, mode='public'))
        if path.startswith('/api/'):
            return self.json(404, {'error': 'Public server has no private workspace API', 'mode': 'public'})
        if path == '/':
            return self.reply(302, headers={'Location': '/start.html'})
        if path in ('/review.html', '/review.js'):
            return self.json(404, {'error': 'Maintenance console is local only'})
        if path in ('/desk.html', '/applications.html', '/board.html'):
            return self.reply(302, headers={'Location': '/local.html'})
        parts = path[1:].split('/')
        if any(not part or part.startswith('.') for part in parts):
            return self.json(404, {'error': 'Not found'})
        candidate = self.site.joinpath(*parts)
        try:
            chain = [self.site, *(self.site.joinpath(*parts[:i]) for i in range(1, len(parts) + 1))]
            if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in chain):
                return self.json(404, {'error': 'Not found'})
            if not candidate.resolve().is_relative_to(self.site.resolve()) or candidate.suffix not in CONTENT_TYPES or not candidate.is_file():
                return self.json(404, {'error': 'Not found'})
            body = candidate.read_bytes()
        except (OSError, ValueError):
            return self.json(404, {'error': 'Not found'})
        return self.reply(200, body, CONTENT_TYPES[candidate.suffix])

    do_HEAD = do_GET

    def read_only(self):
        # Drain only small bodies so closing does not reset the response on Windows.
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if 0 < size <= 16384:
                self.connection.settimeout(1)
                self.rfile.read(size)
        except (ValueError, OSError):
            pass
        self.close_connection = True
        self.reply(405, b'{"error":"Read-only public server","mode":"public"}',
                   headers={'Allow': 'GET, HEAD', 'Connection': 'close'})

    def do_POST(self):
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

    do_PATCH = do_PUT = do_DELETE = do_OPTIONS = read_only


def create_server(root=ROOT, host='0.0.0.0', port=8080):
    return ThreadingHTTPServer((host, port), partial(Handler, root=root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--cert', type=Path)
    parser.add_argument('--key', type=Path)
    args = parser.parse_args()
    server = create_server(host=args.host, port=args.port)
    if args.cert and args.key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    print(f'Public read-only site: http://{args.host}:{server.server_port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

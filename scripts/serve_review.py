"""Maintainer-only opportunity review UI, always bound to IPv4 loopback."""
import argparse
import hmac
import ipaddress
import json
import secrets
import sys
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.review_dashboard import Dashboard


class Handler(BaseHTTPRequestHandler):
    server_version = 'MentorReview/1.0'
    sys_version = ''

    def __init__(self, *args, dashboard, token, **kwargs):
        self.dashboard, self.token = dashboard, token
        super().__init__(*args, **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def reply(self, code, value, content_type='application/json; charset=utf-8'):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        try:
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            self.close_connection = True

    def local(self, writing=False):
        host = self.headers.get('Host', '')
        expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        origin = self.headers.get('Origin')
        fetch_site = self.headers.get('Sec-Fetch-Site')
        allowed = ipaddress.ip_address(self.client_address[0]).is_loopback and host in expected
        allowed = allowed and fetch_site not in ('cross-site', 'same-site') and (not origin or origin == 'http://' + host)
        if writing:
            allowed = allowed and origin == 'http://' + host and hmac.compare_digest(self.headers.get('X-Review-Token', ''), self.token)
        if not allowed:
            self.discard_body()
            self.close_connection = True
            self.reply(403, {'error': '核验工作台只接受本机同源请求；请直接打开本机工作台地址。'})
        return allowed

    def discard_body(self):
        # Drain small rejected bodies so Windows can deliver the error response.
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if 0 < size <= 16384:
                self.connection.settimeout(1)
                self.rfile.read(size)
        except (ValueError, OSError):
            pass

    def do_GET(self):
        if not self.local():
            return
        parsed = urlsplit(self.path)
        if parsed.netloc or parsed.scheme:
            return self.reply(404, {'error': '不存在的地址'})
        path = parsed.path
        try:
            if path in ('/', '/review.html', '/review.js', '/review-worker.js', '/ui.css'):
                name = 'review.html' if path == '/' else path[1:]
                file = self.dashboard.root / 'site' / name
                if file.is_symlink():
                    return self.reply(404, {'error': '不存在的资源'})
                content_type = 'text/html; charset=utf-8' if name.endswith('.html') else 'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
                return self.reply(200, file.read_bytes(), content_type)
            if path == '/api/review':
                return self.reply(200, dict(self.dashboard.listing(), token=self.token, mode='local_review'))
            if path == '/api/review/detail':
                draft_id = parse_qs(parsed.query).get('id', [''])[0]
                return self.reply(200, self.dashboard.detail(draft_id))
            if path == '/api/review/sources':
                return self.reply(200, self.dashboard.sources())
            if path == '/api/review/notifications':
                from crawler import maintenance_push
                return self.reply(200, maintenance_push.settings(self.dashboard.root))
            return self.reply(404, {'error': '不存在的资源；本服务不提供私人申请或磁盘浏览接口'})
        except (ValueError, KeyError, TypeError) as error:
            self.reply(400, {'error': str(error) if isinstance(error, ValueError) else '队列格式不完整，请检查本机维护资料。'})
        except OSError:
            self.reply(503, {'error': '本机队列或资源暂不可读取；请检查配置和文件权限。'})

    def do_POST(self):
        if not self.local(writing=True):
            return
        if self.path not in ('/api/review/action', '/api/review/source-action'):
            self.discard_body()
            self.close_connection = True
            return self.reply(404, {'error': '不支持的操作'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if self.headers.get_content_type() != 'application/json' or not 0 < size <= 1024*1024 or self.headers.get('Transfer-Encoding'):
                self.discard_body()
                self.close_connection = True
                return self.reply(400, {'error': '须提交1MB以内的JSON请求'})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or not isinstance(body.get('id'), str):
                raise ValueError('操作内容不完整')
            if self.path == '/api/review/action' and body['id'] == 'notifications':
                from crawler import maintenance_push
                actions = {'notifications_subscribe': maintenance_push.subscribe,
                           'notifications_unsubscribe': maintenance_push.unsubscribe,
                           'notifications_test': maintenance_push.test_notification}
                if body.get('action') not in actions or not isinstance(body.get('payload'), dict):
                    raise ValueError('维护提醒操作不完整')
                return self.reply(200, actions[body['action']](self.dashboard.root, body['payload']))
            result = (self.dashboard.source_action(body['id'], body) if self.path.endswith('/source-action')
                      else self.dashboard.mutate(body['id'], body.get('action'), body))
            return self.reply(200, result)
        except (ValueError, RuntimeError, KeyError, TypeError) as error:
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else '字段格式不完整，请检查后重试。'
            return self.reply(409 if '已被其他' in message else 400, {'error': message})
        except OSError:
            return self.reply(503, {'error': '本机写入失败；未确认发布成功，请刷新并检查队列。'})

    def log_message(self, fmt, *args):
        pass  # Avoid logging request content or tokens.


def make_server(root=ROOT, port=18769, queue=None, config=None):
    dashboard = Dashboard(root, queue, config)
    handler = partial(Handler, dashboard=dashboard, token=secrets.token_urlsafe(32))
    return ThreadingHTTPServer(('127.0.0.1', port), handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--queue', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--port', type=int, default=18769)
    args = parser.parse_args()
    with make_server(args.root, args.port, args.queue, args.config) as server:
        print(f'本机核验工作台 http://127.0.0.1:{server.server_port}/review.html', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()

"""本地静态站及私人跟进 API；默认只绑定 127.0.0.1。"""
import argparse
import json
import os
import sys
import tempfile
import threading
from datetime import date, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from crawler.outreach_util import validate_outreach, validate_patch

SITE = ROOT / 'site'
OUTREACH = ROOT / 'data' / 'outreach.yaml'
_lock = threading.Lock()


def load_outreach(path=OUTREACH):
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    if not isinstance(data, dict):
        raise ValueError('跟进文件须为 YAML 对象')
    return data


def save_outreach(data, path=OUTREACH):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, site=SITE, outreach=OUTREACH, **kwargs):
        self.site = Path(site)
        self.outreach = Path(outreach)
        super().__init__(*args, directory=str(self.site), **kwargs)

    def log_message(self, fmt, *args):
        if self.path.startswith('/api/'):
            super().log_message(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length < 0 or length > 2_000_000:
            raise ValueError('请求过大')
        return json.loads(self.rfile.read(length) or b'{}')

    def _known_ids(self):
        return {p.stem for p in (self.site / 'p').glob('*.html')}

    def _local_request(self, json_body=False):
        host = self.headers.get('Host', '')
        try:
            address = urlsplit('http://' + host)
            valid_host = address.hostname in ('127.0.0.1', 'localhost') and address.port == self.server.server_port
        except ValueError:
            valid_host = False
        origin = self.headers.get('Origin')
        if not valid_host or (origin is not None and origin != 'http://' + host):
            self._json(403, {'error': '只接受本地同源请求'})
            return False
        if json_body and self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self._json(415, {'error': 'Content-Type 须为 application/json'})
            return False
        return True

    def _pid(self):
        if not self.path.startswith('/api/outreach/'):
            return None
        pid = self.path[len('/api/outreach/'):]
        return pid if pid in self._known_ids() else None

    def do_GET(self):
        if self.path == '/api/health':
            return self._json(200, {'ok': True})
        if self.path in ('/api/outreach', '/api/backup'):
            if not self._local_request():
                return
            with _lock:
                try:
                    data = load_outreach(self.outreach)
                    validate_outreach(data, self._known_ids())
                except (ValueError, yaml.YAMLError) as e:
                    return self._json(500, {'error': str(e)})
                if self.path == '/api/backup':
                    return self._json(200, {'version': 1, 'outreach': data})
                return self._json(200, data)
        return super().do_GET()

    def do_PATCH(self):
        if not self._local_request(json_body=True):
            return
        pid = self._pid()
        if pid is None:
            return self._json(404, {'error': '未知导师或 API'})
        try:
            body = self._body()
            validate_patch(body)
        except (ValueError, UnicodeError) as e:
            return self._json(400, {'error': str(e)})
        with _lock:
            try:
                data = load_outreach(self.outreach)
                validate_outreach(data, self._known_ids())
            except (ValueError, yaml.YAMLError) as e:
                return self._json(500, {'error': str(e)})
            if body.get('clear'):
                data.pop(pid, None)
            else:
                entry = data.get(pid) or {'status': 'interested', 'history': []}
                today = date.today().isoformat()
                status = body.get('status', entry['status'])
                if pid not in data or status != entry['status']:
                    entry.setdefault('history', []).append({'date': today, 'action': status,
                                                           'note': body.get('note', '').strip()})
                entry['status'] = status
                for key in ('notes', 'next_action', 'due_date'):
                    if key in body:
                        entry[key] = body[key].strip()
                if 'tags' in body:
                    entry['tags'] = list(dict.fromkeys(t.strip() for t in body['tags']))
                entry['updated_at'] = today
                data[pid] = entry
            save_outreach(data, self.outreach)
        return self._json(200, data.get(pid, {}))

    def do_DELETE(self):
        if not self._local_request():
            return
        pid = self._pid()
        if pid is None:
            return self._json(404, {'error': '未知导师或 API'})
        with _lock:
            try:
                data = load_outreach(self.outreach)
                validate_outreach(data, self._known_ids())
            except (ValueError, yaml.YAMLError) as e:
                return self._json(500, {'error': str(e)})
            existed = data.pop(pid, None)
            save_outreach(data, self.outreach)
        return self._json(200, {'cleared': existed is not None})

    def do_POST(self):
        if not self._local_request(json_body=True):
            return
        if self.path != '/api/restore':
            return self._json(404, {'error': '未知 API'})
        try:
            body = self._body()
            if not isinstance(body, dict) or body.get('version') != 1:
                raise ValueError('备份版本须为 1')
            data = body.get('outreach')
            validate_outreach(data, self._known_ids())
        except (ValueError, UnicodeError) as e:
            return self._json(400, {'error': str(e)})
        with _lock:
            if self.outreach.exists():
                backups = self.outreach.parent / 'backups'
                backups.mkdir(parents=True, exist_ok=True)
                target = backups / ('outreach-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.yaml')
                target.write_bytes(self.outreach.read_bytes())
            save_outreach(data, self.outreach)
        return self._json(200, {'restored': len(data)})


def create_server(site=SITE, outreach=OUTREACH, port=8000):
    return ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, site=site, outreach=outreach))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--site', type=Path, default=SITE)
    ap.add_argument('--outreach', type=Path, default=OUTREACH)
    args = ap.parse_args()
    server = create_server(args.site, args.outreach, args.port)
    print(f'http://127.0.0.1:{server.server_port}/board.html  (跟进文件: {args.outreach})')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

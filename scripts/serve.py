"""本地静态站及私人跟进 API；默认只绑定 127.0.0.1。"""
import argparse
import errno
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
from crawler.workflow_util import empty_workflow, update_entry, scan_materials
from crawler import contact_util as contact
from crawler import project_util as projects
from crawler import discovery_util as discovery

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
    def __init__(self, *args, site=SITE, outreach=OUTREACH, workflow=None, **kwargs):
        self.site = Path(site)
        self.outreach = Path(outreach)
        self.workflow = Path(workflow) if workflow is not None else self.outreach.with_name('workflow.yaml')
        self.discovery = self.outreach.with_name('discovery.yaml')
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

    def _body(self, limit=2_000_000):
        length = int(self.headers.get('Content-Length') or 0)
        if length < 0 or length > limit:
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
        referer = self.headers.get('Referer')
        cross_site = self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site')
        if referer:
            ref = urlsplit(referer)
            cross_site = cross_site or ref.scheme != 'http' or ref.netloc != host
        if not valid_host or cross_site or (origin is not None and origin != 'http://' + host):
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
        if self.path == '/api/discovery' or self.path.startswith('/api/discovery/'):
            return self._discovery_request('GET')
        if self.path == '/api/workflow' or self.path.startswith('/api/workflow/'):
            return self._workflow_request('GET')
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
        if self.path.startswith('/api/workflow/'):
            return self._workflow_request('PATCH')
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
        if self.path == '/api/discovery' or self.path.startswith('/api/discovery/'):
            return self._discovery_request('POST')
        if self.path.startswith('/api/workflow/'):
            return self._workflow_request('POST')
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

    def _workflow_request(self, method):
        if not self._local_request(json_body=method != 'GET'):
            return
        parts = self.path.split('/')[3:]
        is_eml = len(parts) == 3 and parts[0] == 'drafts' and parts[2] == 'eml'
        if method == 'GET' and self.path not in ('/api/workflow', '/api/workflow/backup') and not is_eml:
            return self._json(404, {'error': '未知 API'})
        try:
            body = self._body(limit=32_000_000 if parts == ['restore'] else 2_000_000) if method != 'GET' else None
        except (ValueError, UnicodeError) as e:
            return self._json(400, {'error': str(e)})
        with _lock:
            try:
                # 恢复不依赖旧文件有效；新备份校验后保留旧文件原始字节。
                data = load_outreach(self.workflow) if self.workflow.exists() and parts != ['restore'] else empty_workflow()
                context = projects.load_context(ROOT)
                data = projects.upgrade(data, self._known_ids(), context)
            except (ValueError, OSError, yaml.YAMLError) as e:
                return self._json(500, {'error': str(e)})
            if method == 'GET':
                if is_eml:
                    try:
                        raw = contact.export_eml(data, parts[1])
                    except KeyError as e:
                        return self._json(404, {'error': str(e)})
                    except (ValueError, OSError) as e:
                        return self._json(400, {'error': str(e)})
                    self.send_response(200)
                    self.send_header('Content-Type', 'message/rfc822')
                    self.send_header('Content-Disposition', 'attachment; filename="mentor-draft.eml"')
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                return self._json(200, {'version': 3, 'workflow': data} if parts == ['backup'] else data)
            try:
                if method == 'POST' and parts == ['restore']:
                    if not isinstance(body, dict) or set(body) != {'version', 'workflow'} or type(body['version']) is not int or body['version'] not in (1, 2, 3):
                        raise ValueError('备份版本或结构错误')
                    data = body['workflow']
                    if not isinstance(data, dict) or data.get('version') != body['version']:
                        raise ValueError('备份内外版本不一致')
                    data = projects.upgrade(data, self._known_ids(), context)
                    if self.workflow.exists():
                        backups = self.workflow.parent / 'backups'
                        backups.mkdir(parents=True, exist_ok=True)
                        target = backups / ('workflow-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.yaml')
                        target.write_bytes(self.workflow.read_bytes())
                    result = {'restored': True}
                elif method == 'POST' and parts == ['scan']:
                    if not isinstance(body, dict) or set(body) != {'root'}:
                        raise ValueError('扫描须指定 root 目录')
                    base, result = scan_materials(contact.core_view(data), body['root'], self._known_ids())
                    data = contact.merge_core(data, base, self._known_ids())
                elif method == 'POST' and len(parts) == 3 and parts[0] == 'drafts' and parts[2] == 'confirm':
                    data, result = contact.confirm(data, parts[1], body, self._known_ids())
                elif method == 'POST' and len(parts) == 3 and parts[0] == 'targets' and parts[2] == 'reply':
                    data, result = contact.reply(data, parts[1], body, self._known_ids())
                elif (method == 'POST' and len(parts) == 1) or (method == 'PATCH' and len(parts) == 2):
                    if parts[0] == 'projects':
                        data, result = projects.update(data, body, self._known_ids(), context,
                                                       parts[1] if method == 'PATCH' else None)
                    elif parts[0] in contact.DEFAULTS:
                        data, result = contact.update(data, parts[0], body, self._known_ids(), parts[1] if method == 'PATCH' else None)
                    else:
                        base, result = update_entry(contact.core_view(data), parts[0], body, self._known_ids(),
                                                    parts[1] if method == 'PATCH' else None)
                        data = contact.merge_core(data, base, self._known_ids())
                else:
                    return self._json(404, {'error': '未知 API'})
                projects.validate(data, context)
                save_outreach(data, self.workflow)
            except KeyError as e:
                return self._json(404, {'error': str(e)})
            except (ValueError, UnicodeError, OSError) as e:
                return self._json(400, {'error': str(e)})
        return self._json(200, result)

    def _discovery_request(self, method):
        if not self._local_request(json_body=method == 'POST'):
            return
        path = self.path.removeprefix('/api/discovery')
        if (method == 'GET' and path not in ('', '/backup')) or (method == 'POST' and path not in ('', '/reviews', '/restore')):
            return self._json(404, {'error': '未知 API'})
        try:
            body = self._body() if method == 'POST' else None
        except (ValueError, UnicodeError) as e:
            return self._json(400, {'error': str(e)})
        with _lock:
            try:
                data = load_outreach(self.discovery) if self.discovery.exists() and path != '/restore' else discovery.empty()
                discovery.validate(data, self._known_ids())
            except (ValueError, OSError, yaml.YAMLError) as e:
                return self._json(500, {'error': str(e)})
            if method == 'GET':
                return self._json(200, {'version': 1, 'discovery': data} if path == '/backup' else data)
            try:
                if path == '/restore':
                    if not isinstance(body, dict) or set(body) != {'version', 'discovery'} or type(body['version']) is not int or body['version'] != 1:
                        raise ValueError('无效筛选备份')
                    data = body['discovery']
                    discovery.validate(data, self._known_ids())
                    if self.discovery.exists():
                        backups = self.discovery.parent / 'backups'
                        backups.mkdir(parents=True, exist_ok=True)
                        (backups / ('discovery-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.yaml')).write_bytes(self.discovery.read_bytes())
                    result = {'restored': True}
                elif path == '/reviews':
                    data, result = discovery.save_review(data, body, self._known_ids())
                else:
                    discovery.validate_preferences(body, self._known_ids())
                    data['preferences'] = body
                    discovery.validate(data, self._known_ids())
                    result = body
                save_outreach(data, self.discovery)
            except (ValueError, OSError, UnicodeError) as e:
                return self._json(400, {'error': str(e)})
        return self._json(200, result)


def create_server(site=SITE, outreach=OUTREACH, port=8000, workflow=None):
    return ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, site=site, outreach=outreach, workflow=workflow))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--site', type=Path, default=SITE)
    ap.add_argument('--outreach', type=Path, default=OUTREACH)
    ap.add_argument('--workflow', type=Path, help='私人申请文件，默认与跟进文件同目录')
    args = ap.parse_args()
    try:
        server = create_server(args.site, args.outreach, args.port, args.workflow)
    except OSError as e:
        # Windows may report access denied for a port held by an exclusive listener.
        if e.errno == errno.EADDRINUSE or getattr(e, 'winerror', None) in (10048, 10013):
            print(f'本地端口 {args.port} 已被占用或系统不允许绑定。'
                  '请关闭该端口的旧服务，或用 --port 8001 选择其他端口。', file=sys.stderr)
            raise SystemExit(1) from None
        raise
    base = f'http://127.0.0.1:{server.server_port}'
    print(f'找导师：{base}/discovery.html')
    print(f'我的申请与联系：{base}/desk.html')
    print(f'项目、材料与提醒：{base}/applications.html')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

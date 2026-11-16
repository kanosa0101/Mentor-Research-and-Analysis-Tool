"""Explicit adapter for the existing workflow logic, with per-account paths."""
import re
import io
import json

from scripts import serve
from crawler import online_materials


class Workspace(serve.Handler):
    # No HTTP handler is constructed here: transport remains owned by the online server.
    def __init__(self, transport, user_root):
        self.transport = transport
        self.site = transport.site
        self.outreach = user_root / 'outreach.yaml'
        self.workflow = user_root / 'workflow.yaml'
        self.discovery = user_root / 'discovery.yaml'
        self.user_root = user_root
        self.path = transport.path
        self.headers = transport.headers
        self.rfile, self.wfile = transport.rfile, io.BytesIO()
        self.response_code, self.response_headers = None, {}
        self.connection, self.server = transport.connection, transport.server
        self._parsed_body = None

    def send_response(self, *args, **kwargs):
        self.response_code = args[0]

    def send_header(self, *args, **kwargs):
        self.response_headers[args[0]] = args[1]

    def end_headers(self):
        pass

    def _reply(self, code, body, content_type, headers=None):
        self.response_code = code
        self.response_headers = {'Content-Type': content_type, 'Cache-Control': 'no-store', **(headers or {})}
        self.wfile.write(body)

    def flush(self):
        # The workflow lock is released before any response bytes meet a slow client.
        headers = dict(self.response_headers)
        content_type = headers.pop('Content-Type', 'application/json; charset=utf-8')
        headers.pop('Content-Length', None)
        return self.transport.reply(self.response_code or 500, self.wfile.getvalue(), content_type, headers)

    def _json(self, code, obj):
        if code == 200:
            workflow = obj if self.path == '/api/workflow' else obj.get('workflow') if self.path == '/api/workflow/backup' else None
            if workflow is not None:
                missing = online_materials.missing_materials(workflow, self.user_root)
                for key, material in workflow.get('materials', {}).items():
                    material['missing'] = key in missing
            if self.path == '/api/workflow/restore' and obj.get('restored'):
                obj['missing_materials'] = len(online_materials.missing_materials(self._parsed_body['workflow'], self.user_root))
        return self._reply(code, json.dumps(obj, ensure_ascii=False).encode(), 'application/json; charset=utf-8')

    def _known_ids(self):
        # One adapter is created per request; avoid repeated full-directory scans.
        if not hasattr(self, '_request_known_ids'):
            self._request_known_ids = super()._known_ids()
        return self._request_known_ids

    def _local_request(self, json_body=False):
        # Authentication, CSRF and JSON type have already been checked by the online gate.
        return True

    def _reject_local(self, code, message):
        self.transport.close_connection = True
        self._json(code, {'error': message})
        self.response_headers['Connection'] = 'close'

    def _body(self, limit=2_000_000):
        if self._parsed_body is not None:
            return self._parsed_body
        self._parsed_body = self.transport.online_body(limit)
        return self._parsed_body

    def handle(self, method):
        if self.path == '/api/workflow/scan' or self.path == '/api/workflow/materials' and method == 'POST':
            return self._reject_local(400, '请上传材料文件；在线服务不读取电脑或服务器目录')
        if self.path.startswith('/api/workflow'):
            # Guard BOTH stored snapshots and incoming backups before existing export code can read files.
            body = self._body(32_000_000 if self.path == '/api/workflow/restore' else 2_000_000) if method != 'GET' else None
            with serve._lock:
                if self.path == '/api/workflow/restore' and isinstance(body, dict):
                    online_materials.validate_storage_paths(body.get('workflow', {}), self.user_root)
                elif self.path != '/api/workflow/restore':
                    stored = serve.load_outreach(self.workflow) if self.workflow.exists() else {}
                    online_materials.validate_storage_paths(stored, self.user_root)
                if re.fullmatch(r'/api/workflow/materials/[a-f0-9]{32}', self.path) and isinstance(body, dict) and 'path' in body:
                    raise ValueError('材料文件不能通过修改路径替换，请重新上传')
                return self._workflow_request(method)
        if self.path == '/api/discovery' or self.path.startswith('/api/discovery/'):
            return self._discovery_request(method)
        if self.path == '/api/outreach' and method == 'GET' or self.path == '/api/backup' and method == 'GET':
            return serve.Handler.do_GET(self)
        if re.fullmatch(r'/api/outreach/[A-Za-z0-9_-]+', self.path) and method in ('PATCH', 'DELETE'):
            if method == 'DELETE' and self._body(4096) != {}:
                raise ValueError('删除请求须为空对象')
            return (serve.Handler.do_PATCH if method == 'PATCH' else serve.Handler.do_DELETE)(self)
        if self.path == '/api/restore' and method == 'POST':
            return serve.Handler.do_POST(self)
        return self._reject_local(404, '未知账号数据接口')

    def materials(self, method):
        body = self.transport.online_body(online_materials.MAX_REQUEST_BYTES) if method == 'POST' and self.path == '/api/materials/upload' else None
        with serve._lock:
            data = serve.load_outreach(self.workflow) if self.workflow.exists() else serve.empty_workflow()
            online_materials.validate_storage_paths(data, self.user_root)
            if method == 'POST' and self.path == '/api/materials/upload':
                updated, material = online_materials.add_upload(self.user_root, data, body, self._known_ids())
                try:
                    serve.save_outreach(updated, self.workflow)
                except OSError:
                    online_materials.rollback_upload(self.user_root, material)
                    raise
                return self._json(200, {'material': material})
            match = re.fullmatch(r'/api/materials/([a-f0-9]{32})/download', self.path)
            if method == 'GET' and match:
                path, filename = online_materials.download(self.user_root, data, match[1])
                raw = path.read_bytes()
                return self._reply(200, raw, 'application/octet-stream', headers=online_materials.download_headers(filename))
            match = re.fullmatch(r'/api/materials/([a-f0-9]{32})', self.path)
            if method == 'DELETE' and match:
                self.transport.online_body(4096)
                try:
                    result = online_materials.delete_upload(self.user_root, data, match[1], lambda updated: serve.save_outreach(updated, self.workflow))
                except online_materials.Conflict as error:
                    return self._json(409, {'error': str(error)})
                return self._json(200, result)
        return self._reject_local(404, '未知材料接口')

"""本地写回服务：静态托管 site/ + 套磁跟进状态的 PATCH API。

REQUIREMENTS §8.5 已决：标准库实现，不引 Flask/FastAPI。只绑 127.0.0.1。
数据落 data/outreach.yaml（gitignore，不进公开仓库）：
    <school>-<dept>-<slug>:
      status: interested|emailed|replied|meeting|archived
      notes: 备注文本
      updated_at: 'YYYY-MM-DD'
      history: [{date, action, note}]

用法：python scripts/serve.py [--port 8000]  （代替 python -m http.server）
"""
import argparse
import json
import os
import tempfile
import threading
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUTREACH = ROOT / "data" / "outreach.yaml"

STATUSES = ("interested", "emailed", "replied", "meeting", "archived")
STATUS_LABELS = {"interested": "意向", "emailed": "已发信", "replied": "已回复",
                 "meeting": "推进中", "archived": "归档"}
_lock = threading.Lock()


def load_outreach():
    if not OUTREACH.exists():
        return {}
    data = yaml.safe_load(OUTREACH.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def save_outreach(data):
    OUTREACH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(OUTREACH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp, OUTREACH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def parse_page_id(pid):
    # school/dept id 不含连字符，slug 可能含（zhangwei-2）——按前两段切
    parts = pid.split("-", 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError("page id 形如 <school>-<dept>-<slug>")
    return "-".join(parts[:2]), parts[2]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SITE), **kw)

    def log_message(self, fmt, *args):  # 静默访问日志，只留 API 动作
        if self.path.startswith("/api/"):
            super().log_message(fmt, *args)

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(200, {"ok": True})
        if self.path == "/api/outreach":
            with _lock:
                return self._json(200, load_outreach())
        return super().do_GET()

    def do_PATCH(self):
        if not self.path.startswith("/api/outreach/"):
            return self._json(404, {"error": "unknown api"})
        pid = self.path[len("/api/outreach/"):].strip("/")
        try:
            school_dept, _slug = parse_page_id(pid)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid json body"})
        status = body.get("status")
        if status is not None and status not in STATUSES:
            return self._json(400, {"error": f"status 须为 {STATUSES}"})
        with _lock:
            data = load_outreach()
            entry = data.get(pid) or {}
            if body.get("clear"):
                data.pop(pid, None)
            else:
                today = date.today().isoformat()
                if status and status != entry.get("status"):
                    entry["status"] = status
                    hist = entry.setdefault("history", [])
                    hist.append({"date": today, "action": status,
                                 "note": (body.get("note") or "").strip()})
                if "notes" in body:
                    entry["notes"] = (body.get("notes") or "").strip()
                entry["updated_at"] = today
                data[pid] = entry
            save_outreach(data)
        out = {} if body.get("clear") else data.get(pid)
        label = STATUS_LABELS.get((out or {}).get("status"), "")
        print(f"[outreach] {pid} -> {body.get('clear') and 'cleared' or label}")
        return self._json(200, out or {})

    def do_DELETE(self):
        if not self.path.startswith("/api/outreach/"):
            return self._json(404, {"error": "unknown api"})
        pid = self.path[len("/api/outreach/"):].strip("/")
        try:
            parse_page_id(pid)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        with _lock:
            data = load_outreach()
            existed = data.pop(pid, None)
            save_outreach(data)
        print(f"[outreach] {pid} -> cleared")
        return self._json(200, {"cleared": bool(existed)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving {SITE} at http://127.0.0.1:{args.port}  (outreach -> {OUTREACH})")
    print("套磁看板: http://127.0.0.1:%d/board.html  Ctrl+C 退出" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()

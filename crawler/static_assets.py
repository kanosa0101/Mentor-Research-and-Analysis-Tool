"""Bounded, revision-aware caching for public static pages and assets."""
import gzip
import hashlib
import threading
from collections import OrderedDict


class AssetCache:
    def __init__(self, max_bytes=32_000_000, max_entries=128):
        self.entries = OrderedDict()
        self.size = 0
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.lock = threading.Lock()

    def read(self, path, compressed):
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ino, compressed)
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key]
        raw = path.read_bytes()
        encoded = gzip.compress(raw, compresslevel=5, mtime=0) if compressed else raw
        value = (encoded, '"' + hashlib.sha256(encoded).hexdigest() + '"')
        with self.lock:
            if key in self.entries:
                return self.entries[key]
            if len(encoded) <= self.max_bytes:
                self.entries[key] = value
                self.size += len(encoded)
                while self.size > self.max_bytes or len(self.entries) > self.max_entries:
                    _, old = self.entries.popitem(last=False)
                    self.size -= len(old[0])
        return value


def send(handler, path, content_type, cache, accepts_gzip=False, max_age=300):
    compressed = accepts_gzip and path.stat().st_size > 1024
    body, etag = cache.read(path, compressed)
    unchanged = etag in [v.strip() for v in handler.headers.get('If-None-Match', '').split(',')]
    handler.send_response(304 if unchanged else 200)
    handler.send_header('Content-Type', content_type)
    if not unchanged:
        handler.send_header('Content-Length', str(len(body)))
    handler.send_header('ETag', etag)
    handler.send_header('Vary', 'Accept-Encoding')
    handler.send_header('Cache-Control', 'no-cache' if path.suffix == '.html' or not max_age else f'public, max-age={max_age}, must-revalidate')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    handler.send_header('Referrer-Policy', 'same-origin')
    if compressed:
        handler.send_header('Content-Encoding', 'gzip')
    handler.end_headers()
    if not unchanged and handler.command != 'HEAD':
        handler.wfile.write(body)

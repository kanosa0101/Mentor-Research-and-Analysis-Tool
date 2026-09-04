import hashlib
import json
import time
from pathlib import Path

import requests

CACHE = Path(__file__).resolve().parent.parent / "cache" / "http"
MIN_INTERVAL = 0.5
_last = [0.0]


def _key(method, url, data):
    raw = method + "\n" + url + "\n" + (
        json.dumps(data, sort_keys=True, ensure_ascii=False) if data else ""
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _throttle():
    wait = _last[0] + MIN_INTERVAL - time.time()
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()


def fetch(method, url, data=None, refresh=False):
    key = _key(method, url, data)
    body_p = CACHE / (key + ".body")
    meta_p = CACHE / (key + ".meta.json")
    if body_p.exists() and not refresh:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        return body_p.read_bytes(), meta, True
    _throttle()
    last_err = None
    for attempt in range(3):
        try:
            r = _request(method, url, data=data, timeout=30,
                         headers={"User-Agent": "Mozilla/5.0 (advisor-research local tool)"})
            break
        except requests.RequestException as e:
            last_err = e
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    else:
        raise last_err
    r.raise_for_status()
    CACHE.mkdir(parents=True, exist_ok=True)
    body_p.write_bytes(r.content)
    meta = {
        "url": url,
        "method": method,
        "data": data,
        "status": r.status_code,
        "fetched_at": time.strftime("%Y-%m-%d"),
    }
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return r.content, meta, False


def fetch_text(method, url, data=None, refresh=False):
    raw, meta, hit = fetch(method, url, data, refresh)
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), meta, hit
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), meta, hit


_pw = None
_direct = False


def set_direct(enabled):
    """绕过环境代理直连（对被代理分流规则拦截的站点用）。"""
    global _direct
    _direct = enabled


def _request(method, url, **kw):
    if _direct:
        kw["proxies"] = {"http": None, "https": None}
    s = requests.Session()
    s.trust_env = not _direct
    return s.request(method, url, **kw)


def _get_browser():
    global _pw
    if _pw is None:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        kw = {"proxy": {"server": "direct://"}} if _direct else {}
        _pw.browser = _pw.chromium.launch(headless=True, **kw)
    return _pw.browser


def fetch_rendered(url, refresh=False, wait_ms=1500, timeout=35000, scroll=False):
    key = _key("RENDER", url, None)
    body_p = CACHE / (key + ".body")
    meta_p = CACHE / (key + ".meta.json")
    if body_p.exists() and not refresh:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        return body_p.read_text(encoding="utf-8"), meta, True
    b = _get_browser()
    page = b.new_page()
    try:
        try:
            page.goto(url, timeout=timeout, wait_until="networkidle")
        except Exception:
            page.wait_for_timeout(3000)
        page.wait_for_timeout(wait_ms)
        if scroll:
            for _ in range(8):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(600)
            page.wait_for_timeout(1500)
        html = page.content()
        status = 200
    finally:
        page.close()
    CACHE.mkdir(parents=True, exist_ok=True)
    body_p.write_text(html, encoding="utf-8")
    meta = {"url": url, "method": "RENDER", "status": status,
            "fetched_at": time.strftime("%Y-%m-%d")}
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return html, meta, False

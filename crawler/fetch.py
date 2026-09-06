import hashlib
import json
import re
import shutil
import subprocess
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
    try:
        r.raise_for_status()
    except requests.HTTPError as e:
        # WAF 质询页(瑞数 412/网防 403 等)自动降级走 CDP 真实浏览器
        if (_cdp_fallback and e.response is not None
                and e.response.status_code in (403, 412, 503) and not data):
            text, meta, _ = fetch_cdp(url)
            return text.encode("utf-8"), meta, False
        raise
    if _cdp_fallback and r.status_code == 202 and len(r.content) < 10000:
        # 网防(wengine)质询页走 202 短响应, requests 视为成功——按特征降级
        text, meta, _ = fetch_cdp(url)
        return text.encode("utf-8"), meta, False
    if _cdp_fallback and len(r.content) < 3000 and b"frms-fingerprint" in r.content:
        # 瑞数 200 指纹壳(浙大 person 等)——正文只有 JS 探针, CDP 执行质询后才有内容
        text, meta, _ = fetch_cdp(url)
        return text.encode("utf-8"), meta, False
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
        if _direct:
            _pw.browser = _pw.chromium.launch(
                headless=True, proxy={"server": "direct://"},
                args=["--no-proxy-server", "--proxy-bypass-list=*"])
        else:
            _pw.browser = _pw.chromium.launch(headless=True)
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


# ---- CDP 真实浏览器后端（破瑞数/网防等强 WAF：真实 Chrome 指纹 + 执行 JS 质询）----

CDP_PORT = 9222
_cdp = None
_cdp_fallback = False
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def set_cdp_fallback(enabled):
    """开启后 requests 遇 403/412/503 自动降级走 CDP 真实浏览器重试。"""
    global _cdp_fallback
    _cdp_fallback = enabled


def _chrome_exe():
    for p in _CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("chrome.exe")


def _cdp_alive():
    # 探测必须无视环境代理(用户环境是 SOCKS 127.0.0.1:10808, 会劫持回环地址)
    s = requests.Session()
    s.trust_env = False
    try:
        s.get(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2).raise_for_status()
        return True
    except Exception:
        return False


def _ensure_chrome_debug():
    """确保本机真实 Chrome 以调试端口运行（独立 profile，不动用户日常会话）。"""
    if _cdp_alive():
        return
    exe = _chrome_exe()
    if not exe:
        raise RuntimeError("chrome.exe not found; 安装 Chrome 或配置 _CHROME_CANDIDATES")
    profile = CACHE.parent / "chrome-profile"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [exe, f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={profile}",
         "--no-first-run", "--no-default-browser-check", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        time.sleep(0.5)
        if _cdp_alive():
            return
    raise RuntimeError("chrome debug instance did not start on port %d" % CDP_PORT)


def _get_cdp_browser():
    global _cdp, _pw
    if _cdp is None:
        _ensure_chrome_debug()
        from playwright.sync_api import sync_playwright
        if _pw is None:
            _pw = sync_playwright().start()
        _cdp = _pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    return _cdp


def fetch_cdp(url, refresh=False, wait_ms=2500, timeout=45000, scroll=False):
    """CDP 真实 Chrome 抓取。用浏览器默认上下文（保留 cookie/指纹），
    新开页用完即关。结果独立缓存键 CDP+url。"""
    key = _key("CDP", url, None)
    body_p = CACHE / (key + ".body")
    meta_p = CACHE / (key + ".meta.json")
    if body_p.exists() and not refresh:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        return body_p.read_text(encoding="utf-8"), meta, True
    b = _get_cdp_browser()
    ctx = b.contexts[0] if b.contexts else b.new_context()
    page = ctx.new_page()
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)
        if scroll:
            for _ in range(6):
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(500)
            page.wait_for_timeout(1200)
        html = page.content()
        status = 200
    finally:
        page.close()
    CACHE.mkdir(parents=True, exist_ok=True)
    body_p.write_text(html, encoding="utf-8")
    meta = {"url": url, "method": "GET+CDP", "status": status,
            "fetched_at": time.strftime("%Y-%m-%d")}
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return html, meta, False


def fetch_cdp_json(api_url, wait_ms=1500, refresh=False):
    """在 CDP 真实浏览器页面上下文里调用同源 XHR API——自动携带瑞数 cookie/签名
    （裸 requests/CDP 直连 API 会 Access denied）。锚点页每次先加载以稳拿质询 cookie。"""
    key = _key("CDPJSON", api_url, None)
    body_p = CACHE / (key + ".body")
    meta_p = CACHE / (key + ".meta.json")
    if body_p.exists() and not refresh:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        return body_p.read_text(encoding="utf-8"), meta, True
    b = _get_cdp_browser()
    ctx = b.contexts[0] if b.contexts else b.new_context()
    page = ctx.new_page()
    try:
        origin = re.match(r"(https?://[^/]+)", api_url).group(1)
        page.goto(origin + "/", timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)
        js = ("fetch(%r, {headers: {'X-Requested-With': 'XMLHttpRequest'}})"
              ".then(function(r){return r.text()})") % api_url
        text = page.evaluate(js)
        status = 200
    finally:
        page.close()
    CACHE.mkdir(parents=True, exist_ok=True)
    body_p.write_text(text or "", encoding="utf-8")
    meta = {"url": api_url, "method": "GET+CDPJSON", "status": status,
            "fetched_at": time.strftime("%Y-%m-%d")}
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return text, meta, False

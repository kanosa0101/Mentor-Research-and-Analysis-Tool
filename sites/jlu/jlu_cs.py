"""吉林大学计算机学院（ccst.jlu.edu.cn）。
详情页"Email："的值是防爬 PNG 图片（__local/…/xxx.png），明文不可得；
用 rapidocr 本地识别（单行小图 use_det=False 整图识别，6x 放大）。
OCR 常把 @ 后域名拆碎/漏字，而该院邮箱域几乎全为 jlu.edu.cn，
故修复策略：可靠取 @ 前 local part + 已知域名重组，整串合法则照用。
"""
import re
from urllib.parse import urljoin

from crawler import fetch
from sites.simple_list import parse_detail as _simple_parse, iter_roster as _simple_roster

_EMAIL_IMG = re.compile(
    r"(?:电子邮箱|Email|邮箱)\s*[：:]?\s*</td>\s*<td[^>]*>\s*<img\s+([^>]+)>", re.I)
# vsb CMS 的 img 真实路径常在 vurl 属性(src 可能是丢目录的相对名)
_VURL = re.compile(r'vurl="([^"]+)"', re.I)
_SRC = re.compile(r'src="([^"]+)"', re.I)
_EMAIL_OK = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_LOCAL_OK = re.compile(r"^[A-Za-z0-9._%+-]{2,30}$")
_OCR = None


def iter_roster(cfg):
    return _simple_roster(cfg)


def _repair_email(boxes):
    joined = " ".join(t for _, t, _ in boxes)
    # 混淆写法还原: "xxx at yyy" / "xxx [AT] yyy" → "@"; 必须在去空格前做
    joined = re.sub(r"(?i)(?<=\s)\[?\(?at\)?\]?(?=\s|$)", "@", joined)
    joined = re.sub(r"\s+", "", joined)
    if not joined:
        return None
    local = rest = None
    if "@" in joined:
        local, _, rest = joined.partition("@")
    else:
        # '@' 漏检: 从尾部剥已知域名(mail.)jlu[.edu[.cn]]
        m = re.search(r"(mail\.?)?jlu\.?(?:edu\.?cn)?$", joined, re.I)
        if m and m.start() >= 2:
            local = joined[:m.start()]
    if not (local and _LOCAL_OK.fullmatch(local)):
        return None
    # OCR 混淆: 行首大写 I 实为 l(lxf 误读 Ixf)
    if re.fullmatch(r"I[a-z0-9]+", local):
        local = "l" + local[1:]
    # OCR 常把域名拆碎/漏字("jlu.edu" + "cn"→"jlueducn" 乃至 "eedu.ccn"),
    # 一律去点后按已知模式匹配重组, 不信碎片整串
    nodots = re.sub(r"[^a-z0-9]", "", (rest or "").lower())
    if nodots.startswith("mailjlu") or nodots.startswith("mail"):
        return local + "@mail.jlu.edu.cn"
    if nodots.startswith("jlu") or nodots in ("", "educn", "edu", "cn"):
        return local + "@jlu.edu.cn"
    # 常见公共邮箱域(OCR 常见 "163.ccom" 形近错字)
    pm = re.fullmatch(r"(163|126|qq|sohu|sina|gmail|hotmail|yeah|aliyun|139|foxmail)cc?om", nodots)
    if pm:
        return local + "@" + pm.group(1) + ".com"
    if nodots == "yeahnet":
        return local + "@yeah.net"
    if _EMAIL_OK.fullmatch(joined):
        parts = (rest or "").lower().split(".")
        if len(parts) >= 2 and all(p for p in parts):
            return joined.lower()
    return None


def _ocr_email_image(img_url, page_url):
    global _OCR
    try:
        raw, _, _ = fetch.fetch("GET", img_url)
    except Exception:
        return None
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or min(img.shape[:2]) < 5:
        return None
    big = cv2.resize(img, None, fx=6, fy=6, interpolation=cv2.INTER_LANCZOS4)
    big = cv2.copyMakeBorder(big, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    # det 模型对细长低对比单行图常丢前段, 直接调识别模型整行读
    try:
        res, _ = _OCR.text_recognizer(cv2.cvtColor(big, cv2.COLOR_GRAY2BGR))
    except Exception:
        return None
    boxes = [[None, t, c] for t, c in (res or [])]
    return _repair_email(boxes or [])


def parse_detail(cfg, html, url):
    out = _simple_parse(cfg, html, url)
    if not out.get("email"):
        m = _EMAIL_IMG.search(html)
        if m:
            # vurl 有两种形态: /__local/…png 原图 或 /_vsl/… 缩略图(OCR 失败), 依次回退
            cands = []
            for rx in (_VURL, _SRC):
                sm = rx.search(m.group(1))
                if sm:
                    cands.append(sm.group(1))
            for src in cands:
                if src.startswith("__local"):
                    src = "/" + src
                if not src.startswith("http"):
                    src = urljoin(url, src)
                e = _ocr_email_image(src, url)
                if e:
                    out["email"] = e
                    break
    return out

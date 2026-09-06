import re

VALID = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$", re.A)
# 防 OCR/标签粘连把下个词吞进域名("jlu.edu.cnWechat"); 长 TLD 白名单外一律拒收
_LONG_TLDS = {"info", "online", "site", "club", "tech", "cloud", "email", "name"}


def _tld_ok(s):
    last = s.rsplit(".", 1)[-1].lower()
    return len(last) <= 3 or last in _LONG_TLDS


def _clean_token(tok):
    core = tok.strip("（）()[]{}【】.,;、")
    if core and re.search(r"[\u4e00-\u9fa5]", core) and "@" not in core:
        return ""
    if core in ("▇", "★", "＊", "*"):
        return "@"
    return core


def normalize_email(raw):
    if not raw:
        return None
    for chunk in re.split(r"[;；,，/、]+", raw.strip()):
        s = _tokens(chunk)
        if VALID.match(s) and _tld_ok(s):
            return s
    return None


def _tokens(raw):
    parts = []
    for tok in re.split(r"\s+", raw.strip()):
        c = _clean_token(tok)
        up = c.upper()
        if up == "AT" or c in ("@", "＠", "#"):
            parts.append("@")
        elif up == "DOT" or c == "。":
            parts.append(".")
        elif c:
            parts.append(c)
    s = "".join(parts)
    s = s.replace("＠", "@")
    s = re.sub(r"[(（【\[{]\s*(?:at|＠)\s*[)）\]}】]", "@", s, flags=re.I)
    s = re.sub(r"[(（【\[{]\s*(?:dot|点)\s*[)）\]}】]", ".", s, flags=re.I)
    return s


def join_email_fragments(*parts):
    return normalize_email(" ".join(p for p in parts if p))

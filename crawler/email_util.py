import re

VALID = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$", re.A)


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
        if VALID.match(s):
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

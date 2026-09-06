"""AI 归纳层工具：输入构建、指纹缓存键、JSON 解析、evidence 校验。

硬约束（REQUIREMENTS §8.2）：输入只限库内已抓材料；结论必带 evidence，
无 evidence 的断言丢弃；缓存键 = 输入指纹 + prompt_version + model。
"""
import hashlib
import json
import re


def build_input(prof) -> dict:
    """只取库内材料字段做 AI 输入，绝不掺其他来源。"""
    return {
        "name": prof.name or "",
        "title": prof.title or "",
        "supervisor": prof.supervisor or "",
        "institutes": list(prof.institutes or []),
        "facets": [f.id for f in (prof.facets or [])],
        "research_direction_raw": prof.research_direction_raw or "",
        "bio_raw": prof.bio_raw or "",
    }


def fingerprint(inp: dict, prompt_version: str, model: str) -> str:
    blob = json.dumps({"input": inp, "prompt_version": prompt_version,
                       "model": model}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def parse_llm_json(text: str):
    """容忍 code fence 与前后废话，提取第一个 JSON 对象。"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _norm(s: str) -> str:
    """匹配用归一：去全部空白，小写——容忍换行/空格差异，字符必须逐字一致。"""
    return re.sub(r"\s+", "", (s or "")).lower()


def validate_claims(claims, materials: dict):
    """evidence 硬校验：每条断言至少一条证据逐字（去空白）出现在材料里。

    返回 (kept_claims, dropped_count)。材料字典的值全部参与拼接。
    """
    hay = _norm(" ".join(str(v) for v in materials.values() if v))
    kept, dropped = [], 0
    for c in claims or []:
        text = (c.get("text") or "").strip()
        evs = [e.strip() for e in (c.get("evidence") or []) if e and e.strip()]
        if not text:
            dropped += 1
            continue
        good = [e for e in evs if _norm(e) and _norm(e) in hay]
        if not good:
            dropped += 1
            continue
        kept.append({"text": text, "evidence": good})
    return kept, dropped


def validate_ai_block(block: dict, materials: dict) -> bool:
    """preflight 用：AI 块整体复核（元数据齐全 + 全部证据可回溯）。"""
    if not block.get("model") or not block.get("prompt_version") \
            or not block.get("generated_at"):
        return False
    for key in ("research_summary", "highlights"):
        for c in block.get(key) or []:
            if not (c.get("text") or "").strip():
                return False
            if not any(e.strip() and _norm(e) in _norm(" ".join(
                    str(v) for v in materials.values() if v))
                    for e in c.get("evidence") or []):
                return False
    return True

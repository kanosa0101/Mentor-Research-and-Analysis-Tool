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
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                value = json.loads(m.group(0))
                return value if isinstance(value, dict) else None
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
    kept, dropped = [], 0
    if not isinstance(claims, list):
        return [], int(bool(claims))
    for c in claims or []:
        if not isinstance(c, dict) or not isinstance(c.get('text'), str) or not isinstance(c.get('evidence'), list):
            dropped += 1
            continue
        text = (c.get("text") or "").strip()
        evs = [e.strip() for e in c['evidence'] if isinstance(e, str) and e.strip()]
        if not text:
            dropped += 1
            continue
        # 自动公开层只接受原文摘录：文本必须包含于同一字段的引用片段中。
        # 这不是语义蕴含判断；自由改写仍需另外的人工审阅流程。
        binding = None
        good = []
        for field in ('research_direction_raw', 'bio_raw', 'title', 'supervisor', 'institutes'):
            material = materials.get(field)
            if isinstance(material, list):
                material = '、'.join(str(x) for x in material)
            if not isinstance(material, str):
                continue
            matches = [e for e in evs if _norm(e) in _norm(material) and _norm(text) in _norm(e)]
            if matches and (not c.get('source_field') or c['source_field'] == field):
                binding, good = field, matches
                break
        if not binding:
            dropped += 1
            continue
        kept.append({"text": text, "evidence": good, 'source_field': binding})
    return kept, dropped


def validate_ai_block(block: dict, materials: dict) -> bool:
    """preflight 用：AI 块整体复核（元数据齐全 + 全部证据可回溯）。"""
    if not block.get("model") or not block.get("prompt_version") \
            or not block.get("generated_at"):
        return False
    for key in ("research_summary", "highlights"):
        claims = block.get(key) or []
        _, dropped = validate_claims(claims, materials)
        if dropped:
            return False
    return True

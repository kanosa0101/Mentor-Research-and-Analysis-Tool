"""AI 归纳层：对导师库内材料做结构化归纳，产出去导师侧 research_summary/highlights。

硬约束（REQUIREMENTS §8.2 / PRODUCT_PLAN §4）：
- 输入只限库内已抓材料（ai_util.build_input）
- 结论必带 evidence（材料内逐字片段），无证据断言丢弃并计数
- 缓存优先：cache/ai/<sha1(输入指纹+prompt_version+model)>.json，--refresh 才回源
- 改 prompt 必升 PROMPT_VERSION

用法：
  python scripts/ai_enrich.py --school sjtu --dept cs [--refresh] [--limit N] [--dry] [--mock]
环境变量（OpenAI 兼容接口，任选一家）：
  AI_API_BASE  如 https://open.bigmodel.cn/api/paas/v4
  AI_API_KEY   密钥（不进 git）
  AI_MODEL     如 glm-4-flash / deepseek-chat
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests

from crawler import store
from crawler.ai_util import build_input, fingerprint, parse_llm_json, validate_claims

PROMPT_VERSION = "v1"
CACHE = ROOT / "cache" / "ai"

SYSTEM = """你是严谨的学术信息整理员。只依据给定材料归纳，禁止使用材料外的知识、
禁止推断材料中没有的事实（包括职称、头衔、方向）。输出中文 JSON：
{"research_summary": [{"text": "...", "evidence": ["材料中的逐字片段", ...]}],
 "highlights": [{"text": "...", "evidence": ["..."]}]}
要求：
- research_summary 2-4 条，每条 ≤50 字，概括研究对象/问题/方法定位
- highlights 1-3 条，每条 ≤50 字，只写材料中明确的事实（获奖、头衔、代表性成果）
- 每条 evidence 必须是材料中的**逐字片段**（可截取 ≤60 字符），每条断言至少 1 条
- 材料不足以支撑的断言直接不写；宁缺毋滥
只输出 JSON，不要多余文字。"""


def call_llm(inp: dict, cfg: dict) -> str:
    body = {
        "model": cfg["model"],
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": "材料：\n" + json.dumps(inp, ensure_ascii=False)}],
        "temperature": 0.2,
    }
    r = requests.post(cfg["base"].rstrip("/") + "/chat/completions", json=body,
                      headers={"Authorization": f"Bearer {cfg['key']}"},
                      timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def mock_llm(inp: dict) -> str:
    """管线自测用：从真实材料里抠片段当断言与证据，走完整 校验/缓存/落库 流程。"""
    claims = []
    if inp["research_direction_raw"]:
        claims.append({"text": f"官网自述方向：{inp['research_direction_raw'][:40]}",
                       "evidence": [inp["research_direction_raw"][:30]]})
    if inp["bio_raw"]:
        head = inp["bio_raw"][:50]
        claims.append({"text": f"简介开头：{head[:40]}", "evidence": [head[:30]]})
        claims.append({"text": "这条断言材料里没有支撑，应当被丢弃", "evidence": ["材料中不存在的句子"]})
    return json.dumps({"research_summary": claims, "highlights": []}, ensure_ascii=False)


def cache_path(fp: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{fp}.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--school", required=True)
    ap.add_argument("--dept", required=True)
    ap.add_argument("--refresh", action="store_true", help="忽略缓存回源重算")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 人（0=全部）")
    ap.add_argument("--dry", action="store_true", help="只打印将处理的输入，不调 API 不落库")
    ap.add_argument("--mock", action="store_true", help="自测：不调 API，用可校验的假响应走全流程")
    args = ap.parse_args()

    cfg = {"base": os.environ.get("AI_API_BASE", ""),
           "key": os.environ.get("AI_API_KEY", ""),
           "model": os.environ.get("AI_MODEL", "")}
    if not args.mock and not args.dry and not (cfg["base"] and cfg["key"] and cfg["model"]):
        sys.exit("缺 AI_API_BASE / AI_API_KEY / AI_MODEL 环境变量（--mock/--dry 不需要）")
    if args.mock:
        cfg["model"] = "mock"

    profs = store.load_all(args.school, args.dept)
    todo = sorted(profs.values(), key=lambda p: p.slug)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{args.school}/{args.dept}: {len(todo)} 人 | prompt {PROMPT_VERSION} | model {cfg['model']}")

    n_cached = n_called = n_saved = n_drop = n_skip = 0
    from crawler.model import AiBlock, AiClaim
    for p in todo:
        inp = build_input(p)
        if not (inp["bio_raw"] or inp["research_direction_raw"]):
            n_skip += 1
            continue
        fp = fingerprint(inp, PROMPT_VERSION, cfg["model"])
        cp = cache_path(fp)
        if cp.exists() and not args.refresh:
            rec = json.loads(cp.read_text(encoding="utf-8"))
            n_cached += 1
        else:
            if args.dry:
                print(f"[dry] {p.slug}: 输入 {sum(len(str(v)) for v in inp.values())} 字符 -> {fp[:10]}")
                continue
            raw = mock_llm(inp) if args.mock else call_llm(inp, cfg)
            rec = {"fingerprint": fp, "model": cfg["model"], "prompt_version": PROMPT_VERSION,
                   "generated_at": datetime.date.today().isoformat(),
                   "input": inp, "raw": raw}
            cp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            n_called += 1
            time.sleep(0.3)
        parsed = parse_llm_json(rec.get("raw") or "")
        if not parsed:
            print(f"[warn] {p.slug}: LLM 输出无法解析为 JSON，跳过")
            continue
        rs, d1 = validate_claims(parsed.get("research_summary"), inp)
        hl, d2 = validate_claims(parsed.get("highlights"), inp)
        n_drop += d1 + d2
        if not rs and not hl:
            continue
        p.ai = AiBlock(model=cfg["model"], prompt_version=PROMPT_VERSION,
                       generated_at=rec["generated_at"],
                       research_summary=[AiClaim(**c) for c in rs],
                       highlights=[AiClaim(**c) for c in hl])
        store.save_professor(p)
        n_saved += 1
    print(f"完成: 缓存命中 {n_cached} | 调用 {n_called} | 落库 {n_saved} | "
          f"无证据丢弃 {n_drop} | 无材料跳过 {n_skip}")
    print("注意: Professor.ai 属生成数据，如需回滚: git checkout -- data/professors/")


if __name__ == "__main__":
    main()

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler import store
from crawler.model import Facet

RULES = [
    ("topic.llm", r"大模型|大语言模型|LLM|GPT|语言模型|生成式|AIGC"),
    ("topic.nlp", r"自然语言处理|NLP|文本(挖掘|分析|理解)|问答"),
    ("topic.cv", r"计算机视觉|视觉|图像|影像|视频(理解|分析)|多模态"),
    ("topic.ml", r"机器学习|深度学习|强化学习|数据挖掘|联邦学习"),
    ("topic.systems", r"操作系统|体系结构|系统结构|分布式|并行计算|高性能计算|编译|存储系统"),
    ("topic.security", r"网络空间安全|密码|安全|隐私|攻防|漏洞"),
    ("topic.graphics", r"图形学|可视化|渲染|虚拟现实|数字人"),
    ("topic.db", r"数据库|大数据|知识图谱|数据管理"),
    ("topic.network", r"计算机网络|网络技术|物联网|边缘计算|无线|5G|6G"),
    ("topic.theory", r"算法博弈论|理论计算机|计算复杂|形式化|算法设计"),
    ("topic.robotics", r"机器人|具身|无人系统|自动驾驶"),
    ("topic.hci", r"人机交互|普适计算|可穿戴"),
    ("topic.bio", r"生物信息|医学影像|医疗|基因组|药物"),
]


def match(text):
    hits = []
    for fid, pat in RULES:
        m = re.search(pat, text, re.I)
        if m:
            hits.append((fid, m.group(0)))
    return hits


def main():
    for f in sorted(Path("data/professors").glob("*/*/*.yaml")):
        d = store._yaml_load(f)
        old = {x["id"] for x in d.get("facets", []) if x.get("origin") == "computed"}
        text = " ".join(str(d.get(k) or "") for k in
                        ("research_direction_raw", "bio_raw"))
        text = text[:1500]
        hits = match(text)
        facets = [Facet(id=fid, origin="computed", confidence="auto",
                        evidence=[f"keyword:{kw}"]) for fid, kw in hits]
        d["facets"] = [x.model_dump(mode="json") for x in facets]
        import yaml
        f.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False),
                     encoding="utf-8")
    print("facets computed for all records")


if __name__ == "__main__":
    main()

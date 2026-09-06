"""从详情页文本提取导师资格(博导/硕导)。

三级来源, 按可靠性排序:
1. 结构化字段: jlu "是否博导：是"、tongji "导师类型 博／硕导"
2. 头部徽标行: people.ucas.ac.cn "曹亚男 女 博导 中国科学院信息工程研究所"
3. 简介自述: 职称后紧跟导师资格("长聘教轨副教授、博士生导师" / "研究员、博导")
   ——必须职称相邻, 否则 ustc 站内导航"兼职教授/博导"这类栏目名会混入。

返回 "博导" / "硕导" / "博导、硕导" 或 None。绝不从"是否博导：否"取值。
"""
import re

_SUP_WORD = r"(?:博士生导师|硕士生导师|博导|硕导)"

# (结构化标签正则, 值)
_STRUCT = [
    (r"是否博导\s*[:：]\s*是", "博导"),
    (r"是否硕导\s*[:：]\s*是", "硕导"),
    (r"导师类型\s*博\s*[／/]\s*硕导", "博导、硕导"),
    (r"导师类型\s*[:：]?\s*博导(?![／/]?\s*硕)", "博导"),
    (r"导师类型\s*[:：]?\s*硕导", "硕导"),
]

_BADGE = re.compile(
    r"[\u4e00-\u9fa5·]{2,4}[\s\u00a0]+(?:男|女)[\s\u00a0]+"
    rf"({_SUP_WORD}[\s\u00a0]*)+")
# 职称 + 顿号/逗号/斜杠 + 导师资格; 允许"博士"垫词("副教授，博士，博士生导师")
_BIO_ADJ = re.compile(
    rf"(?:教授|研究员|讲师|工程师)\s*[、，,／/]\s*"
    rf"(?:博士\s*[、，,／/]\s*)?({_SUP_WORD})"
    rf"(?:\s*[、，,]\s*{_SUP_WORD})*")


def extract_supervisor(text):
    if not text:
        return None
    out = []

    def _add(val):
        for v in val.split("、"):
            if v and v not in out:
                out.append(v)

    for pat, val in _STRUCT:
        if re.search(pat, text):
            _add(val)
    if out:
        return "、".join(out)

    m = _BADGE.search(text)
    if m:
        for b in dict.fromkeys(re.findall(_SUP_WORD, m.group(0))):
            _add("博导" if "博" in b else "硕导")
        if out:
            return "、".join(out)

    for m in _BIO_ADJ.finditer(text):
        for b in re.findall(_SUP_WORD, m.group(0)):
            _add("博导" if "博" in b else "硕导")
        if out:
            return "、".join(out)
    return None

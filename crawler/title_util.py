"""职称值规范化：官网写法五花八门（括号带导师资格、顿号长尾、斜杠多值、
内部空格、级别词），统一为可筛选的规范形态。确定性规则，无推测。"""
import re

# 前缀 + 核心；长词在前防止"副教授"吃掉"长聘副教授"的前缀
_TITLE_RE = re.compile(
    r"^(讲席|特聘|长聘教轨|长聘|准聘|预聘|兼职|客座|荣誉|正高级|副高级)?"
    r"(教授级高级工程师|正高级工程师|教授|副教授|助理教授|研究员|副研究员|"
    r"助理研究员|青年研究员|青年副研究员|高级工程师|高级实验师|正高级实验师|"
    r"工程师|助理工程师|实验师|馆员|研究实习员|讲师|助教|院士)$")

# 无锚点版: 兜底搜索用
_TITLE_SEARCH_RE = re.compile(
    r"(讲席|特聘|长聘教轨|长聘|准聘|预聘|兼职|客座|荣誉|正高级|副高级)?"
    r"(教授级高级工程师|正高级工程师|教授|副教授|助理教授|研究员|副研究员|"
    r"助理研究员|青年研究员|青年副研究员|高级工程师|高级实验师|正高级实验师|"
    r"工程师|助理工程师|实验师|馆员|研究实习员|讲师|助教|院士)")

# 级别词 → 规范级别（官网只给级别时）
_LEVELS = {"副高": "副高级", "正高": "正高级", "中级": "中级", "副研": "副研究员",
           "教授级高工": "教授级高级工程师"}

# 出现在职称标签位但不是职称的词(如 fudan exField1 "教师、博导"): 剥掉,
# 导师资格照常并入 supervisor; 若剥完为空则职称置空
_DROP_SEGS = {"教师"}

# 分段别名 → 规范词(hnu "教授级高工"是"教授级高级工程师"缩写)
_SEG_FIX = {"教授级高工": "教授级高级工程师"}

_SUP_TOKEN = re.compile(r"博士生导师|硕士生导师|博导|硕导")


def normalize_title(value):
    """返回 (规范化职称, 从串里析出的导师资格或 None)。无法识别时原样返回。"""
    if not value:
        return value, None
    s = re.sub(r"[\s\u3000]+", "", str(value))
    sup_bits = set()

    # 括号内容：导师资格并入 supervisor，其余丢弃（如"（院士）"荣誉后缀）
    parens = re.findall(r"[（(]([^（）()]*)[）)]", s)
    core = re.sub(r"[（(][^（）()]*[）)]", "", s)
    # 分段：顿号/斜杠/逗号长尾里也可能带导师资格（"教授、博士生导师"）
    segs = [x for x in re.split(r"[、，,;/]", core) if x]
    for part in parens + segs:
        for m in _SUP_TOKEN.finditer(part):
            # 注意 "博导" 里没有"博士"二字, 不能用 in 判断
            sup_bits.add("硕导" if m.group(0) in ("硕导", "硕士生导师") else "博导")
    sup_out = "、".join(sorted(sup_bits)) if sup_bits else None

    # "博导/硕导"这类纯导师资格串不是职称——置空, 资格并 supervisor
    if segs and all(_SUP_TOKEN.fullmatch(s) or s in _DROP_SEGS for s in segs):
        return None, sup_out
    for seg in segs:
        if seg in _DROP_SEGS:
            continue
        m = _TITLE_RE.fullmatch(_SEG_FIX.get(seg, seg))
        if m:
            return (m.group(1) or "") + m.group(2), sup_out
    m = _TITLE_RE.fullmatch(_SEG_FIX.get(core, core))
    if m:
        return (m.group(1) or "") + m.group(2), sup_out
    # 级别词
    if core in _LEVELS:
        return _LEVELS[core], sup_out
    # 兜底：整串搜规范词（复合词如"副高级研究员"整串无匹配才走到这里,
    # 为忠实官网措辞, 整串本身就是词表超集时原样保留）
    m = _TITLE_SEARCH_RE.search(core)
    if m and len(m.group(0)) < len(core):
        return (m.group(1) or "") + m.group(2), sup_out
    return str(value), sup_out

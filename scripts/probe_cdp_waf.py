"""CDP 后端探针：验证真实 Chrome 能否过瑞数/网防（北邮/重大/电子科大）。"""
import sys

sys.path.insert(0, ".")

from crawler import fetch

fetch.set_direct(True)          # 北邮等走直连(与之前探测口径一致)
fetch.set_cdp_fallback(True)

TARGETS = [
    ("北邮-计算机名录", "https://scs.bupt.edu.cn/szjs1/jsyl.htm"),
    ("北邮-tsites主页", "https://teacher.bupt.edu.cn/zhoufeng/zh_CN/index.htm"),
    ("重大-计算机学院", "https://cs.cqu.edu.cn/"),
    ("电子科大-首页", "https://www.scse.uestc.edu.cn/"),
]

for name, url in TARGETS:
    try:
        text, meta, hit = fetch.fetch_text("GET", url)
        how = meta.get("method", "?")
        ts = "$_ts" in text
        print(f"{name}: {len(text)}B method={how} cache={hit} 瑞数标记={ts}")
        print("   head:", text[:120].replace("\n", " "))
    except Exception as e:
        print(f"{name}: FAIL {repr(e)[:120]}")

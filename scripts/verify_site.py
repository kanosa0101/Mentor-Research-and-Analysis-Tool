import pathlib
import subprocess

idx = pathlib.Path("site/index.html").read_text(encoding="utf-8")
assert "sjtu-ai-yangxiaokang" in idx, "ai page link missing"
assert idx.count("<script>") >= 1
d = pathlib.Path("site/p/sjtu-cs-zangbinyu.html").read_text(encoding="utf-8")
print("detail ok:", "最近核对" in d, "| provenance rows:", d.count("o-crawled"))
a = pathlib.Path("site/p/sjtu-ai-yangxiaokang.html").read_text(encoding="utf-8")
print("ai detail ok:", "智能感知认知" in a, "| title:", "正高" in a or "research" in a)
r = subprocess.run(
    ["python", "-c", "import urllib.request;print(urllib.request.urlopen('http://localhost:8000/').status)"],
    capture_output=True, text=True)
print("server:", r.stdout.strip() or r.stderr.strip()[:100])

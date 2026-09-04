# 导师调研工具

需求见 `REQUIREMENTS.md`（v0.5）。当前：**15 校 19 院系 2619 人**——上交计算机学院 289 / AI 研究院 1、清华 134、北大 119、哈工大 240（研究中心分组，纯名录无详情页）、中科院计算所 283 / 自动化所 345 / 软件所 182 / 信工所 230、中科大 72、南大 102、武大 109、同济 156、山大 11（官网师资页空壳）、中大 112、东北大学 147、吉大 36、华东师大 28（官网单页仅此数）、西工大 23（roster_only，教师系统被 WAF 拦）。字段含姓名/职称/博导硕导标识/研究所/邮箱/个人主页/研究方向/简介原文，全部带出处。

站点范式：AJAX HTML（上交）、JSON API（上交 AI 研究院）、CAS 网站群（计算所/自动化所，含计算所 JS 变量内嵌人才库）、WP/博达 CMS（清华/中科大/南大/武大/同济/山大/北大/东北大学/吉大/华东师大）、JS 渲染名录（哈工大 tbody 网格、中大懒加载卡片）。Playwright 渲染已接入（缓存/滚动/networkidle 降级）。`roster_only` 配置开关用于详情页不可抓的站点（nwpu）。邮箱全库经混淆还原与校验（`crawler/email_util.py`）。

**网络环境说明**：本机请求经本地代理 `127.0.0.1:10808` 出网。此前"连不上"的学校（北邮/西电/南科大/上科大/西交/华南理工/人大/电子科大/中南/湖大/川大/重大/北师大/南开）实为代理分流规则拦截 `.edu.cn`——在代理软件中将 `*.edu.cn` 设为 DIRECT 后重跑 `scripts/retest_network.py` 与对应 `crawl.py` 即可入库。

待处理：复旦（名录登录墙）、浙大（整站 SPA）、北理工（名录懒加载+按研究所分页，需交互式抓取）、厦大（师资页待定位）、东南（导师库混合外链，待专用钩子）、大工软件学院（频道待定位）。

## 常用命令

```powershell
python scripts\crawl.py --school sjtu --dept cs     # 抓取（缓存优先，重跑零新请求）
python scripts\crawl.py --school sjtu --dept cs --refresh   # 强制重新抓取（检测官网变化）
python scripts\build_site.py                        # 重建静态网页 site/
python -m http.server 8000 --directory site         # 本地预览 http://localhost:8000
```

## 更新机制（院系合并 / 导师简历变化怎么办）

- **重跑即更新**：`crawl.py --refresh` 绕过缓存重新抓取。字段级比对，有变化的字段写入 `data/changes/<school>-<dept>.jsonl`（日期、字段、旧值、新值），文件不重写只追加，可审计。
- **字段级新鲜度**：每条 provenance 带抓取日期；每人有 `first_seen`（首次入库）/ `last_verified`（最近核对）。
- **官网自报更新时间**：站点提供时自动记录（如 AI 研究院 API 的 `updatedAt` → `source_updated_at`）。
- **名单变化**：官网名单里消失的人记入 `data/issues/<school>-<dept>.yaml`（kind=missing_in_list），不会静默删除；新增的人自动入库。
- **手改安全**：provenance 里 `origin: manual` 的字段重跑不覆盖。

## 拓展新院系 / 学校（三步）

1. 写配置 `sites/<school>/<dept>.yaml`：`school` / `dept` / `dept_name` / `base_url` / `hook` / `list`（列表入口）。
2. 写钩子 `sites/<school>/<hook>.py`，实现两个函数：
   - `iter_roster(cfg)` → `[{"name", "url", "profile_url"?, "institutes"?, "aliases"?}, ...]`
   - `parse_detail(cfg, html, url)` → `{"name", "title", "email", "bio_raw", ...}`（拿不到的字段省略即可）
   - 已有两种范式可抄：`sjtu_cs.py`（AJAX 返回 HTML 片段）、`sjtu_ai.py`（纯 JSON API）。
3. `python scripts\crawl.py --school <school> --dept <dept>`，然后 `build_site.py`。

学校清单在 `data/schools.yaml`（tier/include/note）。院系粒度一条配置一个。

## 目录

```
crawler/   fetch(缓存+限速) model(pydantic) store(YAML+issues+changes)
sites/     <school>/<dept>.yaml 配置 + <hook>.py 解析钩子
data/      professors/<school>/<dept>/<slug>.yaml · issues/ · changes/ · schools.yaml
cache/     http/ 原始响应缓存（不进 git）
site/      生成的静态网页（index + p/*.html）
scripts/   crawl.py 入口 · build_site.py 网页生成
```

# 导师调研工具

需求见 `REQUIREMENTS.md`（v0.4）。当前：11 校 15 院系 2385 人——上交计算机学院 289、上交 AI 研究院 1、清华计算机系 134、北大计算机学院 119、哈工大计算学部 240（研究中心分组，纯名录无详情页）、中科院计算所 283 / 自动化所 345 / 软件所 182 / 信工所 230、中科大计算机学院 72、南大计算机系 102、武大 109、同济 156、山大 11（官网师资页多为空壳）、中大计算机学院 112（姓名/职称/邮箱/研究所/研究领域）。字段含姓名/职称/博导硕导标识/研究所/邮箱/个人主页/研究方向/简介原文，全部带出处。

站点范式：AJAX HTML（上交）、JSON API（上交 AI 研究院）、CAS 网站群（计算所/自动化所，含 JS 变量内嵌数据的计算所人才库）、WP/博达 CMS（清华/中科大/南大/武大/同济/山大/北大）、JS 渲染名录（哈工大 tbody 网格、中大懒加载卡片列表，`fetch_rendered` 支持滚动加载与 networkidle 降级）。Playwright 渲染抓取已接入（带缓存）。

当前网络环境不可达的学校（连接被重置，Playwright 也无法绕过）：北邮、西电、南科大、上科大、西交、华南理工、人大、电子科大、中南；国防科大（军队院校）未采集；复旦（名录在登录墙后）、浙大（整站 SPA 无服务端内容）、北理工（名录按研究所分页且教师懒加载，待交互式抓取）记录在案待换源；邮箱全库经过混淆还原与校验（`crawler/email_util.py`）。

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

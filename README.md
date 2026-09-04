# 导师调研工具

需求见 `REQUIREMENTS.md`（v0.5）。当前：**22 校 26 院系 3664 人**——上交计算机学院 289 / AI 研究院 1、清华 134、北大 119、哈工大 240（研究中心分组，纯名录无详情页）、中科院计算所 283 / 自动化所 345 / 软件所 182 / 信工所 230、中科大 72、南大 102、武大 109、同济 156、山大 11（官网师资页空壳）、中大 112、东北大学 147、吉大 36、华东师大 28（官网单页仅此数）、西工大 23（roster_only，教师系统被 WAF 拦）、人大高瓴 AI 学院 31、西电 155、中南 108、**北师大 AI 学院 72、西交 75、川大 166、浙大 438**（后四所 2026-09-04 新增；浙大含 374 名录级导师，博导/硕导来自官方 2026 目录 xlsx，覆盖 99%）。字段含姓名/职称/博导硕导标识/研究所/邮箱/个人主页/研究方向/简介原文，全部带出处；方向 facet（topic.llm/cv/systems/... 13 类，`scripts/tag_facets.py` 可重算），列表页可按方向筛选。

站点范式：AJAX HTML（上交）、JSON API（上交 AI 研究院）、CAS 网站群（计算所/自动化所，含计算所 JS 变量内嵌人才库）、WP/博达 CMS（清华/中科大/南大/武大/同济/山大/北大/东北大学/吉大/华东师大/人大/西电）、JS 渲染名录（哈工大 tbody 网格、中大懒加载卡片、浙大名录）、tsites 教师主页系统（中南/西电/川大/西交——邮箱/电话密文可调官网 `tsitesencrypt.jsp` 服务端解密还原，见 `sites/tsites.py: decrypt_encrypted_fields`）、官方 xlsx 导师目录（浙大，openpyxl）。Playwright 渲染已接入（缓存/滚动/networkidle 降级）。`roster_only` 配置开关用于详情页不可抓的站点（nwpu）。邮箱全库经混淆还原与校验（`crawler/email_util.py`）。

**网络环境说明**：本机请求默认经本地代理 `127.0.0.1:10808` 出网；"连不上"的学校实为代理分流规则拦截 `.edu.cn`。两步可用：
1. 配置里加 `direct: true`（爬虫绕过代理直连，Playwright 同步走 direct），配合 `fetch` 内置 3 次重试；
2. 直连对部分学校**间歇性通断**（南开/华科实测：时通时重置），稳定时段重跑即可。

实测直连结果：**中南/西电/川大/北师大/西交**用 direct 模式实际可通（此前 retest 判定"被重置"系误报或当时网络抖动，均已接入）；浙大 www.cs.zju.edu.cn 走代理 http 可达（https SSL 失败、direct 被重置）；南开/华科可通但极不稳定（待稳定时段重跑）；北邮/重大/湖大/电子科大/华南理工/人大信息学院直连仍被重置，疑似运营商或校方 WAF 级阻断。`scripts/retest_direct.py` 可随时重测。

待处理（按处理方式分类）：
- **SPA/JS 懒加载，需 API 逆向**：南科大（faculty 子页卡片 JS 加载）、上科大（szdwx 列表 JS 加载）、复旦（登录墙）
- **待定位名录页**：东南（导师库混合外链，可用 dsxx 专用钩子）、厦大、大工软件学院
- **WAF 拦截（412/202），需带 cookie/会话重试**：北邮（scs.bupt.edu.cn）、重大（412）、湖大（ConnectionError 间歇）
- **网络不可达**：人大信息学院、华南理工（www2）、电子科大、南开/华科（间歇）等，详见下节

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

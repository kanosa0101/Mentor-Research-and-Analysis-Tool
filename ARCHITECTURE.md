# 架构文档（ARCHITECTURE）

> 系统组成、数据流、数据模型、抓取框架、站点范式与设计不变量。
> 配套：`REQUIREMENTS.md`（需求与决策）、`HANDOVER.md`（开发手册：现状/踩坑/操作）。代码级踩坑细节都在 HANDOVER §10。

---

## 1. 总览

系统是一个**爬取管线 + 静态站点生成器**，另有可选本地私人工作流服务：

```
sites/<school>/<dept>.yaml（每院系一份配置）
        +
sites/<school>/<hook>.py 或通用钩子（解析适配）
        │
        ▼
scripts/crawl.py ──► crawler/fetch.py（缓存优先 HTTP/渲染层）
        │                │
        │                ▼
        │           cache/http/<sha1>.body+.meta.json（原始响应，重跑零新请求）
        ▼
   roster（名单：姓名/职称/详情页URL）
        ▼
   enrich（逐个抓详情页，按字段映射解析）
        ▼
crawler/store.py ──► data/professors/<school>/<dept>/<slug>.yaml（一人一文件，pydantic 校验）
                 ──► data/issues/<school>-<dept>.yaml（失败/消失留痕）
                 ──► data/changes/<school>-<dept>.jsonl（字段变更，只追加）
        ▼
scripts/build_site.py ──► site/（Jinja2 模板 → 静态 HTML，进 git，双击即开）
```

两阶段入库：`roster`（仅名单，立即可浏览）→ `enriched`（详情已富化）。`--phase` 可单独跑某一阶段。

## 2. 目录结构

```
crawler/            核心库（与具体学校无关）
  fetch.py          HTTP 层：缓存/限速 0.5s/3 次重试/直连开关/Playwright 渲染
  model.py          pydantic 模型：Professor / Provenance / Facet / Issue
  store.py          YAML 读写 / issues / changes(JSONL) / 手改保护
  email_util.py     邮箱混淆还原 + 严格校验（re.A 防 CJK 混入）
  title_util.py     职称归一化（词表 + 导师资格括号拆分）
sites/              适配层（每校一个目录）
  wp.py             博达/WP CMS 通用钩子（频道+翻页+meta description 兜底）
  simple_list.py    单页静态名录通用钩子
  tsites.py         tsites 教师系统通用钩子（含密文解密）
  <school>/<dept>.yaml    一院系一配置（入口 URL/person_href/hook/direct/roster_only）
  <school>/<hook>.py      该校解析钩子（通用钩子覆盖不了才写）
scripts/            入口与一次性工具（crawl/build_site/audit/preflight/tag_facets/serve…）
data/               产出（进 git）：schools.yaml · professors/ · issues/ · changes/
                    + data/outreach.yaml（套磁跟进，**不进 git**，仅 serve.py 读写）
cache/http/         原始响应缓存（gitignore）
site/               生成的静态网站（进 git；跟进数据不经生成文件）
```

## 3. 数据模型

### 3.1 一位导师（YAML 节选）

```yaml
slug: zangbinyu            # 拼音；同院系撞名加 -2；跨院系同名是合法双聘，不去重
name: 臧斌宇
school: sjtu
dept: cs
status: enriched           # roster → enriched → verified(人工核对，未启用)
title: 长聘教授
supervisor: 博导
email: byzang@sjtu.edu.cn
institutes: [并行与分布式系统研究所]
bio_raw: "..."             # 官网简介原文，原样保存
first_seen: '2026-09-02'
facets:                    # 方向标签，origin=computed 可随时重算
  - {id: topic.systems, origin: computed, confidence: auto, evidence: [keyword:操作系统]}
provenance:                # 每字段出处
  title: {origin: crawled, source: https://..., fetched_at: '2026-09-02', confidence: auto}
```

### 3.2 provenance

按字段路径索引，`origin ∈ {crawled, computed, ai, manual}`，`confidence ∈ {verified, auto, unverified}`。本期只用 `crawled` + `manual`；`ai` 留给延后层（必须带 model/prompt_version/evidence）。

2026-10-13 更新：AI 模型与摘录管线已实现，真实 API 试验仍待验收。`last_parsed` 表示最近解析；`last_fetched` 表示详情响应真实来源日期（缓存命中保留旧日期）；历史 `last_verified` 不作为人工核验标记。页面使用来源日期并显示超过 30 天/未知的人数。人工 fields 和非 computed facets 都受保护。

### 3.3 三条不变量（管线任何改动都不能破坏）

1. `origin: manual` 的字段重跑不覆盖——用户手改受保护
2. `normalize_email` 返回 None 的无效值不覆盖有效值
3. 官网名单里消失的人记 issue（missing_in_list），恢复出现自动销账，**绝不静默删除**

配套：changes JSONL 只追加，任何字段变化（含"消失"）可审计回放。

## 4. 抓取框架（crawler/fetch.py）

| 能力 | 说明 |
| ---- | ---- |
| 缓存优先 | `cache/http/<sha1>.body + .meta.json`；重跑零新请求；`--refresh` 才回源 |
| 限速重试 | 0.5s 节流 + 3 次重试（退避 3s/6s），对 flaky 官网必备 |
| direct 模式 | 配置 `direct: true` → requests 绕过环境代理；Chromium 用 `--no-proxy-server`（`proxy={direct://}` 不可靠，踩过坑） |
| 渲染抓取 | `fetch_rendered`：networkidle 超时自动降级；可选滚动加载（懒列表） |
| 编码 | 按响应头 + 内容嗅探双通道（老站 GBK 常见） |

## 5. 站点适配层：七种已打通范式

新学校先对号入座，通用钩子不够才写专用钩子：

| # | 范式 | 学校 | 钩子 |
| - | ---- | ---- | ---- |
| 1 | AJAX 返回 HTML 片段（POST+JSON 包裹） | 上交计算机学院 | sjtu_cs.py |
| 2 | 纯 JSON API | 上交 AI 研究院 | sjtu_ai.py |
| 3 | CAS 网站群静态分页（含 JS 变量内嵌人才库） | 计算/自动化/软件/信工所 | cas_lists.py, ucas_*.py |
| 4 | WP/博达 CMS（listN 翻页 + meta description 字段打包） | 清华/中科大/南大/武大/同济/山大/北大/东北/吉大/华东师大 | wp.py, simple_list.py, pku_cs.py |
| 5 | JS 渲染名录（requests 拿到空壳） | 哈工大/中大/中南 | hit_cs.py, sysu_cs.py, tsites.py |
| 6 | tsites 教师系统（XHR 列表 + 服务端解密接口还原邮箱/电话密文） | 中南/西电/川大/西交/大工 | tsites.py（多校委托） |
| 7 | sudy WP generalQuery POST 接口（siteId + exField 条件 + rows=999） | 上科大、复旦 | sist_cs.py, fudan_cs.py |

通用钩子的配置开关：`direct: true`（绕代理）、`roster_only: true`（详情页不可抓时只收名单）。

**加新学校三步**：① 写 `sites/<school>/<dept>.yaml`（先 websearch 核实官方域名）② 通用钩子不够时写钩子（`iter_roster` + `parse_detail`）③ `crawl.py --school X --dept Y` → `build_site.py`。

## 6. 静态站点与本地服务

- 列表页：搜索、学校→院系级联、职称/导师资格/方向（13 类 facet）多选筛选、全列排序、列显示开关（localStorage）、分页（20/50/100/500）、跟进列（⭐ 标意向）
- 详情页：字段卡片 + 套磁跟进卡片（状态/备注/历史） + 简介原文 + provenance 出处表（逐字段点回官网原文）+ 新鲜度（first_seen/last_verified/官网 updatedAt）
- 看板页 board.html：5 列拖拽看板 + 搜索加人 + 邮箱一键复制；对比页 compare.html：列表勾选 2–5 人并排比较（选人存 localStorage，逐字段带出处，纯静态）
- **跟进状态走运行时**：`scripts/serve.py`（stdlib ThreadingHTTPServer，只绑 127.0.0.1）静态托管 site/ 并提供 `GET /api/health`、`GET/PATCH/DELETE /api/outreach/<page-id>`，原子写 `data/outreach.yaml`（gitignore）。页面动态探测加载，file:// 协议门控降级只读——**跟进数据绝不进生成文件/公开仓库**
- **表头表体由同一份 `HEADERS` 数组生成**——两次错位事故后的铁律
- 零构建：Jinja2 模板 `site/templates/` → `build_site.py` 生成，生成物进 git；重建时自动清理失效详情页（防孤儿页）

2026-10-13 增量：列表/看板/对比共用精简 `site/data.js`；完整简介搜索只在输入检索时加载 `search.js`，对比附加材料仅在对比页加载 `compare-data.js`。模板开启 HTML 转义，来源链接限制 HTTP(S)。私人跟进增加 `next_action`、`due_date`、`tags`，备份恢复 API 校验同源请求及备份结构。

通知试验由 `sites/notices.yaml` 配置三个官方栏目，`monitor_notices.py` 输出 `data/notices.json` 与栏目变化历史，生成 `site/notices.html`。只监测当前栏目页，标题年份不自动转换成入学年份或截止日期，失败不删除历史通知。

## 6.1 联系闭环（2026-10-14）

2026-10-14 联系闭环：`crawler/contact_util.py` 包装四类基础工作流，提供 v1→v2 内存兼容、targets（project+mentor 唯一）、drafts 和沟通发送快照；基础扫描与记录校验仍由 `workflow_util.py` 承担。`desk.html / desk.js` 为任务入口，项目材料管理保留 `applications.html`。保存、导出草稿和实际发送确认分开；EML 仅由同源本地 API 即时返回，附件正文不写 YAML/静态/Git。回复、目标阶段与可选提醒在锁内同一次原子文件替换提交。备份外层随 workflow 使用 v2，恢复兼容匹配的 v1/v2；GET 不写回升级结果。

## 6.2 条件发现与共用 UI（2026-10-14）

`discovery-core.js` 是独立纯规则函数：院校范围、逐字段关键词、对应学位资格、邮箱、人工招生机会/个人资格；硬条件排除，软条件计数排序，未知默认保留。`discovery.js` 负责按需加载来源/简介、证据卡片和目标传递。私人 `discovery.yaml` schema1 由 `discovery_util.py` 与 `/api/discovery` 校验、原子保存与独立备份恢复，GET 不写。核验固定四项上下文、日期和人工出处，与 workflow v2 无迁移关系。

`ui.css`、`_ui_head.html.j2`、`_nav.html.j2` 为八类页面共用视觉/导航入口；原有页面交互IDs保留。通知页查询参数限定院系，未接入时显式提示且不冒用其他院系结果。研究文字匹配和招生资格判断分别展示，不提供录取概率。

## 6.3 学校与招生政策（2026-10-14）

`data/admissions.yaml` 为独立公开人工摘要：登记原文/附件落地页、层级与年度/学位/渠道/专业范围、各字段原文短片段/定位、人工日期与指纹。`admissions_util.py` 校验，不接入私人写入API。`check_admissions.py` 调用现有缓存/限速fetch，只观测登记来源，写独立公开 `admissions_checks.json`，失败保留历史成功；只有实际网络成功能清除此前失败。

`build_site.py` 校验并生成 `admissions-data.js`（公开规则、检查、既有学校院系目录与栏目入口）及页面。`admissions-core.js` 处理范围与质量状态，不做个人资格判定或层级覆盖。`admissions.js` 显示规则及缺失类别；URL无效范围不扩大查询。`discovery.js` 的学校/院系入口范围是临时上下文，与私人条件分开；workflow只用已知公开policy ID预填项目，主动提交才写。

学校通用与院系/专业规则并列；源码指纹检查不是完整政策发现，年度目录及新增通知仍需额外核对。7/30天提醒阈值分别对应来源检查/人工摘要年龄，不代表政策有效期。

## 6.4 CS相关院系覆盖（2026-10-14）

`sites/related_roster.py` 复用既有fetch与详情解析，支持指定分页和公开POST名单、受限链接、姓名+链接去重、逐页出处/日期及特定字段选择器。空登记页按失败处理；当前职称排除学位和明确历史任职。`crawl.py` 新钩子接收逐条名单来源，旧钩子保持默认行为。

`crawler/unit_util.py` 按院系名称生成导航分类，公开载荷带 `unit_groups`；目录覆盖全部配置，空名单可用 `roster_pending` 说明，区别于未接入。分类只用于发现/政策导航，私人条件schema不变。政策可选 `track` 与带原文定位的 `events`，普通/专项范围分开；日期级事件按中国日期显示，精确时间要求时区。既有学校通用规则保持并列。

## 6.5 院系信息卡与受限补齐（2026-10-14，0.6）

`build_site.py` 的 `unit_coverage` 对已登记院系统计公开邮箱、明确研究方向、简介、导师资格的已知/待补数，以及来源抓取日范围和未知日期人数。明确方向只按 `research_direction_raw` 统计，不从简介或facet推断；有值计数不代表信息完整或人工核验。`admissions-data.js` 携带这些公开统计，`admissions.js` 按学校/院系显示信息卡并传递发现页范围。源抓取日与官网内容更新时间分开，未选范围先引导缩小范围。390px卡片用两列展示，名单部分采集的 `roster_pending` 即使已有记录也持续显示。

新接入东南自动化、华中科大网安、武大网安采用 `explicit_supervisor_only`，关闭共享爬虫从简介全文兜底导师资格；专用钩子只接受名单/本人身份区的明确导师资格，排除历史任职、师从及他人句。旧配置维持兼容行为，不能把全库资格字段统计称为已经全部完成严格核验。

`sites/seu_auto.py` 复用官方公开teacherHome接口，核对分页数量、姓名+URL集合和学术身份。本次仅登记 `reported=114/returned=100/pages=2` 的已核验差异，85条明示学术身份记录入库；15条行政或身份未明不入本试点，另外14条数量差异保持未知。任何其他未核验数量差异都失败保留旧库，数量差异及空壳详情继续写issues，不标为已解决。

`scripts/fill_related_fields.py` 独立试点仅处理清华/上交自动化每院系最多20条空字段。官方页面姓名匹配后提取明确研究栏目，dry-run记录原文定位及前后哈希，实写前核对记录未变化；旧值、人工来源和其余字段保留。字段来源与变化JSONL逐条留痕，未取得邮箱不猜测补齐。

0.6数据与产品来源边界、后续需求优先级见 `PRODUCT_ARCHITECTURE_2026-10-14.md`；验证及未闭合缺口见 `DELIVERY_PARALLEL_V0.6_2026-10-14.md`。

## 7. 关键设计决策

| 决策 | 理由 |
| ---- | ---- |
| 名单驱动、渐进富化 | roster 先入库即可用；富化失败不阻塞名单 |
| 一人一 YAML 文件（不用单大文件） | 千级规模下 diff/手改/合并都可控；字段级 provenance 有处安放 |
| 静态站零构建、生成物进 git | 双击即开、可 GitHub Pages 托管、无运行时依赖 |
| 数据进 git、缓存不进 | 数据可审计可回滚；缓存只服务"重跑零请求" |
| issues/changes 双留痕 | 静默丢数据是头号反判据（REQUIREMENTS §1） |
| 只记录官网明确提供的字段 | 未采到或未成功解析保持未知并记录缺口，不推断信息不存在，绝不猜测填充 |

# 架构文档（ARCHITECTURE）

> 系统组成、数据流、数据模型、抓取框架、站点范式与设计不变量。
> 配套：`REQUIREMENTS.md`（需求与决策）、`HANDOVER.md`（开发手册：现状/踩坑/操作）。代码级踩坑细节都在 HANDOVER §10。

---

## 1. 总览

系统是一个**爬取管线 + 静态站点生成器**，没有运行时服务：

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

## 7. 关键设计决策

| 决策 | 理由 |
| ---- | ---- |
| 名单驱动、渐进富化 | roster 先入库即可用；富化失败不阻塞名单 |
| 一人一 YAML 文件（不用单大文件） | 千级规模下 diff/手改/合并都可控；字段级 provenance 有处安放 |
| 静态站零构建、生成物进 git | 双击即开、可 GitHub Pages 托管、无运行时依赖 |
| 数据进 git、缓存不进 | 数据可审计可回滚；缓存只服务"重跑零请求" |
| issues/changes 双留痕 | 静默丢数据是头号反判据（REQUIREMENTS §1） |
| 官网没写的就是没有 | 值留空显示"官网未提供"，绝不推测填充 |

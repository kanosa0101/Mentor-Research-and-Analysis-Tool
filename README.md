# 导师调研工具

把国内目标院校 CS 相关院系官网的师资信息，抓成一张**全量、可浏览、可筛选、逐字段可溯源**的导师表，服务于 2027 年研究生申请的套磁场景：汇聚（全量名单）→ 筛选（方向/职称/博导）→ 溯源（每个字段点回官网原文）。

需求与决策记录见 `REQUIREMENTS.md`（v0.6）；`ARCHITECTURE.md` 是架构文档（组成/数据流/数据模型/站点范式）；**现状、踩坑记录、下一步的权威文档是 `HANDOVER.md`**。

## 当前规模

**36 校 42 院系 5649 名导师**，逐字段 provenance（出处/抓取日期），方向 facet 13 类可筛选。全库覆盖率：邮箱 80%、职称 74%、简介 62%、博导硕导 53%。各院系人数与字段覆盖率见 `HANDOVER.md` §3，或本地打开站点直接看。

数据获取原则：官网没写的就是没有（显示"官网未提供"），绝不推测填充；解析失败/名单消失一律 issues 留痕，不静默丢数据；`origin: manual` 的人工修改永不被爬虫覆盖。

## 常用命令

```powershell
python scripts\crawl.py --school <s> --dept <d>              # 抓取（缓存优先，重跑零新请求）
python scripts\crawl.py --school <s> --dept <d> --refresh    # 强制回源（检测官网变化）
python scripts\build_site.py                                 # 重建静态站
python scripts\serve.py                                      # 本地服务：静态站 + 套磁跟进写回
python -m http.server 8000 --directory site                  # 纯静态预览（跟进只读）

python scripts\audit.py        # 各院系字段覆盖率审计
python scripts\preflight.py    # 提交前体检（schema/邮箱/站点一致性/issues）
python scripts\tag_facets.py   # 重算方向 facet（改规则后）
```

## 套磁跟进（看板）

`python scripts\serve.py` 后打开 `http://127.0.0.1:8000/board.html`：5 列看板（意向→已发信→已回复→推进中→归档），拖拽换列自动保存，搜索姓名可直接加人，卡片邮箱一键复制；列表页有跟进列（⭐ 标意向），详情页有跟进卡片（状态/备注/历史）；列表页勾选 2–5 位导师可进入 [对比页](http://127.0.0.1:8000/compare.html) 并排比较（逐字段带官网出处）。数据存 `data/outreach.yaml`（gitignore，仅本地，不进公开仓库）；直接双击打开 HTML 为只读模式。

## 更新机制

- `--refresh` 重跑即更新：字段级比对，变化写入 `data/changes/<school>-<dept>.jsonl`（只追加，可审计）
- 官网名单里消失的人记 `data/issues/`（不静默删除），恢复出现自动销账
- 每条 provenance 带抓取日期；手改字段标 `origin: manual` 受保护

## 拓展新院系 / 学校

1. 配置 `sites/<school>/<dept>.yaml`（入口 URL / person_href / 钩子名）
2. 通用钩子不够时写 `sites/<school>/<hook>.py`（`iter_roster` + `parse_detail`；已有 wp/simple_list/tsites 等样板可抄）
3. `crawl.py` → `build_site.py`

注意：先 websearch 核实官方域名（踩过的坑见 HANDOVER §10），再 dump 原始 HTML 确认数据位置。

## 目录

```
crawler/   fetch(缓存+限速) model(pydantic) store(YAML+issues+changes) title_util 邮箱校验
sites/     <school>/<dept>.yaml 配置 + <hook>.py 解析钩子
data/      professors/<school>/<dept>/<slug>.yaml · issues/ · changes/ · schools.yaml
cache/     http/ 原始响应缓存（不进 git）
site/      生成的静态网页（进 git）
scripts/   crawl · build_site · audit · preflight · tag_facets 等
```

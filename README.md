# 导师调研工具

把国内目标院校 CS 相关院系官网的师资信息，抓成一张**全量、可浏览、可筛选、逐字段可溯源**的导师表，服务于 2027 年研究生申请的套磁场景：汇聚（全量名单）→ 筛选（方向/职称/博导）→ 溯源（每个字段点回官网原文）。

需求与决策记录见 `REQUIREMENTS.md`（v0.6）；`ARCHITECTURE.md` 是架构文档（组成/数据流/数据模型/站点范式）；**现状、踩坑记录、下一步的权威文档是 `HANDOVER.md`**。

## 2026-10-13 维护与工作流更新

- 名单/辅助 API/浏览器降级继承 `--refresh`；缓存解析日期与来源抓取日期分开。页面不再用“全库核对至”表示单条最新日期。
- 列表支持方向与简介全文搜索、方向未标注筛选、意向短名单和私人标签筛选。基础载荷共享，简介搜索按需加载，仍支持 `file://`。
- 详情可填写下一步、计划日期与私人标签；看板显示到期事项，支持跟进 JSON 备份及恢复。恢复前校验并自动保存旧文件到 `data/backups/`，备份不包含学生画像、SOP 或信件，其他材料需另行备份。
- 官方招生通知试验：清华/北大/上交三个当前栏目页，37 条候选；通知年份、入学年份与截止日期分开，待核验项明确显示未知。
- AI 自动公开层目前只接受原文摘录；真实 API 质量未验收。mock 只写 `cache/ai/mock/`，`--dry` 不调用 API、不创建缓存、不落库。

安装：`python -m pip install -r requirements.txt`；浏览器检查另运行 `python -m playwright install chromium`。图片邮箱 OCR 为可选依赖：`python -m pip install -r requirements-ocr.txt`。当前环境已验证 Python 3.14；其他环境应运行下列检查再使用。

```powershell
python -m unittest discover -s tests -v
python scripts\preflight.py           # 有问题返回非零退出码
python scripts\ui_check.py            # 自动启动临时服务，真实跟进文件不受影响
python scripts\monitor_notices.py     # 通知栏目缓存优先
python scripts\monitor_notices.py --refresh
python scripts\build_site.py
```

部署或复制静态站时，必须同时包含 `data.js`、`search.js` 和 `compare-data.js`。服务默认只绑定本机并拒绝跨站私人写入。详见 `IMPLEMENTATION_PLAN.md` 和本轮交付记录 `DELIVERY_2026-10-13.md`。

## 2026-10-14 联系闭环 0.2

运行 `python scripts\serve.py` 后打开 `http://127.0.0.1:8000/desk.html`。新版“我的申请”分为今日待办、我的导师、联系准备；原 `applications.html` 保留为项目与材料管理，导师详情的“准备联系 / 我的申请”携带当前导师上下文。

1. 从导师详情进入，先建立或选择申请项目。同一项目中的不同导师、同一导师的不同年度分别推进；目标可以填写选择理由和优先级。
2. 保存联系依据、邮箱、主题、正文和所选材料。草稿可以不完整；导出前须补齐邮箱、主题、正文、联系依据并替换占位内容。
3. 导出含附件的 `.eml`，自行在邮件客户端核对、选择发件账户并发送。保存和导出均不计为发送；客户端兼容性需实际检查。
4. 勾选“我已在外部邮件客户端实际发送此版本”并确认日期，才生成发送记录并进入等待回复。文本、邮箱和附件 SHA256 快照固定；已发草稿锁定，再次联系请新建草稿。
5. 记录回复、后续阶段和可选任务，在一次保存中完成；今日待办可继续目标或完成事项。未保存的草稿、回复/下一步在切换目标、加入目标或离开页面时提示，避免串写。

草稿附件只能来自已登记材料，单封总量最多 20 MB。保存草稿固定内容指纹，导出和实际发送确认复查；文件变化需重新选择保存，已选缺失附件可以取消。发送历史只存内容指纹与元数据，不复制附件原文件，因此原文件及历史版本仍需自行保留和备份。

私人工作流 schema 升级为 v2；旧 v1 记录在内存兼容读取，GET 不修改文件，写入时才升级；恢复支持 v1/v2。旧 `outreach.yaml` 不自动修改，“我的申请”使用项目内目标进度，旧套磁看板仍为历史独立记录。EML 私人导出拒绝跨站请求，不进行自动发信或邮箱同步。

验证：`python scripts\contact_ui_check.py`。计划见 `CONTACT_RELEASE_PLAN_2026-10-14.md`，交付见 `DELIVERY_CONTACT_V0.2_2026-10-14.md`。这是手工联系闭环版本；真实招生事实、作者论文核验及个性化推荐仍属后续范围。

## 2026-10-14 申请工作台

运行 `python scripts\serve.py`，打开 `http://127.0.0.1:8000/applications.html`，也可从导师详情页“申请与材料”进入该导师视图。

- 创建申请项目：填写学校、院系、申请类型和入学年度（可未知），关联一个或多个导师；项目状态与套磁看板状态分开。
- 整理材料：登记文件绝对路径，或扫描专门的材料目录（每次最多 1000 个文件）；人工选择项目和导师关联。仅保存路径、大小、修改时间与缺失标记，不上传或修改文件。重复扫描保留分类和关联，缺失后重新出现会解除标记；改名或移动的文件需要重新登记关联。
- 记录沟通：追加草稿、已发送、收到回复、备注/更正事件，可附关联材料。保留旧历史，不自动发送邮件，也不自动改变套磁状态。
- 设置多个提醒：关联项目或导师，分别完成、重新打开或修改日期；工作台显示到期事项。目前不提供后台弹窗或外部通知。
- 私人数据保存在 `data/workflow.yaml`（已忽略 Git），首次写入才创建。原 `outreach.yaml` 不自动迁移或覆盖。可用 `--workflow <路径>` 指定独立文件；测试同时使用临时 `--outreach` 和工作流文件。
- 工作台有独立备份/恢复：包含四类记录及关联，不含原材料文件、学生画像、SOP 和旧套磁文件。恢复前校验并保留旧索引原始副本到 `data/backups/`；即使当前索引损坏，也能从恢复入口导入有效备份。完整索引容量限 16 MB，单次普通写入 2 MB，恢复请求 32 MB；长材料正文宜保留在文件中。

验证：`python scripts\application_ui_check.py` 使用临时文件验收，不读写真实私人记录。实施依据见 `OPEN_SOURCE_IMPLEMENTATION_REVIEW_2026-10-14.md`，结果见 `DELIVERY_2026-10-14.md`。

## 2026-10-14 条件找导师 0.3

本地服务打开 `http://127.0.0.1:8000/discovery.html`：选择申请年度、学位、渠道、院校和研究关键词，给研究方向、导师资格、邮箱、年度机会、个人资格分别设置必须/偏好/不限制。候选显示逐项依据与待核实状态；关键词是文字检索，排序不是录取概率。

年度机会与个人资格可按官方原文人工核验，绑定导师+年度+学位+渠道，超过30天按待核实处理。私人条件保存在忽略Git的 `data/discovery.yaml`，首次保存才创建，备份恢复与工作流分开。进入联系和项目管理保留申请目标。八类页面已统一导航与视觉基线。

产品分析见 `DISCOVERY_PRODUCT_REVIEW_2026-10-14.md`，验证结果见 `DELIVERY_DISCOVERY_V0.3_2026-10-14.md`。运行 `node tests/discovery_rules.cjs`、`python scripts/discovery_ui_check.py` 验证。

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

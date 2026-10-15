# 产品层计划（阶段三）

2026-10-15 当前项目近期行动0.12以 `PROJECT_RECENT_ACTIONS_PLAN_2026-10-15.md` 和 `DELIVERY_PROJECT_RECENT_ACTIONS_V0.12_2026-10-15.md` 为准：完成0.11暂缓的项目日期与提醒摘要，优先本项目最早未完成提醒及最近尚未过去的安排；官方日期、个人计划和历史分清，时间精度、来源与保存顺序不改。复用原项目入口和未保存保护，保持后端/schema与公开/私人数据不变；只定向升级workflow.js。五组相关UI和独立日期规则检查通过，不重复无关后端/全站测试。root负责产品验收，实现、独立复核与集成由子任务并行。只本地提交，不推送。

2026-10-15 历史项目行动入口0.11以 `PROJECT_ACTIONS_RELEASE_PLAN_2026-10-15.md` 和 `DELIVERY_PROJECT_ACTIONS_V0.11_2026-10-15.md` 为准：补齐项目材料与提醒就地操作，修复提醒管理借用旧目标上下文。沿用现有数据模型，不追加完成度/资格推断。只对变更脚本定向升版，真实私人记录、公开数据与来源不变；日期行动排序本轮暂缓。root负责产品验收，实现与测试由子任务并行完成。只本地提交，不推送。

2026-10-15 历史导师信息与申请目标0.10以 `PROJECT_TARGET_RELEASE_PLAN_2026-10-15.md` 和 `DELIVERY_PROJECT_TARGET_V0.10_2026-10-15.md` 为准：卡片按身份/研究原文/来源排序，BIT CS补齐135条历史研究原文，申请目标及官方时间/个人计划按项目保存，材料要求与关联文件并列。workflow v3兼容旧记录而不根据自由文本推断范围；真实私人数据无自动迁移。原11份sources、cache及私人文件排除提交，只本地提交，不推送。

2026-10-15 历史用户任务连续性0.9以 `USER_FLOW_RELEASE_PLAN_2026-10-15.md` 和 `DELIVERY_USER_FLOW_V0.9_2026-10-15.md` 为准：独立姓名查找、单人候选可操作、跨页公开范围隔离、扫描材料发现与显式关联、邮件缺项和回复后下一步。root已试用真实姓名搜索并检查手机材料结果/待安排前置；最终14组UI及缓存升级通过。公开库、后端与私人schema不变，项目自由文本不推断招生范围。仅本地提交，不推送。

2026-10-15 历史用户体验与基础流程0.8以 `UX_RELEASE_PLAN_2026-10-15.md` 和 `DELIVERY_UX_V0.8_2026-10-15.md` 为准：沿用公开静态库与本地私人工作流，优化四主导航、发现信息层级、政策/通知上下文、联系四面板及提醒/未保存流程；不改数据、后端或私人schema。root依据桌面/手机实际截图验收，实现与独立复核按模块执行；本轮只本地提交，不推送。

2026-10-14 当前推进以 `PRODUCT_ARCHITECTURE_2026-10-14.md` 与 `CHECKLIST_RELEASE_PLAN_2026-10-14.md` 为准，0.6基线为b70503ffe，0.7已交付并本地提交（见git log）；交付证据见 `DELIVERY_CHECKLIST_V0.7_2026-10-14.md`。root负责用户判断、信息来源、架构及验收，采集/补齐/实现/测试交由subagent并行。申请前清单解决学校—院系—专业/项目的范围与证据导航；`special`涵盖不同正式专项项目，不能都称为工程硕博。缺少个人条件或对应原文保持未知，暂不增加自动资格评分或真实发信。

下文阶段三、旧规模、旧推送/预检规则为历史设计。当前版本只作本地提交；预检发现的真实采集缺口按事实保留，不修改问题状态制造通过。最新功能、数据和验收结论以各版本交付记录及HANDOVER顶部为准。

下轮优先补当前候选的明确研究方向、本人公开联系信息，以及目标项目的准入、材料和时间依据，不按新增人数追量。先设计包含项目维度的私人核验key及来源适用范围，再开放专项／专业目标的核验保存；当前未知与禁用保存保护继续保留。学校、院系、专业规则并列，来源发布时间／获取日期／核对日期与覆盖分母继续明示，不将“新”或“已有名单”当作完整覆盖。

2026-10-13 增量：维护修复、研究材料搜索/未知方向、私人标签/下一步/日期、跟进备份恢复和三院系通知试验已实现。AI 自动公开层改为可逐字回溯的原文摘录（prompt v2-extractive）；真实模型归纳、个性化匹配及信件未验收。当前记录见 DELIVERY_2026-10-13.md，不把历史计划预测当作完成情况。

状态：**实施中**（2026-09-06 用户"确认开始"；P3.1 ✅、P3.2 ✅ 已落地，P3.3 骨架已建待用户素材，P3.4/P3.5 等依赖）
前置：数据层收官——36 校 42 院系 5649 人，邮箱 80% / 职称 74% / 博导硕导 53%，preflight 绿。
本文是 HANDOVER §9 阶段三的展开，沿用 REQUIREMENTS v0.6 §8 延后项的既有设计，不推翻已决事项。

## 0. 总原则（四条，全程有效）

1. **零构建不破**：仍是 Jinja2 + 原生 JS 静态站；唯一新增运行时是 `scripts/serve.py`（Python 标准库 http.server，不引 Flask/FastAPI——REQUIREMENTS §8.5 已决）
2. **隐私分界（仓库是公开的，已实测 200）**：官网抓取数据可公开；个人工作流数据（跟进记录/信件/学生画像/SOP/AI 匹配点）**一律不进 git、不进静态站**，见 §6 决策 1
3. **铁律沿用**：表头表体同一 HEADERS 数组；UI 改动必过 ui_check.py（Playwright console+DOM）；preflight 先绿再提交；文档同步、每阶段完成即推送
4. **"不推测填充"延伸到 AI**：AI 归纳必带 evidence，无证据断言不落库（REQUIREMENTS §8.2 硬约束）

## 1. P3.1 状态写回 + 套磁看板（✅ 2026-09-06 完成）

**数据模型**：新建 `data/outreach.yaml`（单文件，**不放进 professor YAML**）

- 键 = page id（`school-dept-slug`，school/dept 不含连字符，按前两段切回）；值 = `{status, notes, updated_at, history:[{date, action, note}]}`
- 不进 Professor 模型的理由：crawl 整文件重写 YAML，不在 pydantic 模型里的键会蒸发（§7.53 教训的镜像）；且跟进数据必须与可公开的抓取数据隔离
- 状态集（看板 5 列）：`interested 意向 → emailed 已发信 → replied 已回复 → meeting 推进中 → archived 归档`

**写回服务** `scripts/serve.py`（stdlib ThreadingHTTPServer，只绑 127.0.0.1）：
`GET /*` 静态托管 site/（顺带替代 http.server）；`GET /api/health` 探测可写；`GET /api/outreach` 全量读；`PATCH /api/outreach/<page-id>` 改状态/备注，临时文件+`os.replace` 原子写，history 追加。约 150 行，无新依赖。

**UI 三个接触面**：

- 新页 `site/board.html`：5 列看板，HTML5 拖拽换列即 PATCH；卡片=姓名/学校·院系/职称/导师资格/方向 chip/**邮箱一键复制**；学校筛选+搜索；列头计数
- 列表页：COLS+HEADERS 各加 `跟进` 列（铁律同数组）；行内 ⭐ 一键标意向（serve 模式可用）
- 详情页：跟进卡片（状态下拉+备注+历史时间线）
- **加载方案（实现定稿，纯 API）**：outreach 数据**不进任何生成文件**（快照方案因隐私废弃）；页面加载探测 `/api/health`，通则 fetch `/api/outreach` 动态加载——改状态无需重建站点；file:// 直开由协议门控降级只读并提示 `python scripts\serve.py`

**preflight 扩展**：outreach.yaml schema 校验（status 枚举、page id 存在于导师库、history 结构）。

改动面：新增 serve.py / board.html.j2 / outreach.yaml 骨架；改 index/detail 模板、build_site.py、preflight.py。

**验收**：拖拽改状态 YAML 落盘且列表/看板即时反映；file:// 只读不报错；ui_check 全绿；preflight 绿。

## 2. P3.2 对比页（✅ 2026-09-06 完成）

- 列表页行首勾选 2–5 人 → 浮动"对比"按钮 → `compare.html`（选人名单存 localStorage）
- 新模板 compare.html.j2 复用同一 payload；行=字段（学校/院系/职称/导师资格/方向/邮箱/电话/研究所/主页/简介摘录），列=导师；缺字段"官网未提供"；有 provenance 的字段点回官网原文；纯静态无服务依赖

**验收**：任意 3 人对比逐字段与详情页一致、出处可点。

## 3. P3.3 学生画像 + SOP 成文（骨架已建，素材依赖用户）

- `data/student.yaml` 按 REQUIREMENTS §8.3 schema：基本信息/院校背景/成绩排名/科研经历（每条要有能讲出细节的内容，不只标题）/技能栈/意向方向/时间线约束——我搭带注释骨架，**素材需用户提供**（简历+项目细节口述即可）
- SOP 独立成文（先于信件生成器）：`data/student_sop.md`，从画像起草→用户改定
- 两份文件 gitignore

**验收**：schema 定稿 + SOP 用户确认可用。

## 4. P3.4 AI 归纳层（✅ 骨架 2026-09-06 完成；实跑等 LLM API key）

- `scripts/ai_enrich.py --school --dept [--refresh]`：缓存优先，`cache/ai/<sha1(输入指纹+prompt_version+model)>.json`（cache/ 已整体 gitignore），改 prompt 必升 prompt_version
- 输入只限库内材料（bio_raw / research_direction_raw / facets / title / institutes）
- 产出分两层：
  - **导师侧**（可公开）：research_summary 方向归纳、highlights 亮点 → 进 `Professor.ai`（pydantic 模型加 AiBlock，origin=ai + model + prompt_version，逐条 evidence），详情页"AI 归纳"区块视觉区分、evidence 可点
  - **学生相关**（隐私）：match_points 匹配点、questions_to_ask 可问问题 → 只落 cache/ai/，**不进 Professor、不进静态站**，供信件生成与 serve 模式使用
- 每条断言写库时校验 evidence，无证据丢弃并记日志
- 需要：LLM 提供商与 API key（OpenAI 兼容接口即可，环境变量注入，key 不进 git）

**验收**：抽 10 人逐条核对 evidence 真实性；缓存重跑零新请求；prompt 变更走版本号。

## 5. P3.5 信件草稿（最后，依赖 SOP+AI）

- `scripts/gen_letter.py --page <id>`：画像+SOP+该导师 AI 材料 → 五段骨架（主题行/一句话自我定位/为什么是他——引具体方向或论文细节/你能贡献什么/收尾+明确下一步）
- **"为什么是他"每句必须挂 evidence**，构建时校验；模板废话 lint：把人名/论文名换掉仍成立的句子标黄（REQUIREMENTS §8.4 自检）
- 产出 `data/letters/<page-id>/<date>.md`（gitignore）；用户确认发送后一键记录：outreach status→emailed + history 追加信件路径，自动进看板

**验收**：抽 3 封人工评审"换人名不成立"；发信记录自动进看板。

## 6. 决策点

1. **隐私边界（P3.1 开工前定）**：仓库公开（已实测）→ 建议 `data/outreach.yaml`、`data/student*.yaml`、`data/student_sop.md`、`data/letters/` 加入 .gitignore；备份走本地/私有渠道。若你把仓库转私有，可全部进 git
2. **看板 5 列状态集**是否合意（可增删，如"无回复跟进"）
3. **LLM 提供商与 API key**（P3.4 开工前给即可）
4. **对比页字段集**默认上述 10 行，可加减

## 7. 顺序与依赖

```
P3.1 看板+写回 ──► P3.2 对比页 ──► P3.3 画像+SOP(等素材) ──► P3.4 AI 归纳(等 key) ──► P3.5 信件
```

P3.1/P3.2 无外部依赖可立即开工；P3.3 起需要用户输入。每阶段：代码+文档同步 → preflight/audit/ui_check 绿 → commit+push。

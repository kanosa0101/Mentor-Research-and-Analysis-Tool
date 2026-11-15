# 当前系统地图与体验审视边界

盘点时间：2026-11-15。范围：只读检查当前源码、文档、版本快照及已有验证记录，不修改产品、数据或部署，不重新调用 AI/采集/发布。v1.9 已有工程验收记录；用户明确否定其整体体验，不能据此宣称产品体验通过。

## 1. 结论先行

当前产品不是一张“导师列表”，而是四套数据与操作模式通过多页面组合起来的申请助手：公开资料库、当前浏览器的关注记录、本机正式申请工作流、维护者核验系统。安全边界和证据约束较丰富，用户的任务入口、名词和进度理解仍要横跨这些边界。

v1.9 的主要变化是 CSS 统一、筛选位置变化、内容折叠和卡片布局。并没有合并“关注目标/申请项目/联系目标/核对记录”等模型，也没有改变公网查看→下载 Python 本机版→导入浏览器备份→建正式项目的路径。技术能力存在，不等于学生能发现、理解或愿意完成它。

当前优先文档工作应是：选定主要用户与高频场景，定义他们在每一步要做的决定、最少需要的事实和成功退出方式，再决定入口/页面责任与信息层级。不要先按现有表、字段或测试用例反推产品需求。

## 2. 技术形态与代码边界

- Python 抓取/校验/文件持久化，Jinja2 生成静态多页面，浏览器原生 JavaScript，无 SPA 路由、无前端组件框架。入口为 `scripts/build_site.py::main/template_environment/write_html`。
- 每页模板大多仍含局部 `<style>`；`site/ui.css` 在模板局部样式之后加载。统一 tokens 和 body 类降低覆盖冲突，但重复的局部字号、布局、控件样式仍存在，未形成可复用组件契约。
- 找导师特殊处理：`build_discovery_entry/render_discovery_page` 把启动所需脚本/样式组合进首屏，常规浏览服务端分页；完整资料只在具体流程需要时加载。
- 数据主存储为 YAML/JSON 文件，私人写入有锁与原子替换。公开查询索引、浏览器状态、静态生成页面是不同层；不能只更新其中一个即视为整站完成。
- 三个服务入口：`scripts/serve_public.py::create_server`（公开服务）、`scripts/serve.py::create_server`（本机应用）、`scripts/serve_review.py::make_server`（本机维护台）。本机应用默认 8000，维护台固定 loopback 18769，生产 HTTPS 入口 8443。

## 3. 页面职责、入口和关键依赖

主导航由 `site/templates/_nav.html.j2` 定义，五项为申请导航、找导师、保研机会、学校与要求、我的申请。更多工具中仍有招生通知、全量导师目录、导师对比、项目与材料、旧套磁看板、版本说明。

| 页面 | 实际职责与主要入口 | 脚本/数据/API | 需要在需求文档澄清的责任 |
| --- | --- | --- | --- |
| `start.html` | 选择申请路径、学校、兴趣；浏览器收藏/待办；本机模式显示下一步、公共资料更新和转项目 | `start.js`、`browser-library-core.js`、`browser-library.js`、`plan-transfer.js`、`public-data.js`、学校目录；本机 workflow 和 public-data API | 同时承担首次引导、日常主页、收藏管理、备份、升级工具。首访与回访是否应该看到同一结构？ |
| `discovery.html` | 姓名/方向/学校/学位/相关院系筛选，首批 20 位；查看资料、准备联系、对比；高级区有年份、渠道和必须/偏好/不限制规则、私有核验 | `discovery.js`、`discovery-core.js`、生成的 `discovery-entry.js`、`school-catalog.js`；公共 mentor-candidates，特殊范围回退本机全量判断 | 普通探索和正式项目核验混用同一页；“目标学位”默认排序偏好，并非硬筛选。学生是否需要理解匹配规则引擎？ |
| `p/<mentor>.html` | 研究方向、导师资格、公开邮箱、官方资料、官网简介；对比、准备联系；旧套磁记录和来源核验记录折叠 | `detail.html.j2` 内联上下文/对比/旧 outreach 脚本，浏览器收藏脚本；`/api/outreach`（仅本机） | 简介原文可能仍很长；研究契合度、当前接收意向与资料完整度是不同事实。首屏应帮助什么判断？ |
| `compare.html` | 按已选 ID 比较 1–5 位导师，继续找导师、准备联系 | 模板内联逻辑、`public-catalog` 按 ID 读取、浏览器 `compare_sel` | 是研究方向比较还是申请可行性比较？列对比与手机使用目标需要单独验证。 |
| `admissions.html` | 选校/院系/年度/学位/渠道；完整目标后生成条件、材料、时间三项；政策卡、官方入口、覆盖与目录 | `admissions.js::render/renderChecklist/checklistItem/revealTarget`、`admissions-core.js`、`material-actions.js`、`admissions-data.js` | 既是学校概览又是目标核对工具。未完成目标时是否仍能迅速知道该去哪报名、看哪份政策？摘要截断不等于业务摘要。 |
| `opportunities.html` | 活动目录，按学校/方向/类型/毕业届别/报名状态筛选，条件/材料/研究方向/联系方式，加入申请、收藏，浏览器通知和维护状态 | `opportunities.js::renderOpportunities`、`opportunities-core.js`、`opportunity-push.js`、`opportunity-sw.js`；`/api/opportunities`、push/updates、仅本机保存项目 | 研究实习、持续招募、冬夏令营、正式预推免分别解决什么需求？监测覆盖与异常信息属于用户决策还是维护解释？ |
| `notices.html` | 官方通知候选，标题检索、学校院系、届别/入学年/活动年/渠道/阶段线索；回查来源 | `notices.js`、`notices-core.js`、模板生成的通知数据 | 与“保研机会”“学校要求”的区别需要一句话说清，通知发现不等于可报名机会或已核验政策。 |
| `desk.html` | “我的申请”：联系目标、草稿、导出 EML、登记已发/回复、下一步/提醒，连接项目材料 | `desk.js::render/renderContext/loadDraft/renderTargetTasks`，`/api/workflow`、`/drafts/<id>/eml`、`/drafts/<id>/confirm`、`/targets/<id>/reply` | 名称像项目总览，重心却在联系工作台；与 applications 的职责分界对用户不显然。 |
| `applications.html` | 正式项目完整目标编辑、阶段状态、材料扫描/关联、材料准备记录、多提醒、备份恢复 | `workflow.js::goalTitle/renderGoalEditor/render`、`material-actions.js`，workflow/projects/material-tasks/scan/reminders 等 | 项目、联系人、材料、准备任务的主从关系应按实际申请路径重写；不应要求学生先掌握内部模型。 |
| `index.html` | 全量导师表，较细筛选与目录检索，加入对比等旧入口 | 模板内联逻辑、`data.js`，搜索载荷 `search.js` | 与 discovery 重复。应明确它是专家工具/数据核对工具，还是普通用户必经页面。 |
| `board.html` | 旧套磁阶段看板、跟进记录 | 模板内联逻辑、`/api/outreach` | 与新 workflow 不同步，仍在导航可见。需要保留兼容，但是否作为新用户入口是产品问题。 |
| `local.html` | 解释公网/本机边界、下载与启动方式 | 静态模板与下载链接 | 需安装 Python、保持服务运行是明显任务成本。当前是能力边界，不能靠一段提示视为完成无缝衔接。 |
| `coverage.html` / `release.html` | 数据缺口及版本/使用说明 | coverage/source_coverage、release.json 等构建输入 | 应服务“这条信息可靠吗/缺了什么”，不能让维护台账成为普通用户理解页面的前置条件。 |
| `review.html` | 维护者队列、证据与差异、编辑/发布、来源准入、审核提醒 | `review.js`、`review-worker.js`，独立 review API | 不属于申请用户页面；公开服务拒绝该页与脚本，不能作为用户获取信息的依赖步骤。 |

## 4. 数据边界及用户容易混淆的对象

| 边界 | 对象和存储 | 可写入口 | 事实与限制 |
| --- | --- | --- | --- |
| 公共资料 | `data/professors/<school>/<dept>/*.yaml`、`admissions.yaml`、`admissions_checks.json`、`admissions_entries.yaml`、`notices.json`、`opportunities.json`、coverage 文件 | 采集/维护脚本及核验发布 | 来源有日期不等于条件已更新；官方入口可用不等于所需政策已覆盖。 |
| 浏览器个人记录 | 当前 origin 的 localStorage：关注目标、收藏、待办；`compare_sel`；discovery 用 sessionStorage 保存已应用条件/随机种子 | `browser-library-core.js`、`start.js`、各页收藏/对比 | HTTPS/HTTP、端口或域名变化即另一份记录；无跨设备账号同步。待办日期不触发后台个人提醒。 |
| 本机正式申请 | `data/workflow.yaml` 默认路径、`data/discovery.yaml`；旧 `data/outreach.yaml`；画像/材料原件另有保存责任 | `scripts/serve.py` 本机 workflow/discovery/outreach API | 正式项目目标、材料索引、草稿、沟通、提醒；公共更新不覆盖私人事实；工作台备份不含所有原件和独立画像/SOP。 |
| 维护运行态 | `cache/opportunity_review.json`、`cache/opportunities_live.json`、`cache/source-discovery.json`、审核告警/AI额度、维护订阅 | 独立审核 API、轮转脚本 | 不公开私人备注/密钥；队列可含未发布线索，不应以队列规模证明机会覆盖。 |
| 公共订阅 | `var/push/alerts.sqlite` 等推送状态，浏览器 push endpoint 和筛选 | 自愿 subscribe/unsubscribe/test | 是公共机会变化提醒，不是个人项目提醒；服务接受不保证系统已弹出。 |

默认 workflow 路径由 `serve.py::Handler.__init__` 从 outreach 同目录推导 `workflow.yaml`，可通过命令行覆盖；不能读 `workflow_util.py` 的 v1 `empty_workflow` 就认为运行态只有 v1，实际 `_workflow_request` 会通过 `material_tasks.upgrade`、contact/project 等模型处理兼容结构。最终 schema 与读写行为必须按服务实际调用链理解。

重点名词负担：关注目标≠正式项目；联系目标≠导师公共记录；旧套磁记录≠新沟通历史；人工核对记录≠公共政策核验；活动年≠毕业届别≠入学年；浏览器待办≠本机个人提醒≠公共活动后台推送。它们有合理的数据隔离原因，但不应把全部隔离原理交给普通学生记忆。

## 5. API 地图与跨页上下文

### 公开只读与自愿订阅

`scripts/serve_public.py::Handler.do_GET`：

- `/api/mentor-candidates` → `crawler/public_discovery.py::candidates`，全索引筛选排序后分页；目录 revision 防翻页混版本。
- `/api/mentors`、`/api/mentor-search` → `crawler/public_catalog.py::selected/search`，按 ID 或词检索，不上传私人项目。
- `/api/opportunities` → 活动目录叠加监测状态；`/api/updates` → 公开变化记录；`/api/push/config` → 订阅能力配置。
- `/api/public-data`、`/api/public-data/archive/<sha>` → 公共资料版本与白名单归档。
- `do_POST` 只允许 push subscribe/unsubscribe/test；其余私人/审核 API 不注册。

### 本机正式工作流

`scripts/serve.py::Handler._workflow_request`：GET 工作流/备份/材料任务/EML；POST 或 PATCH 项目、材料、草稿等，专用 scan、material-tasks、material-tasks/<id>/reminders、opportunities、browser-transfer、drafts/<id>/confirm、targets/<id>/reply、restore。统一通过校验、锁、原子写入。

`_discovery_request`：GET 条件/备份/project-reviews，POST 条件/reviews/restore/project-reviews。私人核对需要完整范围与证据，不可借用原项目或通用结论。

`/api/public-data/check/update` 是本机明确触发的更新入口，和生产定时维护不同。

### 维护者核验

`scripts/serve_review.py::Handler`：GET `/api/review`、detail、sources、notifications；POST action、source-action。维护台绑定 loopback，校验 Host/Origin、令牌及队列版本；不与用户工作流 API 共用。

### 上下文实际传递

通过 URL 的 school/dept/year/degree/route/track/program/project 等字段、浏览器存储、当前项目目标快照三种途径。详情页会清掉跨学校/院系传来的专业或专项范围，筛选页保留已应用条件而非所有未提交输入。`discovery.js::saveView/restoreView/publicScope`、`desk.js::savedGoal`、`workflow.js::goalQuery`、详情模板的 `detailScope` 是关键点。

同一目标在不同页面有不同表单/默认值/主键；这带来真实认知与维护成本，即使范围保护测试通过，也不能证明用户知道当前究竟在筛谁、看哪届。

## 6. 公开信息从哪里来、怎样更新

### 导师与政策

1. `sites/<school>/*.yaml` 定义院系来源与解析配置，配套 `sites` 模块解析官方师资名单/个人页；`scripts/crawl.py`、`crawler/fetch.py`、`crawler/store.py` 更新模型与出处。
2. `crawler/model.py::Professor/Provenance` 区分 raw 研究方向、简介、导师资格、邮箱、状态及逐字段来源；`last_fetched`、`last_parsed`、`last_verified` 不同。
3. 政策结构化摘要主文件 `data/admissions.yaml` 包含 scope/条件/八类 fields/events/material_actions/原文定位；`admissions_checks.json` 单独记录来源检查，`admissions_entries.yaml` 是官方入口而非摘要本身。
4. `scripts/maintain_public.py::main/priority_units/rebuild` 轮转导师、政策、通知并构建；`crawler/legacy_refresh.py` 处理旧资料。来源访问成功不会自动把人工摘要变为新政策，轮转不是整库复核。

### 机会发现、辅助核验、发布

1. `sites/opportunities.yaml` 配置官方列表、受支持 JSON API、招募正文 direct_page；`sites/notices.yaml` 是通知栏目配置，二者不是同一份目录。
2. `crawler/opportunity_monitor.py::run_once/_run/source_interval/due` 按到期时间回源；有域间节流、异常空列表/骤减保护、失败退避；更新 `cache/opportunities_live.json`。
3. `crawler/source_discovery.py::run/decide` 从可信入口有限扩展同机构栏目，新栏目先待准入，不自动发布机会。
4. `scripts/review_opportunities.py` 同步队列；`opportunity_extract` 生成保守提取建议；`opportunity_review` 处理 HTML/PDF/DOCX 证据、SHA/定位、保存与发布。PDF/DOCX 有独立版本，不能只验证 HTML。
5. `crawler/automatic_review.py::prepare_new/process/run` 仅受限 HTML 本科冬夏令营/科研招募、完整栏目、明确邮箱申请、唯一窗口、无附件或人工冲突时尝试规则+AI交叉核验+发布时回源；正式招生/届别映射/系统报名/多批次/附件/人工编辑等转人工。`ai_evidence.suggest` 只提供原文匹配摘录，不直接批准事实。
6. `crawler/review_queue.py::evaluate/ordered/refresh_alerts` 给队列排序、持久化等待时钟和 SLA 事件；紧急2h/高12h/普通24h/低72h 是维护目标，不是招生申请保证。
7. `scripts/run_review_pipeline.py::run` 分阶段执行 discovery、automatic、alerts、maintainer_notifications、public_snapshot、metrics。目录变化才重建公开归档；重建失败保留旧 built_catalog_sha，不伪装完成。
8. `crawler/opportunity_util.py` 和前端 `opportunities-core.js` 区分固定日期 open、月份 open_month、长期 rolling、upcoming、review、closed；发现和发布分开，原文/核验过期会降级。

自动化降低重复维护，不覆盖所有招生政策，不补齐所有院系，也不保证新公告即时可报名。用户真正关心的“今天是否有适合我的新项目”仍取决于可信来源覆盖、有效条件提取、人工阻断积压和发布时效。

### 推送、部署与运行包

- `deploy/mentor-monitor.timer` 每15分钟唤醒，实际来源按1/6/24小时等策略决定回源；monitor service 后执行队列 sync。
- `mentor-maintenance.timer` 每小时；`mentor-review-pipeline.timer` 每15分钟（每轮 limit2 等预算）；`mentor-updates.timer` 每15分钟。证书另有 timer。以上是仓库配置，实际启用情况本次不重新连服务器确认。
- `crawler/push_util.py` + `scripts/dispatch_updates.py` + `site/opportunity-sw.js` 负责公共机会更新/截止通知；`crawler/maintenance_push.py` 是独立维护订阅，不读取学生项目。
- AI 密钥从服务端 credentials / `MENTOR_AI_CONFIG_FILE` 读取，默认无配置不调用，公开文本才可发给 AI；本次不读取密钥、不调用接口。
- `scripts/package_release.py::FIXED/PATTERNS/allowed/checked_path` 白名单打包，manifest逐文件校验；`crawler/public_snapshot.py` 生成公共资料包，`crawler/public_update.py` 校验后用本机模板暂存重建并备份替换。公共资料更新不升级代码，也不等于整个目录原子切换。

## 7. 内容现状的证据等级

`docs/DATA_SNAPSHOT.json` 的 metadata 明确 v1.9 仅改 UI 元数据，统计沿用 v1.8 快照，不能当新一轮抓取。本次未重新爬取官方来源，以下仅为已登记快照：

- 39 校、59 配置院系、56 有导师记录、7173 导师；研究方向字段3061、邮箱5668、导师资格3969；6172条 source_date 超过30天。
- 111 政策、183来源/检查、96官方入口、360通知；69政策有310材料动作、42政策无动作。
- 18条机会是所有状态的登记总数，不能写成18条冬令营或18条正在报名。旧版本状态计数也不能代替当前运行时状态。

这些数量同时提示：再漂亮的卡片也无法解决很多导师缺方向、旧来源未复核、申请条件不全的问题；但缺失字段应以任务可继续的方式呈现，不能把一串“未知”当作默认产品内容。

## 8. 已有测试覆盖及不能证明的事情

### 能证明的范围

- 规则/数据不变量：`tests/test_admissions*.py`、admissions/checklist/conditional Node tests；项目/材料/联系/备份模型；机会窗口、附件、来源变动；公开API与数据包白名单；AI人工保护/日预算/SLA/部署边界。
- 浏览器任务回归：`scripts/*_ui_check.py` 含 school multi-select、material-policy return、entry scope、project reviews、contact、workflow、runtime journey 等。主要使用已知稳定样例、临时私有文件或隔离运行包。
- 本轮 `scripts/ui_system_v19_check.py`：14页1440/390，页面不横溢出、body/h1 tokens、部分可见控件字号、一个可见 details 的键盘开闭、第一次 Tab 焦点、页面错误和禁止写请求；新增320/768另有记录。
- `scripts/detail_v19_ui_check.py`：真实BIT详情样本、来源折叠完整性、上下文保持/跨院系清理、对比增删，不写私人数据。
- 已有交付文档报告625 Python、13组Node、28+28视口检查，以及公网分页、hash、包更新保护等；本次只引用历史报告，未重新运行这些测试。

### 主要盲点

1. 无真实学生不看说明完成任务的可用性证据：找不到合适导师、无法理解年份/范围、没发现某入口、在公网误以为已建申请，都可能在自动化全绿时发生。
2. 无明确任务成功标准与基线：例如“在5分钟内找出3位有方向依据、可联系且满足最低范围的导师”，当前测试主要验证控件存在和预定动作能执行。
3. 字号/无溢出不证明视觉美观、重点清楚、阅读负担低；截图多为默认/空私有态，长标题、资料贫乏、错误态、多项目/多材料高密度态覆盖不能由28个页面访问替代。
4. 键盘测试只验证少数折叠与首个焦点，不等于全流程键盘可达；未提供屏幕阅读器、浏览器缩放、触摸目标实测、多浏览器和不同系统字体的覆盖证明。
5. 公网实测首次首屏约5.020/4.231秒（交付报告样本）仍非轻快；39–40KB和20位分页是技术指标，缺少端到端慢网/冷缓存/连续切页体验目标，不能因为减少载荷就关闭性能问题。
6. 范围、资格及日期模型校验只证明不明显借用，不证明源政策条件已完整、及时、对当前学生可判定；官方网页成功回源也不等于结构化摘要完整更新。
7. 通知测试/服务接受不等于不同手机/浏览器关闭后收到；没有自动把个人项目提醒变为公共推送。
8. 备份/更新隔离测试不代表学生会备份、能正确区分三类数据、能在无Python环境顺利安装，也没有证明真实邮件送达或学校收件。

## 9. 文档过时、语义冲突及需校正处

| 文件 | 真实情况 | 后续文档处理建议 |
| --- | --- | --- |
| `docs/UI_GUIDELINES.md` “刷新保留未保存输入” | `desk.js`、`workflow.js` 实际主要用 beforeunload 弹出取消离开；没有私有草稿自动持久化到浏览器。`discovery.js::saveView` 在 apply 后保存已应用筛选，并不保证所有未提交输入刷新后恢复。 | 区分“提示可取消离开”“已保存草稿重载”“未保存编辑自动恢复”，当前规范不能当已实现事实。 |
| `docs/UI_GUIDELINES.md` “所有关键操作可用键盘完成” | 是目标，当前通用验收只抽取一个 summary/首个Tab，不足以证明全部关键任务。 | 保留为验收要求，另列需要人工走通的键盘任务矩阵，不标已满足。 |
| `README.md` / `REQUIREMENTS.md` / `ARCHITECTURE.md` v1.9呈现说明 | 基本已同步到v1.9，写的是“已提供能力”，并非独立用户体验证明。此次用户反馈已否定整体效果。 | 在后续评审文档明确工程交付通过、产品体验未通过；不要沿用“统一/清楚”作为验收结论。 |
| `IMPLEMENTATION_PLAN.md`（根目录通用文件名） | 标题是2026-10-13，含“37条候选”“真实API质量尚未验收”等旧任务状态，与v1.8已存在的真实受限AI流程不属同一时间基线。 | 明确历史归档身份或建立当前计划唯一入口，避免从通用文件名继承旧范围。 |
| 大量根目录 `*_V0.*` 与 `*_2026-10-*` 计划/交付 | 含旧端口、旧覆盖、无后台提醒、试点规模等；有版本日期但路径与当前主文档平级，容易被搜索当现状。 | `docs/HISTORY.md`作为历史索引已存在；当前重规划应只从一个新基线入口链接历史证据。 |
| `RELEASE_ACCEPTANCE.md` / `RELEASE_NOTES.md` | 顶部已明确指向v1.9，后面保留v1.0旧记录；不能称整个文件过时，也不能引用下半部旧数字为现状。 | 读引用时必须带章节版本；旧“无后台推送”与当前公共推送并非产品矛盾，是版本/提醒对象不同。 |
| `docs/AUTOMATIC_REVIEW.md` 标v1.8 | 自动核验能力是v1.8新增并在v1.9沿用，版本旧不自动意味着内容过时；当前链接仍指v1.8交付。 | 写清“自v1.8生效、现版沿用”，具体运行状态另查最新交付/运行证据。 |
| `docs/DATA_SNAPSHOT.json` metadata version1.9、generated_at沿用v1.8 | 文件已明确UI-only元数据；若消费者只看版本会误以为重新全量采集。 | 需求/报告分别列程序版本、统计生成时间、字段来源时间、摘要核验时间；不要合并成“更新时间”。 |
| `REQUIREMENTS.md` 四阶段验收段落 | 持续继承前几版功能验收清单，加入v1.8/v1.9补充，但缺本次体验收尾的场景优先级、用户任务完成尺度与不做事项。 | 新文档先冻结体验问题、目标场景和四阶段交付标准，再执行；避免继续向旧功能清单追加。 |

## 10. 交给主代理的规划输入（不在本次实施）

1. 先确定本轮核心任务：探索导师、找到可行动机会、核对目标申请要求、跟进已选项目，分别写当前路径与期望路径；确认公网用户是否本轮主要对象。
2. 每页只定一个主问题、一个首要动作，列首屏必要事实/补充详情/证据及不可省略限制；明确学校概览与精确申请核对是否同一入口。
3. 建统一对象词典，指出用户需理解的概念与应由系统处理的概念；给跨模式保存、返回、重复建立、未完成目标定义反馈。
4. UI规范从只有字号/颜色扩为少量真实组件及状态示例：导师有/无方向、有/无邮箱；机会开放/需复核；政策完整/不完整；筛选未应用/已应用/无结果；已有私人项目的高密度工作台。
5. 验收改为真实任务走查加现有工程保护：观察能否找到下一步、理解适用范围和时间、回到原筛选、不误判保存或报名；保留已有数据安全与来源校验测试。

本次仅产出地图。没有新增功能、修改资料、触发外部请求/AI或进行部署。

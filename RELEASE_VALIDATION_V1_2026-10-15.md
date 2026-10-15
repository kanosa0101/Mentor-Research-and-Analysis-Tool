# v1.0 本机版现态发布验收

验收日期：2026-10-15。代码起点：`179052b4dddde86af39f57b2c5f003303c0f31eb`（v0.22）。首轮现态验收不重建站点、不修改产品代码；后续发布负责人仅新增版本页与导航入口并构建，未改变业务流程与公开数据，新增页面已纳入后续 release-page 补验。初始验收运行原测试；发现旧公共导航 fixture 与后续项目规则冲突后，经发布负责人明确授权，仅修正 `scripts/public_flow_v13_ui_check.py` 的场景划分，保留全部原业务及隐私断言并补缺失项目断言。验收环境为 Windows 11、Python 3.14.6、Node v24.11.1、Playwright Chromium。

结论：首轮完整 Python 313 项、最终完整 Python 318 项、九组 Node、全部公开 JavaScript 语法及最终九组业务浏览器检查通过，另有实际主站版本页双视口补验通过；预检仍报原七组共 67 项资料问题。旧公共导航脚本初次失败、定位、最小测试修正及重跑均在下文保留，未以产品改动迎合旧断言。本报告不能证明数据已齐或所有未覆盖场景都正确。

## 命令与退出码

所有本轮输出位于 `cache/release_v1/validation/`。`results.json` 保存初次各子命令、退出码、耗时与日志名，包含未改写的旧公共脚本失败；后续只读探针与测试修正重跑记录在 `supplemental-results.json`，不可只读首轮结果或只读调度器退出码。`environment.json` 保存运行环境。主调度命令为 `python cache/release_v1/validation/run_validation.py`。调度器会继续收集失败后的其他验证，**调度器退出 0 不代表全部检查通过**，应读取各子命令结果。

| 检查 | 实际命令模式 | 退出码 | 结果/日志 |
|---|---|---:|---|
| 首轮完整 Python | `python -m pytest -q` | 0 | 313 passed，3 warnings；`pytest.log` |
| 最终完整 Python | `python -m pytest -q` | 0 | 318 passed，3 warnings，99.25s，无 skip；`pytest-final.log`。含新增五项打包合同测试，首轮日志保留 |
| 招生规则 | `node --test tests/admissions_rules.cjs` | 0 | `node-admissions_rules.log` |
| 清单规则 | `node --test tests/checklist_rules.cjs` | 0 | `node-checklist_rules.log` |
| 条件政策 | `node --test tests/conditional_policy_v18.cjs` | 0 | `node-conditional_policy_v18.log` |
| 发现质量 | `node --test tests/discovery_quality_v21.cjs` | 0 | `node-discovery_quality_v21.log` |
| 排序规则 | `node --test tests/discovery_ranking_v14.cjs` | 0 | `node-discovery_ranking_v14.log` |
| 发现规则 | `node --test tests/discovery_rules.cjs` | 0 | `node-discovery_rules.log` |
| 发现范围 | `node --test tests/discovery_scope.cjs` | 0 | `node-discovery_scope.log` |
| 入口范围 | `node --test tests/entry_scope_v17.cjs` | 0 | `node-entry_scope_v17.log` |
| 项目核验 | `node --test tests/project_reviews_v16.cjs` | 0 | `node-project_reviews_v16.log` |
| 公开 JS 语法 | 对 `site/**/*.js` 逐个 `node --check` | 全部 0 | 11 个文件，清单及退出码见 `javascript-syntax.json`，合并日志 `javascript-syntax.log` |
| 完整预检 | `python scripts/preflight.py` | 1 | 原七组资料问题；`preflight.log` |
| 浏览器九组 | 见下表，每组经 `python cache/release_v1/validation/run_legacy.py scripts/<脚本>.py` 执行 | 最终九组 0 | 每组同名 `.log`；公共脚本初次 1 与修正重跑日志分别保存 |

Python 三项警告来自 `pytest_asyncio` 的 `asyncio.get_event_loop_policy` 及 `pypinyin` 的两处 `codecs.open` 弃用提示，不是测试失败。

## 用户流程与浏览器证据

| 脚本名（省略 `.py`） | 退出码 | 本轮覆盖 |
|---|---:|---|
| `discovery_school_v21_ui_check` | 0 | 1440/390：学校搜索、多选/清除、键盘、未保存核验取消保护、URL 兼容、结果稳定、无横向溢出；浏览不创建私人文件 |
| `material_filters_v22_ui_check` | 0 | 1440/390：六阶段、混合人工状态、旧目标/历史、原数组索引保存、dirty 确认/取消、八字段及项目切换、加载/刷新；真实浙江 CS 11 项清单试点，筛选无 POST，临时工作流 SHA 不变 |
| `policy_requirements_v22_ui_check` | 0 | 五真实政策目标×1440/390：山东 081200 与 085404 独立专业规则、清华/浙大博士及清华自动化历史截止；四次显式 prepared 保存、两次未勾条件拒绝；无浏览器错误/外部请求/新增提醒/学校提交 |
| `application_ui_check` | 0 | 项目、材料扫描/关联与缺失文件、通信追加历史、多提醒及完成状态、持久化、备份恢复、损坏索引恢复、390 无溢出、file 模式提示及禁写 |
| `contact_ui_check` | 0 | 导师上下文→项目/材料→草稿→EML 下载→显式人工标记已发→回复/下一步→今日工作台；持久化、手机、备份及损坏索引恢复、file 模式 |
| `contact_v9_ui_check` | 0 | 1440/390：准备条件、未保存/已发草稿、后续事项可见性、项目提醒隔离、招生范围与私人项目隔离 |
| `desk_actions_v11_ui_check` | 0 | 1440/390：同导师多项目提醒、项目/目标范围及跳转参数隔离 |
| `public_flow_v13_ui_check` | 初次 **1**；修正后 **0** | 初次 1440 在旧第 75 行失败；修正后完整 1440/390 跑完缺失项目保护、公共范围、未应用条件、应用条件、比较/详情、政策/通知、跨院系清除、无效年度、隐私与手机布局；最终日志 `public_flow_v13_ui_check-final2.log` |
| `ui_check` | 0 | 真实公开站点列表搜索/方向/学校筛选、意向与看板拖动、浏览器备份恢复、比较页 14 行、手机看板、file 全文检索、通知筛选；console errors NONE |

截图共 50 张，全部位于 `cache/release_v1/validation/ui/<脚本名>/` 下，保留旧脚本的相对目录。`evidence-index.json` 提供逐文件路径和 SHA-256。代表截图：

- 找导师手机：`ui/discovery_school_v21_ui_check/policy_v21/east/ui/after-390-results.png`
- 真实材料手机：`ui/material_filters_v22_ui_check/policy_v22/ui/zju-live/application-pending-390.png`
- 山东专业政策手机：`ui/policy_requirements_v22_ui_check/policy_v22/live_flow/sdu-cs-081200-2027-exam-v22-390-public.png`
- 联系/回复手机：`ui/contact_ui_check/ux_v8/workflow/contact/prepare-mobile.png`
- 比较页：`ui/ui_check/ui_compare.png`

### 发布版本页与最终导航补验

发布负责人完成版本页与导航构建后，新增只读脚本 `scripts/release_page_v1_ui_check.py`（默认临时私人存储服务，也接受 `--base` 检查实际主站）。本轮命令 `python scripts/release_page_v1_ui_check.py --base http://127.0.0.1:18768` 退出 0，日志 `release-page-live.log`，结果 `release-page/results.json`。

1440/390 均从实际主站 discovery 的“更多工具→版本与使用说明”进入 release.html，验证 1.0.0、39/59/56、7173、111/183/96、310、180/3 均可见；主导航恰为四项，三个“开始找导师/项目与材料/我的申请”返回链接实际可跳转并完成页面加载。无横向溢出、无 pageerror；脚本拦截并拒绝任何非 GET/HEAD 请求，实际写请求为零，真实私人签名不变。补验截图 `release-page/release-1440.png` 与 `release-page/release-390.png`，390 截图已人工查看，文字、数据表和返回链接可读。首轮 50 张流程截图加本次两张，累计 52 张。

本轮人工查看了浙江材料手机、山东政策手机、联系/回复手机截图；全页长截图在预览中会缩小，布局/无溢出断言仍以各脚本实际浏览器结果为准。没有把 50 张均称为逐张人工视觉验收。

## 未通过项与已知资料缺口

`public_flow_v13_ui_check.py:75` 的触发过程：以 `school=bit&dept=cs&year=2027&degree=master&route=recommend&track=special&program=0854|test` 打开发现页，展开高级条件，把年度输入改为 2028，尚未点击应用条件时检查全站导航。脚本要求导航仍携带原 `track=special`、`program=0854|test`；实际 discovery 导航保留学校、院系、2027、master、recommend，未带 track/program，导致第 56 行断言失败。日志保留原始 expected/actual。未放宽断言、未修改旧脚本、未自动修产品；该差异是否属于当前范围策略，需结合现行产品规则判定，现态证据按未通过记录。

### 失败的只读定位补记

进一步核对发现，旧脚本第 41 行的同一 URL 还含 `project=secret&target=secret&notes=secret`，其中 secret 在临时库中不存在。当前 `site/discovery.js:197` 将该情况设为 `selectedProject='secret'`，提示项目不存在并继续保留核验保护；`publicScope` 第 29–35 行规定，只有未选择项目、或所选项目与已应用目标完全匹配时才向公共导航附加 track/program。`site/discovery-core.js:41` 的 `projectMatches` 要求完整真实项目、目标快照、学校及年度/学位/渠道均匹配；不存在项目必不匹配。因此这个 fixture 在初始加载时就不携带 track/program，并非编辑年度导致旧范围丢失。

新增只读探针 `python cache/release_v1/validation/probe_scope_contract.py` 退出 0（日志 `scope-contract-probe.log`、结果 `scope-contract-probe.json`）。它用当前公开载荷和未经修改的 discovery 代码，在 1440/390 比较“无 project 参数”和“缺失 project=secret”两种情形：前者初始及年度输入变为 2028、尚未应用时都保留原 2027 的专项/专业导航；后者初始及输入编辑后都不附带 track/program。四场景均无 pageerror、无私人文件创建，私密 project/target/notes 均不进入公共导航。

较新的规则依据是 `tests/project_reviews_v16.cjs:14–23`（目标/学校改变撤下项目判断、projectIntent 阻止通用核验回填、外部专业改变须重新选择），`scripts/project_reviews_v16_ui_check.py:119–130`（缺失项目及项目 API 不可用时维持 unknown/禁用核验，而非静默转入普通浏览），以及 `tests/test_project_reviews_v16.py:132–135`（project_missing 撤下资格判断）。这些测试支持失效项目的保护语义，但没有直接断言缺失项目的公共导航 track/program；该细节由本轮探针核实。现有 `tests/entry_scope_v17.cjs:25–40` 还规定不完整目标不冒称“本目标政策原文”、专业不匹配不混用入口；compare 模板第 78–82 行在跨学校/院系时也清除原专项/专业。

判断：对“旧/伪造私人项目链接已经不存在”的具体用户情景，当前行为符合 v16 之后不借失效项目传播精确范围的规则；对“单纯临时专项浏览，修改条件尚未应用”的情景，应保持旧已应用范围，当前实测也确实保持。旧 v13 fixture 同时混入不存在的私人项目和公共范围预期，不能直接证明后一个情景回归。只读诊断阶段保留旧脚本 exit1，不把探针写成旧脚本通过。

随后经发布负责人明确授权，只修改该测试：将公共 scope 与含 secret 私密参数的 private_scope 分开；新增缺失项目不得建立 track/program 公共范围及不得泄露 project/target/notes 的断言，独立公共分支保留原未应用条件、应用、比较与后续完整断言；详情/招生/通知仍实际输入 private_scope，保留其隐私泄漏检查。产品未改。重跑两次完整 1440/390 均 exit0，第一版为 `public_flow_v13_ui_check-final.log`；第二版在详情/招生/通知继续明确注入私密参数后为 `public_flow_v13_ui_check-final2.log`。初始失败日志、初始 `results.json`、旧 HEAD 测试文本及测试 diff 均保留，最终结论为九组浏览器通过。

预检读取 7173 导师记录，公开载荷也是 7173；政策/来源/入口校验为 111/183/96，未新增 schema 或站点一致性问题。退出 1 来自以下七组 open issues，条目合计 67；预检末尾 `total: 7` 统计的是问题组数：

| 资料文件 | 未结条目 |
|---|---:|
| `hust-cyber.yaml` | 1 |
| `nankai-cs.yaml` | 4 |
| `nankai-cyber.yaml` | 44 |
| `nudt-ai.yaml` | 1 |
| `nudt-cs.yaml` | 14 |
| `seu-auto.yaml` | 2 |
| `whu-cyber.yaml` | 1 |

临时服务日志保留 Windows 10053 导航断连。application/contact 脚本故意损坏临时 workflow 索引时产生的 500 与随后的恢复均如实保留；这些通过脚本的最终断言与退出码见上表，不以日志中出现 HTTP 500 自动判定所有服务失败。

## 私人保护、证据与边界

所有含写操作的浏览器脚本本来就在 `TemporaryDirectory` 中配置 outreach/workflow/discovery；本轮保持其 ROOT 与服务器路径规则，不复制或改指真实私人根目录。`private-before.json`、`private-after.json`、`private-protection.json` 证明真实 outreach/student/student_sop SHA-256 相同，真实 workflow.yaml/workflow.json/discovery.yaml 前后均不存在。真实政策脚本还独立校验 backup.json、letters/backups 路径签名，结果 unchanged。未发送邮件、上传文件、报名、推送或部署。

旧脚本通过专用 harness 只替换证据输出 `cache/...` 路径；`ui_check` 唯一裸 `cache` 输出声明作精确替换。全部适配后的源文本保存在 `adapted/`，初次适配差异保存在 `harness-diffs.log`，最终适配差异在 `harness-diffs-final.log`；公共脚本原 HEAD 文本及独立测试 diff 另存。不覆盖历史 cache；唯一旧测试修改已在上述补记明示。`evidence-index.json` 对本轮证据建索引，不包含该索引自身，私人内容仅保存签名，不复制原文。

本报告只证明当前代码/公开构建载荷在这些本地场景的行为。未全量回源刷新导师、未重新核验全部官方站点、未证明政策/材料覆盖完整、未验证真实邮箱投递或学校系统提交、未验证远程部署。首轮现态验收没有重建站点；后续发布负责人新增版本页/导航并完成构建后，实际主站双视口 release-page 补验结果如上。本报告不代替发布负责人对最终包、主服务资源字节和启动脚本的验收。旧 v20 缓存偏差及其未恢复边界沿用现有记录，没有借本次测试改称恢复。

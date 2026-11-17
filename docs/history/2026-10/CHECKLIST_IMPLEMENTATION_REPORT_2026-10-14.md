# 0.7 申请前核对清单实现记录

实现基于 `b70503ffe`。本次只修改清单页面、共享规则函数与申请项目的公开目标预填；未全局生成静态站、未修改私人记录、未提交或推送。

## 已实现行为

- 学校、院系、入学年度、学位、渠道、普通／专项范围完整且有效后，显示8类核对项：资格、材料、考核、时间、学费、奖助、计划、咨询入口。缺少任何目标维度时先提示补目标，原有政策浏览继续工作。
- 同一范围的学校通用、院系和专业／项目摘要逐层并列。每层没有该项摘要时显示“未整理，待查”，仍可展开查该层原文和来源质量，不能据此判断没有要求。
- 来源状态复用 `AdmissionsRules.quality`。已有摘要不等于个人符合；变化、失败、过期及缺少有效检查的摘要提示重新核对。依据摘要、待查范围、条件性参考和来源异常状态默认可见；原文短片段、定位和逐层来源详情折叠展示，减少手机页面负担。
- 选项以 `program_code|program正式名称` 区分专业／项目。同代码的工程专项与菁英班等特定项目不能互借条款；代码单独不能自动选中一个项目。未指定专业／项目时，专业及有正式名称的专项条款仅作为“专业适用待核对”的条件性参考。学校通用规则在专项范围显示“专项适用性仍待核实”。
- `special` 标签显示“专项/特定项目”，具体政策的专项名称采用现有 `program` 正式名称；名称空缺时明确具体类型待核对。不更改数据schema或既存私人项目的类型。
- 时间节点复用 `eventState`，同时展示所属政策、事件及原文。过去截止写为“该轮次已截止”，过去考核写为“既往安排”，不据某一轮次推断整个年度或目标已关闭。
- 导师资格、当年机会和个人联系方式单列“待选择导师核验”，不由院系计划或招生咨询邮箱推断。
- 按产品审查移除临时已读勾选。清单只用于证据导航；申请进度继续在已有项目与材料流程记录，无localStorage、新私人schema或清单保存接口。
- 带完整公开目标进入发现、院系通知和申请项目。通用项目链接不任选政策；项目预填保留学校、院系、年度、渠道、范围和可选专业／项目。没有规则的已知单位仍可预填；未知单位不伪造名称。只在用户执行保存后写私人记录。

## 文件

- `site/admissions-core.js`：纯清单聚合、目标检查、项目标识。
- `site/admissions.js`：清单渲染、专业／项目选项、公开目标链接。
- `site/templates/admissions.html.j2`：清单区域与森林绿／纸白主题下的390px单列布局。
- `site/workflow.js`：公开目录名称解析与目标预填；保留既有policy直达预填。
- `tests/checklist_rules.cjs`：独立fixture规则测试。
- `scripts/checklist_ui_check.py`：临时站点、临时私人目录的Playwright验收；只复制页面及数据到临时目录，不生成真实站点。

## 验证结果

先观察缺少清单API与UI区域的失败，再实现。追加同code不同special项目与未整理项原文入口失败测试后修复；通用scope项目预填学校／院系以及专项正式名称也由UI测试先捕捉到失败。

| 检查 | 结果 |
| --- | --- |
| `node --test tests/checklist_rules.cjs` | 7通过；覆盖完整／缺目标、未知值、多层未知、年度／渠道／范围隔离、专业与同code特定项目隔离、来源质量与past事件、条款／事件准确来源及旧格式回退 |
| `node tests/admissions_rules.cjs` | 通过；保留既有select／quality／eventState行为 |
| `python scripts/checklist_ui_check.py` | 通过；来源入口、默认可见摘要/缺失/异常状态、折叠各层原文、无临时勾选、专业条件参考、同code专项隔离、项目预填、未保存零私人写入、XSS转义、390px无溢出、file模式 |
| `python -m unittest discover -s tests -p test_admissions.py` | 9通过 |
| `python -m unittest discover -s tests -p test_workflow.py` | 8通过，测试使用临时服务和私人数据 |
| `node --check site/admissions.js` / `site/workflow.js` | 通过 |
| `git diff --check` | 通过 |

截图：`cache/checklist/checklist-desktop.png`、`checklist-desktop-panel.png`、`checklist-mobile.png`、`checklist-mobile-viewport.png`、`checklist-mobile-past.png`。已查看390px截图，来源展开入口可见，页面没有横向溢出。

## 交接与边界

清单规则使用真实数据格式的fixture；UI临时副本限制到既有3个政策样本，并增加同code两种专项fixture，因此不锁定集成后的真实政策总数。UI通过证明流程行为，不代表已人工核验所有招生规则、完整官方覆盖或个人资格已通过。

本次未运行全站生成；集成负责人需在数据与模板均冻结后统一 `scripts/build_site.py` 并跑最终真实站验收。新增官方规则及院系数据由其他任务提供。本页对未收录目标仍明确待查并提供官方招生入口。

产品负责人已查看清单桌面区域与390px首屏并通过验收：八类证据／缺失、条件性参考及阶段边界清楚，无临时勾选。所属文件于2026-10-14冻结；之后仅接受独立审查指出的修复，真实政策／院系整合与全站生成由集成任务执行。

## 独立审查后的来源链接修复

审查发现新增WHU材料／事件来自预报名PDF，而页面此前统一链接政策主来源的正式报名PDF。按来源决策增加兼容读取：条款及事件优先使用 `source_ids` 数组；未提供时回退 `[policy.source_id]`。链接采用 `source.label`，旧来源没有label时采用PDF／官方原文标签。清单字段、清单事件、政策字段及政策事件统一走同一来源解析；混合依据列出所有实际来源。政策整体来源检查仍使用全部 `review_hashes`，没有缩窄质量提示。

先观察Node缺少来源解析函数与UI“第二来源材料仍链接第一来源”的失败，再实施修复。7个Node清单测试、既有招生规则、Playwright准确href／label／混合来源／项目流程／390px与file模式，以及JS语法／diff检查均通过。UI新增fixture中材料只在第二来源，事件也只引用第二来源；时间摘要引用两来源，同时保留没有 `source_ids` 的旧字段测试。

本次修复只改 `site/admissions-core.js`、`site/admissions.js`、清单Node／UI测试与本报告，没有修改数据、validator、私人记录或全站生成。数据方负责精确标注实际来源；修复文件再次冻结，交独立审查闭环及统一集成验收。

## 独立审查后的导师页项目范围桥接

审查确认旧导师核验记录只有导师／年度／学位／渠道，不能代表某个具体专业／项目或专项。现以仅存在浏览上下文的 `track` 与 `program` 识别具体项目范围：传入非空program或track=special时，招生机会与个人申请资格均为unknown，不借旧pass加分、不借旧fail排除、不展示旧记录为当前项目核验依据。由于这两项尚未支持项目维度，即使存量keep_unknown=false，也不会据此硬排除候选；研究、导师资格、邮箱等原规则保持。

页面默认显示当前代码及正式名称／专项范围，以及“核验尚未区分该项目，需对照原文”。筛选附近解释unknown为什么保留、未证明符合；两项控件禁用但保留存量值。旧核验入口与保存按钮禁用，事件处理也拦截强制触发的旧提交。清除学校／院系不会移除项目范围，回政策链接保留track/program；通用找导师提供明确重新打开入口。普通且未指定program的保存行为保持。

transient keys不进入readCriteria、applied、私人schema、POST或备份。没有迁移／修改旧记录，backend不变。通用条件保存与备份仍是原有通用字段，页面对此作明确说明。

| 新增／相关验收 | 结果 |
| --- | --- |
| `node --test tests/discovery_scope.cjs` | 3通过；旧pass无加分、旧fail不排除、同代码不同program不借、普通旧判断与其他字段原样 |
| `node tests/discovery_rules.cjs` | 通过，保留既有原文规则与普通核验语义 |
| `python scripts/discovery_scope_ui_check.py` | 通过；四种项目／专项上下文、旧pass/fail保留且仅资格／邮箱得分、无旧核验详情、禁用控件与强制事件无POST、清院系不丢scope、回政策链接、普通仍可保存、备份精确等于原version/discovery对象且零transient keys、私人原文件在项目范围内不变、390px无溢出 |
| `python -m unittest discover -s tests -p test_discovery.py` | 6通过，私人backend保持兼容 |
| `node --test tests/checklist_rules.cjs` | 7通过，清单隔离与准确出处保持 |
| JS语法及限定文件diff检查 | 通过 |

新增／修改文件为 `site/discovery-core.js`、`site/discovery.js`、`site/templates/discovery.html.j2`、`tests/discovery_scope.cjs`、`scripts/discovery_scope_ui_check.py`及本报告。所有UI数据、legacy核验记录、普通保存和备份均在临时目录；截图 `cache/checklist/discovery-project-scope-mobile.png` 已由产品负责人查看并认可。对应文件再次冻结，等待独立审查关闭scope桥接问题和统一全站集成；未全站build、commit或push。

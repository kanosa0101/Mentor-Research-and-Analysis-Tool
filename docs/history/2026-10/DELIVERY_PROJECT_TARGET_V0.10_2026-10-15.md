# 导师信息与申请目标 v0.10 交付（2026-10-15）

基线 `76788aa6c`。本轮覆盖导师卡片信息层级、BIT CS历史简介中的研究方向原文，以及持久申请目标和有来源的申请时间。实施范围见 `PROJECT_TARGET_RELEASE_PLAN_2026-10-15.md`；模块说明见 `CARDS_V0.10_2026-10-15.md`、`PROJECT_MODEL_V0.10_2026-10-15.md` 与 `PROJECT_UI_V0.10_2026-10-15.md`。

正式构建与全站回归完成。产品、数据、兼容和事件适用性已独立复核；root已只读验收真实站点的单纯研究方向与手机卡片/材料/日期视图。root已验收正式结果、真实预览与精确暂存审计，并授权本地提交。本轮以本地提交保存，不push；提交SHA与最终状态见 `cache/ux_v10/integration/commit.result.json` 及git log。

## 用户行为与证据边界

导师卡片先显示身份、研究原文或明确标注的官网简介摘录、字段来源与记录日期及公开邮箱，主要操作为查看资料和保留比较。完整筛选依据及联系申请入口按需展开。未知资料不生成空列表项，不根据职称推断当年招生资格。

BIT CS共151条，135条只增加 `research_direction_raw` 与对应provenance，内容逐字来自既有官网简介明确章节，原采集日期仍为2026-09-05；16条跳过记录保持不变。这是旧快照提取，不代表本轮重新抓取或确认招生状态。未来抓取与离线补齐共用同一定界规则，人工值不覆盖。

workflow v3保留旧项目自由文本和所有ID/关联，新增结构化单位、年度、学位、渠道、类别及专业代码/名称和时间项。旧记录GET仅内存兼容，不解析名称推断范围，不自动迁移真实文件。政策事件须明确适用于目标并保留阶段、原文、出处与日期精度；个人计划独立标注，保存日期不自动创建提醒。

更改目标须清理不适用的旧政策时间，选择导师不得覆盖项目目标。材料要求与已关联文件并列，登记文件数量不等于材料齐全。测试就绪不证明资格、名额、材料满足或申请效果。

## 集成证据

真实命令、退出码、保护审计、HTTP比对与十张实际页面截图统一保存在 `cache/ux_v10/integration/`，私人文件和cache不提交。

- 初次保护：v0.9的6663个保护项中，135个BIT文件只新增目标字段；另2项变化为授权的contact_util和serve。扩大保护范围后共6761项，包含sites目录和新增project_util。
- 真实私人文件：初次清单3项，与v0.9哈希完全一致；后续每次最终审计要求内容和清单均不变。
- 公开载荷：逐值审计通过，恰135条导师raw及派生search_text、135条compare的raw provenance，以及BIT CS研究方向coverage从0到135；search.js与集成入口工作区字节相同，13政策/14来源/14检查及其他目录值完全相同。
- 原11份未跟踪sources保持排除。其他公开数据、来源与院系配置不在本轮变更范围。

| 正式检查 | 实际结果 |
| --- | --- |
| build / 资源 | exit 0；6527教师/37校/51院系；全部模板与动态loader统一20261015-10 |
| Python / 四Node | pytest 138 passed，3项既有依赖弃用警告；四Node合计12 tests passed |
| UI | 原14组与新增cards_v10/project_v10共16组全部exit 0 |
| 缓存升级 | 同浏览器context分别warm v8、v9后加载v10；两组均exit 0，覆盖JS/CSS及动态search/compare |
| 预检 | exit 1；问题块与v0.9逐字相同，仅csu-auto×4、hust-aia×2、hust-cyber×2、seu-auto×2、whu-cyber×1，五组11项 |
| 保护与语义 | 6761项保护范围无未授权变化/新增/删除，135份BIT逐条原值不变；真实私人3项哈希与清单完全不变；旧11份sources仍排除 |
| 实际预览 | 已核对并替换旧PID34632为隐藏serve.py PID8996（2026-10-15 12:41:13+08）；实际操作仅GET/HEAD |
| 页面与HTTP | discovery/admissions/notices/desk/applications各1440/390，共10张截图HTTP200且无横向溢出；另留真实单纯1440截图；10个HTTP入口/资源与磁盘逐字节相同 |
| 独立复核 | `cache/ux_v10/review/final-review.md`；生产契约及旧UI适配独立检查，执行结果由本轮真实命令单独记录 |

命令与退出码完整见 `cache/ux_v10/integration/final-verification-summary.json`，各命令另存 `.log` 与 `.result.json`。原UI命令仍为ui/application_ui/contact_ui/discovery_ui/admissions_ui/coverage_ui/checklist_ui/discovery_scope_ui、shell_v8/workflow_v8/policy_v8、discovery_v9/workflow_v9/contact_v9；新增cards_v10/project_v10。

旧UI适配只显式展开v10折叠区域，跨项目操作先清除显式项目筛选，备份输出版本断言升为3，保留原dirty取消/确认与损坏恢复流程。推免/统考旧用例改为显式结构字段：自由文本不反推route，原推免入口不认领统考项目，显式保存项目入口沿用其真实范围。初次失败和最终通过日志均保留，不用初次退出码冒充最终结果。

最初公开search审计误把Git LF内容与Windows CRLF工作区作字节比较；改为与操作前真实工作区SHA256比较后通过，Git规范化内容也一致。浏览器页面切换会在临时HTTP服务留下WinError10053/10054连接关闭日志；对应完整脚本exit 0，前端断言与错误检查均保留，没有为此更改生产逻辑。

仅本地提交，不push；原11份sources、真实私人文件及cache不暂存。本地提交范围已按root授权精确暂存，cached清单与差异检查记录于 `cache/ux_v10/integration/stage-audit.json`；root已核对6713项与计划一致、missing/unexpected为空、cached检查通过、无未暂存修改，仅原11份sources未跟踪，并授权本地提交。

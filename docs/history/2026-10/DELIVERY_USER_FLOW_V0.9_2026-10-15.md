# 用户任务连续性 v0.9 交付（2026-10-15）

基线：`2a5611f17`，分支 `codex/reliable-maintenance`。本轮围绕找回导师、保留申请范围、找到扫描材料和安排回复后的下一步，不扩充数据或改变后端、私人 schema。实现及最终回归已完成，root已复核暂存审计并授权本地提交。

## 用户问题与行为

- 找导师增加独立姓名搜索，与研究条件取交集；单人比较候选也能查看、移除和继续联系，刷新保留候选。
- 发现、比较、详情与联系沿用公开范围白名单；导师真实学校院系优先，跨院系或不完整上下文不借用原专业项目，未知保持未知。
- 材料扫描只登记文件，当前项目可直接查看全库未关联项目材料并逐条关联。保留导师关联，重扫保留项目关联；列表与反馈前置，手机操作可到达结果，失败不假报成功。
- 联系准备显示邮箱、主题、正文、联系依据和附件缺项；不完整草稿可保存，最终导出与附件检查仍由后端完成。当前下一步常显，已回复/补材料/约谈且没有未完成导师提醒的目标进入待安排集合，已结束排除。

范围和场景见 `USER_FLOW_RELEASE_PLAN_2026-10-15.md`。模块实现及测试分别见 `DISCOVERY_V0.9_2026-10-15.md`、`PREPARATION_V0.9_2026-10-15.md`、`CONTACT_V0.9_2026-10-15.md`。

## 集成验证

真实命令、退出码、保护审计及截图存于 `cache/ux_v9/integration/`。以下均为最终冻结源码及资源版本9的本轮结果。

| 检查 | 实际结果 |
| --- | --- |
| 保护基线 | 6663个文件与v0.8基线SHA256完全相同，无新增/删除；原11份sources仍未跟踪 |
| build与统一资源版本 | exit 0，6527教师/37校/51院系；全部模板及动态资源引用统一20261015-9 |
| Python / 四Node | 默认pytest最终122 passed，3项既有依赖弃用警告；四Node合计12 tests passed |
| 原11组UI与新增3组UI | 14组全部exit 0，详见下方命令清单 |
| 同浏览器缓存升级 | tests/ux_cache_upgrade_v8.py exit 0；同一context缓存v0.8 JS/CSS后加载v0.9，含动态search/compare载荷 |
| preflight | exit 1，恰原五组11项缺口；schema、字段卫生和站点一致性无新增错误 |
| 18768实际站点与1440/390截图 | 端口原服务退出，隐藏窗口恢复正常serve.py，PID34632；五页十张截图均HTTP200且无整页横溢出；十个入口/资源HTTP与磁盘逐字节一致 |
| 独立复核与暂存审计 | 最终源码独立复核通过；精确暂存清单和cached审计见cache/ux_v9/integration/stage-audit.json |

## 数据与证据边界

公开库沿用6527教师、37校、51院系及13政策/14来源/14检查。测试使用临时私人目录与合成场景，实际站点只读检查，不请求真实私人写入。原11份未跟踪sources、cache、私人材料、备份、公开数据与后端不进入提交。不自动采集、不真实发信，不把界面就绪或文件已登记等同于资格、材料齐全、邮件送达或申请效果。

姓名条件是临时筛选，不写私人偏好；项目自由文本不解析成招生范围，完整结构化绑定及专项/专业核验保存仍属后续设计。最终只作本地提交，不推送。

## 命令、故障与恢复

- Python：`python -X utf8 -m pytest --collect-only -q` 收集122正式测试；`python -X utf8 -m pytest -q` 最终122通过，见pytest_verified日志。`pytest-safe-before.json`/`pytest-safe-after.json`确认运行前后shell测试及两份历史缓存脚本SHA256不变。
- Node：`node --test tests/discovery_rules.cjs tests/admissions_rules.cjs tests/checklist_rules.cjs tests/discovery_scope.cjs`，12项通过。
- 原八组UI：`scripts/{ui_check,application_ui_check,contact_ui_check,discovery_ui_check,admissions_ui_check,coverage_ui_check,checklist_ui_check,discovery_scope_ui_check}.py`。
- v0.8三组UI：`tests/ux_shell_v8.py`、`scripts/workflow_v8_ui_check.py`、`scripts/ux_policy_ui_check.py`。
- v0.9三组UI：`scripts/discovery_v9_ui_check.py`、`scripts/workflow_v9_ui_check.py`、`scripts/contact_v9_ui_check.py`。以上14组均最终exit 0；缓存专项独立计算。

根目录pytest最初误收集cache中历史test_edit.py/test_cleanup.py，后者报ValueError，前者修改了shell测试。已静态检查两份脚本唯一写目标均为tests/ux_shell_v8.py，将该文件恢复到HEAD内容后只作必要链接参数断言适配；产品源码未因此修改。root授权添加两行pytest.ini，将默认收集限定到tests。随后正式目录及默认命令均122通过，最后固定文件状态的默认运行及前后哈希审计通过。失败日志保留；没有删除缓存脚本。一次中间哈希审计撞上同步修正shell断言，后续固定文件重跑解决。

旧UI断言按真实语义适配：workflow有效专项入口补入fixture实际school/dept，保留并强化track/program/单位四字段；缺单位清除由新增contact测试覆盖。shell比较链接按路径和解析参数校验，未知degree/route不携带，原选择动作保留。独立review复核这些差异。shell首次另因服务已退出而无法加载静态资源，恢复18768后完整通过。

独立review发现联系入口自动匹配普通目标、跨单位目标切换继承旧专业的两项P2，均由owner修复并复审；最终contact套件也覆盖缺单位和仅单位上下文。最终复核证据见cache/ux_v9/review/。

## 实际页面与保护结果

实际只读截图：`cache/ux_v9/integration/actual-{discovery,admissions,notices,desk,applications}-{1440,390}.png`。root已检查手机材料结果与待安排入口前置，并在真实18768 IAB输入“柴成亮”查询，候选6527→1，摘要含姓名，详情/联系/政策链接携带bit/cs；只作临时查找，没有保存私人条件。集成检查发现页、今日页手机视口，文本与主操作可见。

保护复核6663文件全部与v0.8基线相同，无新增私人记录；原11份sources仍未跟踪。生成物为6527份详情和8个入口HTML，变化来自冻结模板及资源版本；公共载荷、公开记录、后台与配置无diff。preflight保留华科网安2项、东南自动化2项、武大网安1项、华科人工智能与自动化2项、中南自动化4项，共五组11项，不以修改状态消除。

暂存仅源码、模板、必要测试配置/脚本、文档和生成HTML；缓存、原11份sources、真实私人材料及数据/后端排除。root已接受6563文件精确暂存清单（6527详情HTML、8入口HTML、28源码/模板/测试/配置/文档）及git diff --cached --check通过结果，授权本地提交。提交标识以git log为准，绝不推送。

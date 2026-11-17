# 招生入口与分层覆盖 v0.15 验收记录

日期：2026-10-15。范围为公开招生入口登记、39校目录与分层规则展示；没有执行全站 build、提交或修改私人记录。中央数据与最终真实体验由集成组继续验收。

## 交付

- `crawler/admissions_entries.py`：`load_catalog(root)` 返回全部学校和真实院系集合；`validate_entries(data, units, sources)` 严格校验 version=1、字段、来源、学校/院系、非未来核对日与 (school,dept,source_id) 唯一性；`load_entries` 兼容旧 fixture 缺文件；`source_status(entry, check, today=None)` 区分失败、未检查、超过7天、超过30天待核对与近期有效。失败保留历史成功日，不把本次尝试当成功。
- `build_site.py` 在 payload 新增 schools 与 entries；preflight/check_admissions 共用全学校目录，允许未接入院系学校的学校级政策，绝不虚构院系。
- `report_admissions_coverage.py` 的 `build_report(schools, units, data, entries, checks, year=2027, degree='master', route='exam', track='ordinary', program='', today=None)` 按学校层及每院系列出三层 policy IDs、八类字段集合、source 状态、逐摘要待复核与入口缺口。CLI 支持同名筛选参数及 --root/--output。当前配置分母为39校/37校接入院系/51院系；摘要类别数不作为完整率。
- 招生页学校下拉与目录读取全部 schools，缺 schools 的旧 fixture 由 units 推导；无院系学校仍可查看学校规则，明确目录待接入。
- 官方招生入口前置于大清单，显示 scope、note、核对/成功/尝试日期及真实失败/未检查/过期状态，不用师资入口替代研招入口。
- 学校通用、院系附加、专业专属分别展示。未选院系、院系未整理、无目录与非法院系区分；专业未指定不计专属适用，专项学校通用条款仍待核实。
- 具体专业过滤保留通用规则及所选专业卡，隐藏其他专业卡；下拉由未按专业过滤的 matching 集构建，选中后其他选项不消失。命名专项即使 level 为 school/dept 仍视为专业专属。

## 验证

先写新增后端测试，缺模块红灯；学校39项及两专业 UI 用例在旧逻辑下分别失败后修复。

- `python -m pytest tests/test_admissions_entries_v15.py tests/test_admissions.py tests/test_admissions_json_v15.py -q`：43 passed。
- `python -m pytest tests/test_workflow.py -q`：8 passed。仅已有 pytest_asyncio 弃用警告。
- `node tests/admissions_rules.cjs`：PASS。
- `node --check site/admissions.js` 与所改 Python 模块 py_compile：通过。
- `python scripts/admissions_v15_ui_check.py`：隔离临时站点通过39校、分层缺口、具体两专业、三层命名专项、失败历史成功日、未检查/过期、非法院系、未选院系、无院系学校、旧 payload 无 schools/entries、1440/390无横向溢出与不写私人文件。截图位于 cache/policy_v15/coverage_ui/，已查看1440全页布局。
- `python scripts/report_admissions_coverage.py --output cache/policy_v15/coverage_ui/coverage-report.json`：成功，分母39/37/51。

报告共用 source 的一旧一新摘要测试保证只旧摘要待复核；source_states 不再混入最后一条 policy 核对日。命名专项在 school/dept/program 三层测试未指定、其他专业、精确指定三种情形。

## 文件

新增：crawler/admissions_entries.py、scripts/report_admissions_coverage.py、tests/test_admissions_entries_v15.py、scripts/admissions_v15_ui_check.py。
修改：scripts/build_site.py、scripts/preflight.py、scripts/check_admissions.py、site/admissions.js、site/templates/admissions.html.j2。

模块脚本资源 admissions.js 已改15；共享 data/core 资源版本留集成组统一。旧 tests 未修改。此版本不声称39校政策齐全，不推断个人资格、导师名额、截止时间或网上确认流程。

## 补充：无院系学校的项目闭环

workflow.js 的学校选项、显示名与预填统一读取 payload.schools，缺该字段仍兼容 units；院系继续只来自真实 units。新增南开无院系政策→项目预填→保存→回查学校政策隔离 UI，先在旧实现复现裸 ID/未收录学校失败。新实现显示南开大学、院系待补，保存 dept_id 空串与 deadlines 空数组；即使学校政策有官方事件也不开放加入日期，完整清单与事件仍保留原六项门槛。applications template 的 workflow.js 版本改15。项目保存只写隔离临时 private，不碰真实私人文件。

追加最终验证：合并运行四组后端测试51 passed；`python scripts/workflow_v8_ui_check.py` 原有项目上下文、重复提醒、分区/视图保护、独立任务、到期/未来划分及手机布局兼容验收 PASS（临时服务/临时私人目录）。

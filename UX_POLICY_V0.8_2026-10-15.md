# 学校政策与通知 UX v0.8 验证记录

日期：2026-10-15。模块冻结，供主agent集成和独立复核。未运行build_site、未提交、未修改数据/schema/private/shared CSS/nav。

## 修复范围

- `site/templates/admissions.html.j2`：标题、简短用途和学校优先的目标表单；范围说明折叠；当前学校院系导航前于全校目录，目录置于主体后；官方入口就近展示，覆盖统计按需展开。
- `site/admissions.js`：完整目标后的找导师/通知/预填项目移到八类清单前；原有13份政策正文默认折叠，层级、年度、范围、来源质量、已整理数量/缺失提示与时间状态可见；目录/方向切换清除无效专业；所有通知入口携带完整目标。
- `site/templates/notices.html.j2`：中文学校院系名称；当前范围官方入口、空结果与清除标题条件；真实目录URL回退，未登记则明确告知；来源技术详情折叠，当前范围抓取失败警告保持可见。兼容旧`school=tsinghua/cs`及分离`school=tsinghua&dept=cs`，返回政策保留year/degree/route/track/program/group，切换院系清除专业。年度/渠道仅为导航上下文，不过滤未知通知。
- 全范围未选学校时提示“选择学校与院系，查看对应官方招生入口”，避免把未选目标说成全库没有来源。

## 复现与验证

修复前审计和复现：`cache/ux_v8/policy/audit.md`、`interaction.json`、`measurements.json`。完整目标移动端下一步原在约3048px；现前置到清单顶部，root viewport审阅约830px。

通过：

- `python scripts/ux_policy_ui_check.py`：临时目录渲染模板与静态服务器；1440/390无文档横向溢出；默认13卡全部正文折叠；完整八类、缺目标、未知院系、无规则仍八类待查；专业在目录/方向变更时清除；通知往返完整目标；中文选项；未知年份通知仍8条；已知未接入院系使用登记URL、完全未知无猜测URL；零结果恢复；模拟政策来源失败和通知来源失败默认可见；file模式；无页面异常。
- `node tests/checklist_rules.cjs`：7/7通过，含同代码不同项目、普通/专项隔离、质量异常和原文引用。
- `node tests/admissions_rules.cjs`：PASS。
- `node --check site/admissions.js`、owner路径`git diff --check`：通过。

UI脚本一次导航断言在页面脚本初始化完成前读取值失败；加导航后的networkidle等待后通过。未以修改产品逻辑规避测试。

最终截图位于 `cache/ux_v8/policy/after/`：admissions-empty、admissions-target、notices-target，各1440与390的viewport/full共12张。截图引用当时共享CSS/nav，与集成最终产物仍需再验证。

## 保留边界

规则数据及引用没有变；质量检查仍为原逻辑，未把抓取成功、摘要核对或候选通知当成资格满足/报名开放。此轮仅验证本地呈现和上下文传递，不代表真实申请效果。原政策到项目的policy预填行为保留；私人记录仍须显式保存，测试无私人API。

## 独立复核后的 P2 闭环（第二次冻结）

- 已按 `cache/ux_v8/review/policy-extra.log` 复现路径修复：通知显式切换院系同时清除旧program与group，保留year/degree/route/track；computer方向到自动化院系返回不会再被旧方向判无效。
- 学校级目标（如school=tsinghua&year=2027）现在仅聚合该校已接入院系，展示“全校已接入的2个院系栏目（不是全校全部通知）”及两处登记官方入口；回链保留school/year、不虚构dept。未知学校仍零结果并保留原school；不会扩大成全部通知。
- 恢复折叠目录内全范围/按方向浏览院系列表，保留原coverage行为；目录不再占主阅读流。
- 新UI回归新增跨方向返回、学校级范围/回链/来源数量、未知学校不扩大三组检查，`python scripts/ux_policy_ui_check.py`通过；两组Node规则仍全部通过，syntax/diff检查通过。
- `scripts/admissions_ui_check.py`、`coverage_ui_check.py`、`checklist_ui_check.py`仅适配展开正文/覆盖步骤，及通知URL分离school/dept的等义断言，没有删除原有内容/私有写入/来源断言。旧UI生成产物统一由集成agent build后执行，本模块不build。

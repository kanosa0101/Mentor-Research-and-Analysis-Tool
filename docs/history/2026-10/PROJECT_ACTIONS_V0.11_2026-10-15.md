# 项目材料与提醒入口 v0.11

日期：2026-10-15

## 用户场景与实现

在项目“目标与要求”内直接管理当前项目材料、查看当前项目提醒；已有文件逐条展示标题、类型及索引缺失状态，并提供编辑材料关联入口。结构化目标尚未完整的旧项目也可使用这些动作。材料列表不推断申请完成度或资格，提示按官方要求核对文件内容。

新动作复用现有项目筛选和未保存编辑确认，再切到对应分区；材料管理默认关联所选项目。取消离开保留原 tab、项目筛选、URL 与字段。成功切换时同步 URL 和返回联系人工作台的项目 ID，清理旧 target、政策、来访目标，避免刷新或返回旧项目。URL 不写项目名称、材料标题或备注。

## 变更范围

- `site/workflow.js`：材料明细及项目入口、最小上下文同步。
- `site/templates/applications.html.j2`：材料明细列表间距与手机按钮换行。
- `scripts/project_actions_v11_ui_check.py`：真实临时服务中的用户场景测试。

未 build、未更新 cache 版本、未 commit，未读取或写入真实私人记录。

## 验证

- `python scripts/project_actions_v11_ui_check.py`：PASS。A/B 材料与提醒隔离，缺失材料可编辑且不更改 B，旧结构目标可用，取消 dirty 确认后上下文保持，刷新仍 B，返回链接 B，390/1440 无页面水平溢出，零 pageerror。
- `python scripts/project_v10_ui_check.py`：PASS。现有结构化目标、政策事件、日期与私人上下文回归。
- `node --check site/workflow.js`：exit 0。
- `git diff --check -- site/workflow.js site/templates/applications.html.j2`：exit 0。

测试全部使用临时目录及临时 HTTP 服务。首次受限环境临时目录返回 WinError 5，之后临时目录置于 `cache/ux_v11/project_actions`；受限浏览器进程挂起后已中止，使用自动审批允许的非沙盒测试运行通过。未修改产品实现来绕过测试。

截图：`cache/ux_v11/project_actions/project-actions-390.png` 与 `project-actions-1440.png`。已查看 390 全页截图，材料行与动作清晰可见，无横向溢出。

## 真实目标上下文补测（13:25）

补充从真实 `project=A&target=目标A` 与完整来访 goal 进入的场景，分别切 B 材料、B 提醒入口。取消 dirty 确认时 URL、返回链接、tab、筛选、字段保持；接受后清理旧 target/goal、刷新仍 B、真实点击返回联系人页后项目选择和所选目标均属于 B。最终新 UI 运行 exit 0。

最终日志：`cache/ux_v11/project_actions/final-ui.log`；退出码：`final-ui.exit.txt`。首轮补测的 `initial-target-test.log` / `.exit.txt` 保留：当 B 绑定同一导师时 API 会创建 B target，联系人页正确选择 B；测试最初误要求返回后完全没有 target，已改为精确检查没有旧 A target 且实际 target 属于 B（或无 target）。生产未更改。v10 回归未重复，其此前 PASS 为工具输出（无独立落盘日志）。

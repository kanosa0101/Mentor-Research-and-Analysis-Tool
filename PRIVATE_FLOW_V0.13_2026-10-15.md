# 私人申请流程审计与修复 v0.13（2026-10-15）

范围：`applications`、`desk` 的项目、材料、草稿/EML、人工发送确认、回复、提醒、恢复及未保存表单保护。全部复现和写入使用临时服务/合成记录；未读写真实私人内容。未执行生产构建或 Git 提交。

## 已复现的问题与最小修复

1. **P1 项目下拉切换不保持当前项目。** 基线选择项目 A 后，URL 仍不带 `project`；刷新回到全局。选择 B 后返回联系人工作台的链接仍可能保留 A 的 target 或回全局。在 `site/workflow.js` 将已有卡片快捷入口的上下文同步逻辑收敛为 `syncProjectContext()`，下拉、卡片快捷、查看全部导师统一调用。确认切换后更新纯私人项目上下文，清除旧 target/来访 policy/goal；B 的导师保持可用时允许匹配 B 的实际目标。选择全部项目清旧项目、目标和导师范围。取消切换保留原下拉、URL、返回链接、当前分区及输入。
2. **P2 跨时区“今天”不一致。** 冻结 UTC `2026-10-15T17:00:00Z`、浏览器 `America/Los_Angeles`，基线 desk 今日为 `2026-10-15`，项目摘要为上海日期 `2026-10-16`。统一 desk 的今日、发送/回复默认日期，以及补录沟通默认日期为 Asia/Shanghai；不修改已存 due_date 或原始事件时间。
3. **新用户入口小修。** 空项目列表改为说明先填名称、可随后补学校与招生目标；无文字的分区反馈不占高度，错误出现后仍可见。保留整体主题、表单结构和分区。

## 实际验证

- `python -m pytest tests/test_contact_flow.py tests/test_workflow.py tests/test_project_api.py tests/test_project_model.py -q`：32 passed，1 条依赖弃用警告。
- `python scripts/private_flow_v13_ui_check.py`：PASS。涵盖取消丢弃、确认 B、refresh/reload/返回联系人工作台、相同导师在 A/B 的目标不串、全局清上下文、空反馈/错误反馈、1440/390 无页面横溢，以及洛杉矶浏览器下冻结上海跨日的一致日期与到期待办。
- `python scripts/contact_ui_check.py`：PASS。临时新用户项目/材料→草稿→EML→人工确认发送→回复/下一步→持久化/移动/恢复/file 模式；文件变化/缺失和发送锁定等既有断言保留。
- `python scripts/workflow_v8_ui_check.py`：PASS。
- `python scripts/project_actions_v11_ui_check.py`：PASS。
- `python scripts/workflow_v9_ui_check.py`：PASS。
- `python scripts/desk_actions_v11_ui_check.py`：PASS。
- `python scripts/recent_actions_v12_ui_check.py`：PASS。
- 初次误用了不存在的旧测试名 `test_contact_api.py` / `test_contact_model.py`，未收集到测试；随后使用实际存在的四个测试文件完整通过。失败日志未用于通过声明。

证据保存在 `cache/system_v13/private/`：基线 `audit-repro.json`、`date-before.json`，新用户 desk/applications 1440/390 截图、修复后截图、各完整测试日志。临时 HTTP 客户端关闭可能留下 WinError 10053 日志，断言及进程 exit0；未抑制服务器异常。

## 审计未发现的问题与边界

- 临时验证 desk 编辑提醒标题后，原始政策时间/来源备注仍完整保留。
- 草稿导出不计实际发送；实际发送确认后版本锁定。
- 恢复有旧索引备份，非法恢复拒绝与历史版本兼容由 API 回归覆盖。
- 本轮不代表实际邮箱投递或申请结果验证；政策覆盖、资料完整性仍按当前来源如实展示。

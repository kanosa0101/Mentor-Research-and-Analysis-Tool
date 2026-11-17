# v0.11 今日待办入口上下文修复

用户场景：工作台当前选中申请 A，但今日待办 / 未来计划同时列出申请 B 的事项。点 B 的「管理任务」应进入 B 的提醒页。

## 根因与最小修复

`site/desk.js` 的提醒卡片无对应导师目标时使用 `manageUrl()`，该函数读取当前选中目标、当前项目与来访招生范围。因此 B 事项链接携带 A 的 target / project，申请管理页又正确优先采用 target，最终打开错误申请。

新增 `reminderManageUrl(reminder)`，仅从该事项读取有效项目、有效导师，固定 `section=reminder`。不传当前 target 或来访招生字段。未关联项目的导师事项进入跨项目的该导师提醒范围。既有对应 target 的「继续该导师」按钮不变。其余 `manageUrl()` 调用均为当前工作区的管理/材料/创建入口，未发现同一逐条记录串线原因，保持原状。

## 验证

- 新脚本 `scripts/desk_actions_v11_ui_check.py`：修复前在 `B reminder must not inherit current A target/project` 断言失败；修复后完整退出 0。
- 当前 A 下 B 项目事项、无项目导师事项、B 导师无 target 事项，进入正确项目 / 导师 / 提醒 tab；链接不含旧 target。
- 导航前后临时 workflow 完全一致；公开招生/发现/导师链接不带私人项目、target 参数。
- 原对应 target 的继续按钮仍进入该目标联系准备页。
- 390 / 1440 宽截图已保存，无页面横向溢出；已目视检查 390 截图。
- `scripts/contact_v9_ui_check.py` 完整退出 0，涵盖草稿就绪、未保存修改、发送记录、跟进、项目提醒隔离与招生范围隔离。
- `git diff --check -- site/desk.js` 退出 0。生产改动仅 7 行新增、1 行替换。

执行命令（进程级临时目录，所有写入为测试夹具）：

```powershell
$env:TEMP=(Resolve-Path cache).Path
$env:TMP=$env:TEMP
python scripts/desk_actions_v11_ui_check.py
python scripts/contact_v9_ui_check.py
```

默认系统 sandbox TEMP 无写权限；改用工作区 cache 后，沙箱浏览器启动未完成，停止该测试并以获准本地浏览器执行重新验证。两次最终回归均使用 `TemporaryDirectory` 和临时 API 服务；未访问真实私人 workflow。初次夹具尝试无项目且无导师事项被现有 API 正确拒绝，改为合法的无项目导师事项。

截图：`cache/ux_v11/desk-actions/desk-reminders-{390,1440}.png`、`applications-b-reminders-390.png`。

本子任务未 build、未修改缓存版本、未 commit。当前修复只保证管理入口范围准确；不新增自动提醒或外部通知。

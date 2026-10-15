# 准备清单政策回查入口 v0.20

## 改动与范围

仅改`site/material-actions.js`，增加一个短渲染辅助函数及一次调用。选中项目后，无论是否存在分阶段材料动作，都显示“核对本项目政策与材料要求”内部链接。scope与`site/workflow.js::projectScope`一致，保留学校、院系、年度、学位、渠道、类别，正式专业仅在有名称时使用`code|name`。仅有代码不生成完整专业参数；未知院系原样保留，不替换或借用其他单位。

申请目标缺项或单位未确认时说明未知范围，并通过现有`data-edit-project`与`data-project-section`行为打开当前项目编辑器。仅缺正式专业名称时说明专业要求仍待明确。未复制摘要渲染、未创建材料动作或准备记录、未添加后端API。原有未保存输入保护继续适用于新编辑按钮。

未改中央招生数据、后端、模板、旧测试或资源版本。资源版本由root统一更新。未提交Git。

## 浏览器红绿证据

新增`scripts/material_policy_return_v20_ui_check.py`，在临时站点运行真实applications脚本，私人API用内存响应截获，政策链接目标为本地静态stub，没有访问外部网站。先在改动前运行，空清单断言明确失败：`empty: expected policy return link, found 0`；对应`cache/policy_v20/material_policy_return/red.json`。修复后同脚本通过，证据`green.json`及`v20-return.log`。

8种目标分别在1440/390验证：空清单、正常动作、不同年度/博士/assessment/专项/正式专业、未知院系、缺院系、缺全部目标、仅代码、仅名称。16次真实点击后实际URL query均精确相等；同页切换项目不串范围，缺目标入口实际打开对应项目。浏览器无JS异常、无自动POST、无横向溢出。另验证新编辑按钮遇到未保存准备备注时取消可保留输入，确认放弃后才能进入编辑器。

截图`empty-1440.png/empty-390.png/normal-1440.png/normal-390.png`位于同一证据目录；已实际查看390空清单截图，链接、未知专业提示与编辑入口可见，无横向裁切。

## 针对性回归

- `python scripts/material_policy_return_v20_ui_check.py`：PASS。
- `python scripts/material_frontend_v19_ui_check.py`：PASS，原有双项目/双动作、dirty、409、来源变化与缺文件等流程。
- `python scripts/material_frontend_v19_integration_check.py`：PASS，真实master/phd公开政策及临时private保存、历史、文件版本、备份恢复、1440/390。
- `python scripts/application_ui_check.py`：PASS，项目、文件关联、沟通历史、多提醒、持久化、备份恢复、移动端及file模式。
- `node --check site/material-actions.js`、`git diff --check -- site/material-actions.js`：PASS。

三组回归日志保存在`cache/policy_v20/material_policy_return/`。旧application回归期间，页面重载中止的请求触发服务端`ConnectionAbortedError WinError 10053`日志，最终浏览器全部断言通过并输出PASS；未借此修改无关后端。旧集成/申请测试的主动保存仅使用其临时private，不涉及真实私人记录。回查链接测试证明本地导航与scope正确，不证明外部官方原文可达，也不证明目标要求完整。

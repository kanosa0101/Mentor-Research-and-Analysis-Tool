# v0.19 材料准备前端交付

本轮在现有申请工作台增加「准备清单」，项目卡有「准备材料」入口。动作默认渐进收起，仅展示标题、最近人工登记、来源状态、真实摘要核对/成功检查日期及条件存在提示；展开「查看要求并登记准备」后再阅读全文、选文件、登记和查历史。按项目/政策/动作保留展开态，保存回读不会将用户已打开的动作和历史关回去。按当前项目和阶段阅读动作、原文、条件与事项，文件通过checkbox多选；状态与备注由本人手动登记，明确保存才新增历史。文件不上传，已提交不表示院方收到或审核通过。原有项目、文件索引、沟通、提醒仍沿用原流程。

公开招生页面只渲染公开材料动作，逐项保留政策/动作条件、来源质量与精确事项原文。入口只预填目标；没有项目时引导创建，不自动保存。公开渲染不会访问私人API或浏览器持久存储。

未保存输入按动作保护：切换项目/分区与离开页面有确认；无关刷新不替换当前输入的目标/动作指纹；来源或目标冲突409保留输入。保存一个动作不清除另一动作的未保存备注。异步GET有serial与dirty revision保护，不让旧项目请求复活。重新核对按钮明确放弃未保存输入后载入当前清单。

历史单独显示每次人工登记的状态、目标、动作原文、登记时来源与文件内容指纹/路径/修改时间；目标/动作/来源或文件变化显示需复核。当前清单之外的历史也保留。只有当前官方目标、动作、来源与条件仍适用的最近记录可绑定该动作明确关联的事项提醒；仅文件变化仍可设置准备/补正提醒，并明确文件需复核、不表示完成，原始时刻不补造。

## 已完成验证

- `node --check site/material-actions.js`、`workflow.js`、`admissions.js`。
- `python scripts/material_frontend_v19_ui_check.py`：1440/390真实Chromium、两项目/两动作同文件隔离、checkbox多选、dirty项目/分区取消、后台刷新仍提交原指纹后409保留输入、同时编辑两动作保存一个不丢另一个、条件默认不勾/专业未知禁止/来源changed禁止、文件缺失历史与提醒保留需复核提示、绑定事项提醒、空项目/503降级、公开渲染无私人请求/localStorage、无横向溢出。
- `python scripts/application_ui_check.py`：原项目/文件关联/沟通追加/多提醒/持久化/备份恢复/手机/file模式回归通过。最终复跑的共享fixture已由root加入新模块，原4分区与模块并存通过；不替代新模块专项测试。临时服务关闭/页面导航取消请求时出现Windows10053连接取消日志，进程退出0，未改后端。

截图位于`cache/policy_v19/material_frontend/`，均为临时项目与合成文件。

## 统一构建后的真实集成已完成

`python scripts/material_frontend_v19_integration_check.py`最终退出0。公开数据为11政策/33动作；代表性流程选择西工大2027硕士统考与清华计算机2027博士申请考核，全部项目/材料/备份写入临时private与临时文件，未连接18768或发送材料。

- 两目标实际后端项目→材料登记→checkbox选文件→人工已准备→新历史记录及文件指纹→v4完整包装backup/restore通过；更新临时文件后记录显示changed/需复核，恢复不会把变更文件误判为旧版本。
- 西工大6112政策/动作条件原文在对应动作中可见，确认checkbox默认不勾。
- 清华申请材料动作绑定实际原文事项，页面点击建立提醒成功；验证提醒备注保留精确原始at、quote与source_url。
- 两目标1440/390无横向溢出，补充首屏及滚到新动作区域的viewport截图。真实公开招生页渲染材料动作，未请求私人API。
- 官方原文链接验证为精确登记source URL、target=_blank、新窗口跳转；测试中仅导航响应使用合成HTML，不能据此声称官网实时可达或内容已重新核验。

测试夹具修正记录：最初合成policy未给track产生KeyError，已按现有默认ordinary；旧导航/历史summary选择器过宽及默认收起后的visible等待，已改为精确区域与attached后显式展开。真实集成脚本先由root发现backup返回为version/workflow包装，断言改读workflow.material_tasks，restore仍传完整包装，未改API。首轮按API索引猜卡片DOM顺序错误（UI按阶段重排），改为data-material-action稳定定位；原文默认policy来源与动作source_ids不同，改核对动作明确来源。

真实集成随后发现测试过早在保存响应之后、材料GET回读之前展开历史，读到0记录，随后回读重建关闭历史；最终测试明确等待所选动作最近人工状态更新后再操作，生产同时保留历史details展开态。未使用force click或绕过可见性校验。

最终截图：`master-real-1440.png`、`master-real-390.png`、`phd-real-1440.png`、`phd-real-390.png`及对应`-viewport.png`/`-actions-viewport.png`，均位于上述cache目录。代码与脚本已冻结，未提交。

最终可引用日志：`cache/policy_v19/material_frontend/frontend-ui-final.log`与`cache/policy_v19/material_frontend/frontend-integration-final.log`。这两个文件为冻结代码后重新执行脚本的stdout/stderr实际输出；旧application回归的PASS已在本轮工具输出核对，未另造日志。

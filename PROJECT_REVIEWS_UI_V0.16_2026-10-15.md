# 项目级核对前端 v0.16（2026-10-15）

本批将已有“我的申请”项目接入找导师，以明确项目ID与八字段目标快照隔离“招生机会”和“本人资格”的私人核对记录。记录属于用户自己的核对，不是系统招生认证。

## 已改动

- `site/workflow.js` 的项目“带目标找导师”本机入口携带项目ID；`applications.html.j2` 仅将对应 workflow 资源升级到16。
- `site/templates/discovery.html.j2` / `site/discovery.js` 增加项目选择、完整目标/待补目标、编辑项目入口和“使用此项目最新目标”。专项未选择有效项目时继续禁用保存；明确选择普通浏览才退出私人项目意图。
- 核对表单位于结果主列顶部；桌面两组证据并排，手机单列，提供受未保存保护的“收起并返回候选”。
- 两项判断各有独立证据：官方URL、原文和适用说明，或当前项目同导师已收到回复的ID、原文和适用说明。回复选择不包括草稿/备注；保存不会发送邮件。
- `site/discovery-core.js` 仅应用准确项目ID、导师ID及目标快照的当前有效状态。学校多选、年度/学位/渠道冲突、项目目标变更撤下旧判断。项目缺失或项目API不可用时明确保持unknown，不能借旧v1通用结论。
- 有效项目下hard/keep_unknown正常作用；无效专项范围继续保留原保护。一般浏览、原资料完整度排序与随机顺序保持。
- 项目与证据失效原因有中文解释，并可展开查看失效/旧目标记录。未登记监测的官方来源明确要求自行回查；新增source_registered原因提醒重新核对。
- 查看候选、窗口focus和浏览器返回pageshow重新GET最新状态。八字段 selectionGoal 与编辑表单 reviewGoal 分开保留；外页修改目标不会把旧表单自动绑定新目标。409保存冲突保留输入；切项目/候选/范围或离页时保护未保存修改。
- 项目与旧通用两个保存分支均以表单revision保护异步回调；POST期间继续输入或重开同项目同导师表单时，旧响应不能关闭新表单。保存期间阻止重复提交，失败保留输入。POST后刷新期间重开的表单也保持；POST已成功、随后GET失败明确显示已保存/刷新失败，并撤下缓存的项目判断。
- publicScope与官网链接不携带私人项目ID、名称、备注或核对文本。有效同范围“准备联系”本机链接可带项目ID。

## 验证与证据

先新增 `tests/project_reviews_v16.cjs` 并观察原实现在精确项目核对断言失败，再实现；追加missing普通项目意图负例亦观察原路径借用v1 pass失败，再修复。纯函数验证包含两项目隔离、八字段目标变化、hard fail、有效项目unknown排除、无效专项保护、学校多选、过期、导师ID和独立状态。

运行：

- `node tests/project_reviews_v16.cjs`
- `node tests/discovery_rules.cjs`
- `node tests/discovery_scope.cjs`
- `node tests/discovery_ranking_v14.cjs`
- `node --check site/discovery.js`
- `python scripts/project_reviews_v16_ui_check.py`
- `python scripts/discovery_v9_ui_check.py`
- `python scripts/discovery_scope_ui_check.py`

实际UI脚本直接渲染临时模板并使用临时site/private与本地服务，不调用build、不接触真实private。场景：同导师两隔离项目相反结论；机会使用已收到回复、资格使用独立官网依据；草稿不可引用；hard+不保留unknown仅留当前pass；未保存切项目取消；外部API改专业后的真实POST409；同页刷新核对状态撤判断、保留输入，并明确确认最新目标后继续；刷新与学校多选；先存v1 pass/fail再访问missing普通项目与项目API503，均无泛化结论泄漏；用户明确普通浏览后恢复一般规则。新增实际延迟POST响应测试先复现成功回调错误关闭新输入，再验证项目与通用两个分支均保留提交后新输入。

截图位于 `cache/policy_v16/review_ui/desktop-form.png`、`mobile-form.png`、`desktop.png`、`mobile.png`。1440×1000和390×844检查无横向溢出；表单使用scroll margin避开固定导航。截图为临时测试项目与测试原文，不是真实招生结论。

## 边界

此批不扩充公开招生事实，不验证用户真实资格或导师真实名额。官方来源内容/指纹/回复失效与备份恢复的服务端规则由后端测试覆盖；前端分别呈现服务给出的有效状态。并未声称实际浏览器跑完所有学校与项目组合，也未模拟每一种网络延迟排列。构建、最终资源一致性检查与整合审查由root执行。本分工不commit、不push、不修改旧测试或生成构建文件。

# v0.8 全局导航与导师发现交付（2026-10-15）

## 审计与可复现问题

截图位于 `cache/ux_v8/shell`，基线为 1440×900、390×844 viewport（不只是长截图）。只读预览由 scripts/serve.py 提供，PID/log 同目录；未对真实 private 发写请求。

1. 手机主导航8项横滑，“我的申请”首屏不可见。owner: `_nav.html.j2`, `ui.css`；改四主任务+更多工具。
2. 查看候选按钮桌面 y=1187、手机 y=1172，均低于首屏。owner: `discovery.html.j2`；关键词和查看候选前置，高级条件折叠。
3. 卡片默认只展示邮箱命中与重复未知，没有明确方向。owner: `discovery.js`；只展示现有 research_direction_raw 短原文，空值说明暂未整理，不从简介造方向；详细依据折叠，未知标签始终保留。
4. 改筛选条件时旧结果仍在且没有提示。owner: `discovery.js`；未应用提示、已应用条件摘要、手机提交定位结果。
5. 发现页无法加入对比，需转全量表重新找。owner: `discovery.js`；复用 compare_sel，加入/移出、最多5位、2位起可比较。
6. 对比页窄屏多列挤压，方向标签误作原文方向。owner: `compare.html.j2`；表格内横滑、明确研究方向与自动检索标签独立、准备联系与清空选择。
7. 详情页新准备联系入口与旧跟进表单双流程混淆。owner: `detail.html.j2`；新操作前置，旧记录默认折叠并明确不与项目同步；缺失字段呈现“暂未收录”。
8. 全量表当前对比选择与下一步不清晰。owner: `index.html.j2`；显示选中数量、可达对比入口、窄屏表格横滑提示。

## 已完成范围

共享 ui.css/_nav；index/discovery/compare/detail 模板；discovery.js；tests/ux_shell_v8.py；旧UI脚本步骤适配 scripts/discovery_ui_check.py、scripts/discovery_scope_ui_check.py、scripts/ui_check.py。未修改匹配core、数据、private、backend，未执行全站 build 或 commit。

发现页向 desk/policy/notices 传递真实 school/dept 与已知 year/degree/route/track/program，暂态范围不写入私人条件。scope 核验限制保留。

## 验证

- 先运行 `python tests/ux_shell_v8.py --baseline` 失败：390屏查看候选 y1171.609，高37。
- `python tests/ux_shell_v8.py` 通过：四导航/键盘更多工具、首屏CTA、dirty/应用摘要、手机定位结果、加入移出/最多5对比、详情旧表单展开、明确研究方向/检索标签区分、390/1440各页面无document横溢出、scope上下文与disabled review、file模式。脚本渲染模板并mock API，未写真实private；详情截图是公开目录记录渲染fixture，非完整生产详情数据。
- `node --test tests/discovery_rules.cjs tests/discovery_scope.cjs`：4/4通过。
- `python scripts/discovery_scope_ui_check.py`：临时private+临时渲染通过，特定项目不复用旧pass/fail、不提交旧核验POST，普通范围保存正常。
- `node --check site/discovery.js` 通过。
- 旧 discovery_ui_check/ui_check 已适配折叠控件，需root全站构建后的集成运行（本agent不build）。

## 视觉验收入口

- `cache/ux_v8/shell/discovery-initial-390.png`：手机初始视图。
- `cache/ux_v8/shell/discovery-after-1440.png`：桌面视图。
- `cache/ux_v8/shell/discovery-after-390.png`：手机筛选后的结果。
- `cache/ux_v8/shell/compare-after-390.png`：手机5导师比较。
- `cache/ux_v8/shell/detail-after-390.png`：手机详情与默认折叠旧记录。
- `cache/ux_v8/shell/index-after-390.png`：手机目录。

主测试为可独立运行的显式脚本，不在 pytest 默认 test_* 发现范围内。

## 独立复核 P2：折叠后的已应用条件摘要（08:50 补丁）

- 回归先失败：选择自动化与控制后结果收窄，但摘要不含该方向；tests/ux_shell_v8.py 在断言方向名处失败。
- apply 在读取条件时同时保存独立的 appliedGroup 快照；过滤与摘要使用同一快照，不把临时方向添加到 readCriteria / private schema。
- 已应用摘要增加院系方向、五项必须/偏好/不限制规则，以及保留/不保留必须条件待核实候选策略。具体项目的招生机会与申请资格明确显示规则暂不应用，且不据此排除候选、不借用旧结论排序。
- 保留原有方向切换自动应用行为，修正其 change 事件冒泡造成的错误 dirty 提示；其他修改仍必须点击查看候选。未提交模式/待核实策略的变更不改变摘要；重渲染也不读取未提交方向值。
- 红绿回归和全部专项：`python tests/ux_shell_v8.py`、`python scripts/discovery_scope_ui_check.py`、`node --test tests/discovery_scope.cjs tests/discovery_rules.cjs`、`node --check site/discovery.js`、`git diff --check` 均通过。
- 此补丁仅更改 site/discovery.js、tests/ux_shell_v8.py 与本报告，无 build/commit。

## 缓存升级修复与测试脚本整理（08:56）

- 修复原因分开：shell测试包含错误重复urllib.parse导入及重复的旧测试尾段，分别导致ImportError与Playwright回调参数错误；已删除重复部分，保留完整新断言。此前集成ImportError日志在 cache/ux_v8/integration/shell_v8.log，修后完整专项日志为 cache/ux_v8/shell/shell-final-green.log。
- 全部页面模板的CSS/JS URL统一添加 `?v=20261015-8`，包含 data/admissions-data/core、workflow/desk/discovery、compare-data，以及index/discovery动态加载search。详情页保留 `../ui.css` 相对路径。官网图片URL不变。
- 新增 `python tests/ux_cache_upgrade_v8.py`：同一浏览器context先缓存长有效期旧JS/CSS，再读取新模板；修复前DISCOVERY_READY超时，修复后新版卡片与CSS、动态search/compare数据加载通过。未启用路由拦截（避免Playwright禁用HTTP缓存），临时本地HTTP服务与mock私人条件，不修改后端或private。
- 缓存专项同时检查全部模板script版本一致；红绿日志为 cache-upgrade-red.log/cache-upgrade-green.log，实际请求记录cache-upgrade-requests.json，截图cache-upgrade-390.png。
- `python tests/ux_shell_v8.py`（含file模式）与 `python scripts/discovery_scope_ui_check.py` 复跑通过。
- 后续发布如任一静态资源内容变更，应一起递增全部模板与动态加载器的版本值并重建全部页面，再运行缓存升级回归；该版本标记用于避免旧页面升级时混用旧CSS/JS，不替代源数据版本管理。
- 本agent仍未build/commit，交integrator重建。

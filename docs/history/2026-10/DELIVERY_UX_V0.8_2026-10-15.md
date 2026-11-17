# 用户体验与基础流程 v0.8 交付（2026-10-15）

基线：`594fd3fdc`，分支 `codex/reliable-maintenance`。本轮围绕找导师、核对要求、准备联系及跟进优化界面与基本流程；不改公开数据、后端或私人 schema。

## 用户问题与结果

- 手机导航和搜索操作过深：四个主入口直接可见，更多工具按需展开；研究关键词与查看候选前置，详细筛选折叠；候选显示已有研究方向、未知条件及已应用范围，可直接加入对比。
- 学校要求与通知信息过长、往返丢范围：当前目标与下一步先于政策正文，目录和来源诊断按需展开；年度、学位、渠道、普通/专项与专业项目在跨页导航保留，来源失败仍直接可见。
- 项目材料与目标关联易丢、提醒必须依附回复：从目标解析真实所属项目，连续新增提醒继承当前项目；材料/沟通/提醒分区，联系准备支持独立提醒及完成/重开。root根据手机3331px长页截图要求再次调整，最终联系准备分为写邮件、下一步、回复、历史四面板，目标/项目/阶段保持可见，背景折叠；默认写邮件不再被其他表单推后。
- 未保存输入易丢失：切换目标、分区及离开页面时提示，取消保留输入；保存失败在操作处反馈并保留内容。
- 比较和详情语义混淆：官网明确研究方向与自动检索标签分开；缺字段显示暂未收录，旧跟进表单折叠并说明独立存储。

实现与模块测试见 `UX_SHELL_V0.8_2026-10-15.md`、`UX_WORKFLOW_V0.8_2026-10-15.md`、`UX_POLICY_V0.8_2026-10-15.md`；范围与情境见 `UX_RELEASE_PLAN_2026-10-15.md`。

## 集成验证

真实命令、退出码和日志保存在 `cache/ux_v8/integration/`；最终资源版本补丁后重新构建并复测所有受影响UI。

| 检查 | 实际结果 |
| --- | --- |
| `python -X utf8 scripts/build_site.py` | 最终exit 0；6527教师、37校、51院系 |
| `python -X utf8 -m pytest -q` | 122 passed，3项现有依赖弃用警告；缓存补丁只改前端资源引用，未重复后端测试 |
| 四Node：discovery_rules/admissions_rules/checklist_rules/discovery_scope | `node --test` exit 0，12 tests passed |
| 原八组UI | ui_check、application_ui_check、contact_ui_check、discovery_ui_check、admissions_ui_check、coverage_ui_check、checklist_ui_check、discovery_scope_ui_check，最终均exit 0 |
| 新三组UI | `tests/ux_shell_v8.py`、`scripts/workflow_v8_ui_check.py`、`scripts/ux_policy_ui_check.py`，最终均exit 0；加上原八组共11组 |
| 额外缓存升级回归 | `tests/ux_cache_upgrade_v8.py` exit 0；同一浏览器context缓存旧JS/CSS后升级，含动态search/compare载荷；独立于上述11组UI |
| `python -X utf8 scripts/preflight.py` | 最终exit 1；恰五组11项已知缺口，schema/字段卫生/站点一致性无新增错误 |
| 只读实际站点 | 18768服务复用PID12004；五页各1440/390共10张截图，HTTP200且无document横向溢出；页面/API只读 |
| 数据保护 | 6663个受保护文件SHA256一致；无新增私人记录，公开数据/后端/配置无diff，四份公共载荷字节不变 |

独立复核发现的三项P2（政策范围/来源呈现两项、已应用筛选摘要一项）已由owner修复并复审闭环。root看过四面板及实际移动端页面截图，最终复核记录为 `cache/ux_v8/review/final-review.md`。

集成曾发现shell测试错误重复import；owner整理重复测试段并修复，失败原日志保留，最终 `shell_v8_final` 成功。Node首轮子命令exit0，但日志包装器因Windows GBK打印符号报错；仅修cache包装器UTF8输出，实际测试结果不受影响。discovery UI日志保留浏览器跳转断开连接的WinError10054，页面断言与测试exit0；临时索引损坏恢复测试的HTTP500是预期注入。

root在长期打开的IAB发现HTML与旧CSS/JS混用；HTTP资源与磁盘哈希一致，因此全部模板及动态加载器统一增加 `?v=20261015-8`，并用同浏览器缓存回归验证，不要求用户手动清缓存。root在原IAB同一标签页reload后已看到新版研究方向、比较按钮、折叠出处和完整规则摘要，实际升级验收闭环；独立复审也通过file模式、动态加载和详情相对路径检查。后续静态资源内容改动须统一递增版本并重建、运行此回归。

## 视觉证据

模块前后截图保存在缓存，不进入提交：

- 发现页前：`cache/ux_v8/shell/discovery-390.png`；后：`cache/ux_v8/integration/actual-discovery-390.png`及`actual-discovery-1440.png`。
- 联系准备前：`cache/ux_v8/workflow/prepare-mobile.png`；四面板后：`cache/ux_v8/workflow/after/prepare-mobile-viewport.png`及`prepare-desktop-viewport.png`。后者使用临时目标记录，真实私人数据未写入。
- 学校要求前：`cache/ux_v8/policy/admissions-target-390.png`；后：`cache/ux_v8/policy/after/admissions-target-390-viewport.png`，完整目标由临时渲染验证。
- 实际站点最终截图：`cache/ux_v8/integration/actual-{discovery,admissions,notices,desk,applications}-{1440,390}.png`；这是当前生成站点只读默认视图，实际联系表单的受控记录流程由上述临时UI测试验证。

## 数据、隐私与限制

公开库仍为6527条教师、37校、51个名单院系；政策13条、来源14条、检查14条。五组issues中的11项已知采集缺口继续保留；preflight实际退出1，只报告这些缺口；schema、字段卫生与站点载荷一致性没有新增错误。具体为华科网安周嘉熙/周轲2项，东南黄伟解析及名单数量差异2项，武大赵星宇1项，华科韩守东/邹旭2项，中南姜霞/覃爱娜/汤嘉伟/苏丹4项；均沿用0.7事实和状态，不以改状态消除。

测试使用临时私人目录或受控mock；不写真实私人记录、不自动采集、不真实发信。最终构建使6527份详情HTML及8个入口HTML重新生成；build逻辑未变，变更来自冻结模板。6663个受保护文件SHA256前后一致，包括公开数据、原私人文件、来源及四份公共载荷；后端/站点配置无diff。最终资源版本补丁后已再次核对一致。原11份未跟踪sources、cache、私人材料及备份不暂存。

本轮验证本地界面和受控流程行为；真实邮件客户端兼容性、个人资格、招生事实和申请效果仍需独立核验。专项/专业范围的私人核验保存限制继续保留。

## 提交范围

产品负责人复核最终差异与保护审计后，本版按清单本地提交，不推送。6571个文件包括6527份详情HTML、8个入口HTML及36份源码/模板/测试/文档；详情变更来自公共导航、资源版本和详情模板呈现调整，原始记录与公共载荷没有变化。`git diff --cached --check`通过；原11份sources仍未跟踪，cache/私人材料/备份/数据/后端不进入提交。提交标识以本地git log为准。

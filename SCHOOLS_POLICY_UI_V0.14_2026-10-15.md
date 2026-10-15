# 学校筛选与政策时效展示 v0.14

本模块对应用户反馈：学校多选不便、默认总展示同一学校、过期政策挤占申请入口。范围仅为展示和筛选行为；未修改公开政策/导师数据、私人文件，未构建或提交。

## 已完成

- 学校筛选放在默认条件内，提供名称/学校代码搜索、可点击的 checkbox、已选学校移除 chips、清空和已选数量。无需 Ctrl/Command，多选可用鼠标、触屏和键盘 Space。
- 搜索仅收窄学校选项，不改变已选学校，不标记候选条件 dirty；选择、取消、清空标记 dirty，点击“查看候选”后生效。
- 原 `intent-schools` select 保留为隐藏兼容状态，由新控件同步；旧私人筛选保存/备份格式不变。
- 临时学校/院系范围仍独立于私人条件。用户未修改学校时清除范围恢复原条件；修改过时保留新选择。专项/专业核验保护不变。
- 默认候选按可解释的资料完整度分组：明确研究原文 > 简介 > 无研究文字，其后依次为公开邮箱、已记录职称、导师资格、研究文字来源及日期。未知招生机会/个人资格不作为完整度缺失。
- 同组用会话 seed 与 mentor ID 的散列排序。分页、重新应用和同会话刷新保持稳定；原数据文件顺序不再决定首屏。不同会话可改变同组顺序。
- 有关键词、学位资格、年度/渠道、必须条件或有效人工核验时，保留原匹配 score/unknown 优先级，同分再参考完整度及随机值。
- 默认显示简短排序说明，详细定义放在已有折叠说明；明确资料有日期不等于本轮已经刷新，不表示招生名额或录取概率。
- 政策列表先按用户选定的目标过滤，再依次展示：有尚未过去的已登记截止时间、截止未完整整理、已登记截止均已过。仅 `deadline` 事件决定分组，复用 `AdmissionsRules.eventState`，今日 date-only 不算已过。各组按入学年度/人工核对日期递减，不推断报名正在开放。
- 政策卡同时显示官方发布、最近成功回源、摘要人工核对。回源取 review_hashes 所引用来源的有效 last_success 最早日期；最近检查失败保留警示，缺失/无效/未来日期明确异常，绝不把 last_attempt 当更新时间。

## 文件

- `site/discovery-core.js`：完整度、确定 seed 排序纯函数。
- `site/discovery.js`：学校 picker 行为、会话排序、简短解释。
- `site/templates/discovery.html.j2`：可搜索 checkbox 和 chips、响应式样式、v14缓存版本。
- `site/admissions.js`：政策截止分组与三类日期。
- `tests/discovery_ranking_v14.cjs`：确定性、不同seed、完整度优先、条件优先、未知项场景。
- `scripts/schools_policy_v14_ui_check.py`：全部使用临时站点/私人目录的用户流程验证。

## 验证

2026-10-15 最终执行：

- `node tests/discovery_ranking_v14.cjs`：9 组场景通过。
- `node tests/discovery_rules.cjs`：通过。
- `node tests/discovery_scope.cjs`：3 项通过。
- `python scripts/schools_policy_v14_ui_check.py`：通过。覆盖鼠标及键盘选择、搜索不丢选择、chip取消、清空、dirty/apply、保存/加载/备份恢复、临时范围原条件恢复/新选择保留、专项保护、66候选稳定排序/40条分页不重复、政策三组/今日date-only/非deadline不误判、最早成功来源日期/异常日期/缺失检查/失败回源不冒充今日更新，1440/390截图无整页横溢。
- `python scripts/cards_v10_ui_check.py`：通过。
- `python scripts/discovery_scope_ui_check.py`：通过。
- `python scripts/discovery_v9_ui_check.py`：通过。

证据：`cache/ux_v14/schools-policy/`，包括 schools/policy 的1440/390完整页与viewport截图。已查看390学校选择和政策卡截图。

## 集成注意

旧 `public_flow_v13_ui_check.py` 第67/69行直接操作可见原生 select。该select如今只保存兼容状态；应改为真实学校 checkbox 操作并保留原scope断言，不能用 force 操作隐藏select充当新UI验收。

导师库未全量回源，本模块不将旧导师记录日期改为今天；新政策数据与回源记录由数据负责人另行接入，所有缺口仍依证据保留。

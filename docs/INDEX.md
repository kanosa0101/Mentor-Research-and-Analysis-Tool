# 文档索引：运行v1.9与2026-11-15整改基线

## 当前产品基线（先读）

本轮先做文档和只读审计，尚未实施或部署整改。不再把历史版本计划作为当前任务单。

- [项目地图：页面、数据、API、来源与运行边界](../PROJECT_MAP.md)
- [现状审计：问题原因、18条内容去向、导师字段质量](PRODUCT_AUDIT_2026-11-15.md)
- [产品计划：目标、范围与优先顺序](../PRODUCT_PLAN.md)
- [需求基线：内容、筛选、UI与保护约束](../REQUIREMENTS.md)
- [用户用况：正常任务、异常路径与验收](USE_CASES.md)
- [内容与来源规则：院校活动、导师招募、招生通知](CONTENT_RULES.md)
- [UI目标：统一卡片、有效筛选与信息层次](UI_GUIDELINES.md)
- [四阶段实施计划及进度](../IMPLEMENTATION_PLAN.md)
- [逐条来源审核](audits/2026-11-15/opportunity-audit.md)、[导师字段审计](audits/2026-11-15/discovery-audit.md)、[系统盘点](audits/2026-11-15/system-map.md)

运行说明与交付记录继续描述v1.9现状；本页的UI、需求和计划描述待实施目标，两者不能混用。旧通用计划和规范已保存在[整改前文档归档](history/pre-ux-reset-20261115/SHA256.json)，原字节SHA清单可核对。

## v1.9运行说明与历史交付事实

- [README：启动与入口](../README.md)
- [使用手册：申请流程、公共资料更新、私人备份与回滚](../USER_GUIDE.md)
- [新需求与现有运行版差距](../REQUIREMENTS.md)
- [当前架构](../ARCHITECTURE.md)
- [v1.9当时采用的页面规范（归档，已被新目标替代）](history/pre-ux-reset-20261115/docs/UI_GUIDELINES.md)
- [自动核验、来源准入与维护提醒](AUTOMATIC_REVIEW.md)
- [维护交接](../HANDOVER.md)
- [v1.9 交付记录：运行包、验证及部署实际状态](../deploy/DELIVERY_V1.9_2026-11-15.md)

默认入口为申请导航：公开 HTTPS 8443、本机应用 8000。本机核验工作台单独使用 18769；不开放公网审核写接口。最新交付记录由本版发布流程更新，链接存在不代表待验证或待部署事项已经完成。

v1.9运行版采用学校要求摘要与折叠、导师常用筛选前置及自然高度卡片。这是旧版实现事实，用户已指出其体验问题，自然高度等规则不再是后续目标。操作方式见运行版手册，当时规范见上方归档。v1.8的受限自动发布、辅助建议、来源准入与审核提醒见自动核验说明；导师分页和私人范围边界见架构/交接。新的内容分类、筛选和等高卡片以本页顶部的整改基线为准，尚未实施。

v1.7 的 2026-11-15 [历史快照](history/pre-v1.8/DATA_SNAPSHOT.json)记录 18 条机会（明确日期开放 1、月份窗口 1、持续招募 6、尚未开始 1、待复核 1、已结束 8）及 61 个配置监测来源。本版实际数量见[数据快照](DATA_SNAPSHOT.json)，验证与部署见 v1.9 交付记录；历史数字不代替本版线上验收。

## 保留的版本记录

- [v1.8 交付](../deploy/DELIVERY_V1.8_2026-11-15.md)
- [v1.8 数据快照原件](history/pre-v1.9/DATA_SNAPSHOT.json)

- [v1.7 交付](../deploy/DELIVERY_V1.7_2026-11-15.md)
- [v1.7 数据快照原件](history/pre-v1.8/DATA_SNAPSHOT.json)

- [v1.6 交付](../deploy/DELIVERY_V1.6_2026-11-15.md)
- [v1.5 交付](../deploy/DELIVERY_V1.5_2026-11-15.md)

- [v1.4 交付](../deploy/DELIVERY_V1.4_2026-11-15.md)
- [v1.3 交付](../deploy/DELIVERY_V1.3_2026-11-15.md)
- [v1.0 版本说明](../RELEASE_NOTES.md)
- [v1.0 验收](../RELEASE_ACCEPTANCE.md)
- [本版数据快照与分层缺口](DATA_SNAPSHOT.json)
- [v1.6 数据快照原件](history/pre-v1.7/DATA_SNAPSHOT.json)
- [v1.5 数据快照原件](history/pre-v1.6/DATA_SNAPSHOT.json)
- [v1.0 数据快照原件](history/pre-v1.5/DATA_SNAPSHOT.json)
- 更早调研与交付索引保留在源码目录 `docs/HISTORY.md`，不随运行包分发。

历史文档中的数量、测试、端口、推送能力和停止扩充说明只描述当时状态，不作为 v1.9 的现状或完成证明。

## 改版前原文

本次整理前的 v1.8 六份文档及数据快照按原字节保存在 `docs/history/pre-v1.9/`，附 [SHA-256 清单](history/pre-v1.9/SHA256.json)：

- [旧 README](history/pre-v1.9/README.md)
- [旧使用手册](history/pre-v1.9/USER_GUIDE.md)
- [旧架构](history/pre-v1.9/ARCHITECTURE.md)
- [旧需求基线](history/pre-v1.9/REQUIREMENTS.md)
- [旧交接说明](history/pre-v1.9/HANDOVER.md)
- [旧文档索引](history/pre-v1.9/DOCS_INDEX.md)

v1.7 原文仍在 `docs/history/pre-v1.8/`；v1.6 原文仍在 `docs/history/pre-v1.7/`；v1.5 原文仍在 `docs/history/pre-v1.6/`，其整理前文档在 `docs/history/pre-v1.5/`。更早的四份主文档原文仍在 `docs/history/pre-v1/`。维护历史和取证缓存通常不进入运行包；交付包实际内容以发布清单为准。

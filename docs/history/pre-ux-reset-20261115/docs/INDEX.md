# 文档索引 · v1.9.0

## 当前使用与维护

- [README：启动与入口](../README.md)
- [使用手册：申请流程、公共资料更新、私人备份与回滚](../USER_GUIDE.md)
- [功能、需求与边界](../REQUIREMENTS.md)
- [当前架构](../ARCHITECTURE.md)
- [页面与交互规范：信息层级、字体、控件和响应式布局](UI_GUIDELINES.md)
- [自动核验、来源准入与维护提醒](AUTOMATIC_REVIEW.md)
- [维护交接](../HANDOVER.md)
- [v1.9 交付记录：运行包、验证及部署实际状态](../deploy/DELIVERY_V1.9_2026-11-15.md)

默认入口为申请导航：公开 HTTPS 8443、本机应用 8000。本机核验工作台单独使用 18769；不开放公网审核写接口。最新交付记录由本版发布流程更新，链接存在不代表待验证或待部署事项已经完成。

本版统一页面层级与视觉规范：学校要求先看摘要，完整规则、官方入口与覆盖记录按需展开；导师常用筛选前置，卡片按内容自然排列。操作说明见使用手册，统一标准见页面与交互规范。v1.8 增加的受限自动发布、人工阻断、仅辅助建议、来源准入与审核提醒见自动核验说明；既有持续招募、月份截止、申请对象限制、DOCX 附件证据与变更降级见使用手册和架构；导师首次 20 位服务端分页、私人范围回退及维护来源模式见维护交接。具体机会数量和部署结果只引用本版最终交付记录。

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

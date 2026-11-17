# 申请工作台实施计划（2026-10-14）

用户已批准 OPEN_SOURCE_IMPLEMENTATION_REVIEW_2026-10-14.md 的调整后范围。本批只实现申请项目、材料关联、沟通历史、多个提醒，沿用当前 codex/reliable-maintenance 分支及本地 YAML 服务。采用 writing-plans 的任务拆分与执行检查，当前工作区含既有私人缓存，保留原位且所有测试使用临时存储。

## 设计与范围

新私人文件 data/workflow.yaml 与 outreach.yaml 独立：projects、materials、communications、reminders 四类稳定 ID 记录。申请年度可未知；导师关联仅采用当前详情页 ID，不按姓名合并。申请状态与套磁状态独立。材料仅索引用户指定文件或目录的路径、大小、修改时间及缺失状态，不上传、不读取正文、不猜导师；重扫保留人工关联。沟通采用追加事件（草稿/发送/回复/备注），不自动修改套磁状态。提醒可独立完成、修改日期，必须关联项目或导师。现有单下一步不自动迁移。

通过 /api/workflow 系列路由写入，复用本地 Host/Origin、JSON 校验、锁和原子替换。独立备份恢复包含完整索引和关联，不包含原文件；恢复前校验并留旧副本。私人记录不进入静态生成或 Git。新增 applications.html + workflow.js，导师页与看板提供入口，file:// 显示服务提示禁用写入。

## 执行与验收

- [x] tests/test_applications.py 先失败：跨年度关联、未知 ID/非法日期拒绝、材料重扫及缺失、沟通追加不覆盖、独立提醒、备份恢复/异常不写入、同源限制。
- [x] crawler/workflow_util.py 实现上述模型、校验、材料元数据扫描；scripts/serve.py 接入独立 API 和 --workflow。
- [x] site/templates/applications.html.j2 + site/workflow.js，实现创建/编辑项目、材料登记/扫描/关联、追加沟通、多个提醒完成与修改、索引备份恢复和错误提示。
- [x] build_site.py 加入空公共工作台页面，既有模板仅加入导航链接；.gitignore 忽略新私人文件。
- [x] scripts/application_ui_check.py 用临时 API、材料目录测试桌面闭环、刷新持久化、手机布局、file:// 提示。
- [x] 完整 unittest、preflight、现有 UI 与新 UI，核对原公开/私人数据哈希；独立代码审查后修复实质问题。
- [x] 更新 README、DELIVERY_2026-10-14.md，记录已验证/未验证、开源设计借鉴与保留边界，明确备份不含材料文件。

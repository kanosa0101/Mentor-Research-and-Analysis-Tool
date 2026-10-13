# 维护与申请工作流实施计划（2026-10-13）

依据已确认的 PROJECT_RESEARCH_2026-10-13.md，按 executing-plans 在当前会话逐项执行。用户已授权自行推进，沿用公开 YAML / 静态站与私人本地服务边界。使用 codex/reliable-maintenance 分支，保留当前目录的缓存和私人文件。没有新增框架或迁移数据库。

## A：维护基线

- [x] tests/test_maintenance.py：先复现缓存日期、WP 刷新、CDP 降级刷新、问题复发、人工标签丢失、preflight 错误退出。
- [x] crawler/fetch.py：刷新作用域覆盖钩子的辅助请求；普通缓存调用不变。scripts/crawl.py：解析与回源日期分离，人工字段保护，名单失败不作为空名单。
- [x] crawler/store.py / model.py：复发问题重新打开、保留复验历史；新增解析/回源日期。scripts/tag_facets.py：保留非 computed 标签。
- [x] scripts/serve.py / ui_check.py：测试独立临时数据路径与服务，不修改真实 outreach；失败也关闭服务。preflight 返回可靠退出码。
- [x] requirements.txt 与文档：列出运行依赖、验证命令和日期含义。
- [x] 验证：python -m unittest discover -s tests -v；python scripts/preflight.py；隔离 UI 检查。

## B：申请工作流

- [x] tests/test_workflow.py：验证未知导师/错误字段拒绝、下一步日期持久化、备份恢复、页面精简与搜索材料覆盖、HTML 转义。
- [x] build_site.py / templates：共享精简 data.js，保留完整研究材料搜索、显式未知方向、历史来源日期。保留 file:// 浏览。
- [x] serve.py / detail / board：私人标签、下一步、日期；意向作为短名单；导出与先校验后恢复的备份，恢复前自动保留旧数据。
- [x] 验证：单元及隔离 API、浏览器桌面/手机与 file://；数据源文件和私人文件前后哈希一致；测量载荷。

## C–E：小样本后续（按实际验证状态记录）

- [x] 官方通知监测试验：三个院系当前栏目、37 条候选、缓存复跑 0 变化，页面已接入；资格/截止日期人工验收仍待完成。
- [ ] 短名单论文试验：先固定身份再获取论文，不凭姓名自动绑人；无真实意向名单时保留准备状态。
- [x] AI 本地管线修复：dry-run、mock 隔离、输出结构和逐字摘录约束已验证；真实 API 质量及信件尚未验收。

每批补失败测试后修复；不提交或推送私人文件。最终记录已验证项、待真实样本项和具体限制。

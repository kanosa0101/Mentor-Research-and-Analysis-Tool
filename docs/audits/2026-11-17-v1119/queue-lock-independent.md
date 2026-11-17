# 共享审核队列锁补丁独立审查

基于 v1.11.9 的 `06e5ff600d75360de9639914742a850380d5b954` 审查提交前冻结源码。使用临时目录、独立子进程、模拟官方原文和模拟模型结论复测。独立审查未调用真实模型或写入生产。

| 验证项 | 独立复测结果 |
| --- | --- |
| 共享锁等待与释放 | 子进程先持有审核队列锁，释放后自动审核在本轮继续。持锁进程异常退出时锁可以再次获取。目录锁及整轮单实例锁保留立即返回的行为。 |
| 严格等待截止 | 让子进程持锁约 1 秒，等待上限设为 0.15 秒，再模拟调度延迟到约 1.15 秒才唤醒。补丁前，等待者会在截止后取得锁。修复后返回队列忙，未进入临界区，随后正常取锁成功。该 P2 已关闭。 |
| 超时与接续 | 在预检前及模拟 AI 已完成后分别令队列锁超时。自动审核报告 `review_queue_busy`，现有业务字段、摘录和人工编辑未改，也未生成公开目录。锁释放后，下轮可重新处理。监测同步、每小时续核和来源恢复均保留延期状态，来源恢复继续使用原父栏目游标。 |
| 发布版本检查 | 自动审核完成第一次草稿比较后，在正式发布进入提交锁前插入人工编辑。发布入口再次按完整草稿版本比较，拒绝写入目录并保留人工内容。 |
| 目录写入失败 | 在原子替换目录之前模拟文件写入失败。结果为 `local_io_error` 并安排重试，公开目录未生成，草稿业务字段和摘录保持原值。成功发布路径由目录、审计记录和队列状态回归覆盖。 |

监测同步由 `ExecStartPost` 调用，队列忙会输出 `deferred` 和 `review_queue_busy`，进程退出码为 1。实现代理从生产同一次 invocation 核实 `ExecStartPost` 的状态为 1、`ignore_errors=no`，服务结果仍为 `success`。独立核对 systemd v255 源码，子进程退出检查在区分主进程及控制进程前应用 `success_status`。原先对退出码会使监测单元失败的疑问已撤回。[systemd v255 源码](https://github.com/systemd/systemd/blob/v255/src/core/service.c#L3365-L3385)

10 秒是每次获取共享审核队列锁的等待上限，一轮任务可能获取该锁多次。若 AI 已成功返回但本轮因共享锁超时未能保存结果，下一轮可能重新核验并计费。现有日预算仍然适用。

## 最终回归

冻结源码的 9 个定向测试文件共 225 项通过。唯一提示为当前环境的 `pytest-asyncio` 弃用提示，`git diff --check` 通过。

```powershell
python -m pytest -q -p no:cacheprovider tests/test_content_autonomy_v1119.py tests/test_automatic_review_v18.py tests/test_complete_evidence_v1116.py tests/test_opportunity_recovery_v1115.py tests/test_opportunity_review.py tests/test_review_pipeline_v18.py tests/test_public_maintenance.py tests/test_activity_publish_version_v1118.py tests/test_review_evidence_state_v1117.py
```

已复现的严格截止问题通过复测，未发现遗留 P1/P2。独立审查结论适用于上述冻结源码。

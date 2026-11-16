# 新政策审核进入维护闭环

新政策入库任务的 `cache/policy_intake/state.json` 已纳入现有 `quality_status` 汇总。维护工作台通过原 `pipeline_metrics → quality-alerts.json` 链路展示，无新增学生页面、账号流程或公开写接口。

## 状态与时限

- `manual_required`、`retry`、`budget_wait`、`eligible` 均保留活跃待办；`published` 退出新政策待办，后续由政策续核流程接管。
- 处理时限为 `pending_since` 后 24 小时；旧记录只在没有该字段时沿用 `first_seen`。重试、下一次预算恢复时间和正文 SHA 变化不会重置连续等待时钟或提醒指纹。无有效起点时明确显示状态待检查，不伪造超时。
- 显示首次待处理起点、维护处理时限、最近尝试、下次检查、具体原因、下一步动作、官方公告及来源栏目链接。维护时限不是学生的申请截止。
- 列表只输出这些元数据，不输出 `proposed_policy`、完整附件证据、AI 原始输出或私有配置。
- `quality-alerts.active` 的新类别为 `policy_intake`，计数为 `summary.new_policies`。现有维护者推送消费该列表；是否实际送达仍取决于订阅与推送服务。本轮没有实际发送外部推送。

## 验收

`tests/test_quality_status.py`、`tests/test_policy_intake_dashboard_v1116.py`、`tests/test_maintenance_push_v18.py`、`tests/test_review_dashboard.py` 合计 **37 passed**，12.88 秒；1 条既有 pytest-asyncio 弃用提示。日志：`cache/v1116/policy-dashboard-tests.log`。

新增真实 Chromium 桌面 1440×1000 与手机 390×844 验收，检查预算等待、人工核验、核验通过待发布、原因筛选、来源链接、时限与下次检查；没有页面错误、横向溢出或写请求。截图已目视检查：

- `cache/v1116/maintainer-policy-ui/policy-wait-1440.png`
- `cache/v1116/maintainer-policy-ui/policy-wait-390.png`

原维护工作台完整 UI 验收脚本也通过：原因筛选、30/60/66 条分批展示、轮询保持筛选、并发编辑保护、维护订阅隔离与移动布局。结果：`cache/v1116/review-ui-regression/result.json`。该脚本使用临时公开数据与模拟通知，不代表真实浏览器已收到线上推送。

前端脚本缓存版本为 `review.js?v=20261116-policyqueue1`。以上为部署前隔离验收，未操作生产队列、账号、AI 额度或服务。

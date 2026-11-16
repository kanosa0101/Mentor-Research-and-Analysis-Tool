# 前端与性能改动独立审查

## 结论

审查了首屏内联脚本及样式、机会页 API 首取与静态降级、招生条件分条、自动核验标签与无订阅维护提示。未发现发布状态或匿名保存门禁被放宽。发现并修复 1 项 P2：机会 API 挂起时，新的首取逻辑会一直停在加载中，无法启动静态降级。

最小修复在 `site/opportunities.js`：API 请求及 JSON 正文读取共 8 秒上限，使用 AbortController 中止；静态脚本加载另限 8 秒，失败后移除脚本并恢复重新检查按钮。API 失败后的静态记录标记为来源不可用，不声称报名开放；没有成功连接时不开放保存。

## 证据

- `tests/test_frontend_review_v1116.py` 实际 Chromium 覆盖 HTTP 503、API 持续挂起、静态脚本持续挂起、手动重试恢复。过期/不可用快照不显示“报名窗口内”，未连接时按钮禁用，恢复到匿名 API 后只出现登录入口，未发出写请求。
- 条件分条在真实 DOM 中逐字拼接还原原限制，包括“仅限”“不得低于”“非全日制不接受”和模拟 HTML 标签；未生成 script 节点或执行正文内容。
- 首屏入口、降级与内联 escaping 相关 **13 项通过**，26.89 秒。日志：`cache/v1116/frontend-independent-tests.log`。
- 内联顺序：account-session / cloud-library 在 head 定义，CloudLibrary 等 DOMContentLoaded 后才读取 core；start 的 core 在 plan-transfer/start 前；discovery 的异步请求完成前已执行其 core/library 定义。现有大小写混合 `</script>` 转义回归通过。
- 招生摘要只按中文句号、分号拆分并 trim 分隔空白，完整限制仍保留；详情和官方证据没有删减。自动/人工标签依据 `review_method`，不改变事实门禁。
- 无订阅提醒由维护者投递汇总明确显示，不把服务启用或 sent=0 当成有人收到。

## 公网性能验收脚本

`scripts/public_performance_v1116.py` 默认执行 3 轮，每轮 6 个样本，共 18 个：新 Chromium 冷开申请导航，同会话依次找导师、学校要求、院校活动、返回申请导航；另起新 Chromium 冷开找导师。

```powershell
python scripts/public_performance_v1116.py --rounds 3 --output cache/v1116/public-performance
```

手机可另指定 `--width 390 --height 844`。默认目标为 `https://8.213.137.82:8443`，仅匿名 GET/HEAD。没有账号注册、申请保存或真实推送操作。脚本不拦截正常请求，保留浏览器 HTTP 缓存；新进程隔离浏览器连接与缓存，未清除操作系统 DNS 缓存。

每次样本立即落盘，保留失败，不只汇报最好成绩。`result.json` 包含完整导航和资源 PerformanceTiming、CDP 响应连接是否复用/协议/连接ID/公开IP及 timing、DNS/连接/TLS/请求到首字节/正文传输拆分、所有资源传输大小、缓存命中、页面错误、HTTP 错误、完整导师回退是否被下载，以及首轮截图。TLS 包含在连接时长内；请求到首字节仍包含网络等待，不能直接认定为后端 CPU 时间。

fetch/XHR/表单/beacon 写请求会在浏览器内被阻止；同时观察实际请求，结果中不保存请求头、Cookie、CSRF 或响应正文。脚本遇验收失败返回非零退出码。

测量工具以真实临时 HTTP 服务和 Chromium 自验 **2 项通过**，12.04 秒：保留全部 6 样本、正常缓存复用与连接分段，模拟 POST 在发出前被阻止、结果失败且没有服务端写请求；模拟 CSRF 值未进入报告。日志：`cache/v1116/performance-script-tests.log`。

本报告未执行新版本公网测量或部署；上述命令供部署后验收，不能将开发验证结果表述为线上性能提升。

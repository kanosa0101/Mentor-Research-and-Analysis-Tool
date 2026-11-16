# v1.11.5 验收证据

2026-11-16，在线版本已部署。最终实现源码为 `bf985c0a302bc57fbc5c320462327339a2ab8ada`；主来源修复包为 `e240db8214201521a36f83a6472f81b2cec5150d`。文档提交单独登记。内容缺口与未解决问题没有通过降低门禁清空。

| 范围 | 实测结果 | 证据 |
| --- | --- | --- |
| 最终完整Python回归 | 904通过，3条第三方弃用提示 | [日志](pytest.log) |
| Node规则 | 25通过，0失败 | [日志](node.log) |
| 数据检查 | 模型及格式未新增错误；35组264条公开资料问题仍阻断全绿 | [preflight](preflight.log) |
| 积压真实回源 | 419逐项检查，155恢复、264保留；665次真实HTTP | [逐项台账](../../audits/2026-11-16-v1115/backlog.json) |
| AI服务账号 | 2次真实请求10.230秒/6.193秒，逐字建议有效，无发布，预算6→8/10 | [服务验收](ai-service-acceptance.json) |
| 原生产阻挡处理 | root诊断导致账本owner错误；仅修复权限并提前2项重试，不重置额度、人工字段或队列时钟 | [操作记录](ai-permission-recovery.json) |
| 真实维护首轮 | 政策5源成功；导师40项30成功10失败；问题16项8恢复8保留，阶段无程序异常 | [摘要](maintenance-first-cycle.json) |
| 真实审核编排 | 入口按预算轮转、受限准入、来源接续阶段、告警均实际执行 | [首轮](review-first-cycle.json)、[权限修复后](review-after-ai-recovery.json) |
| 原导航误入 | 2项按原文SHA分流，只改triage | [记录](triage-applied.json) |
| 来源自动扩展 | 部署时81项，部署后新增4项至85；不等于新增4个报名机会 | [具体入口](live-source-expansion.json) |
| 维护台 | 1440/390px共8项，原因筛选、折叠及30/60/66条按需显示、轮询保留编辑、无溢出 | [结果](review-ui.json)、[手机截图](review-quality-mobile.png) |
| 公网完整申请流程 | 12项通过，无脚本错误与失败请求 | [结果](result.json) |
| 初次公网异常 | 一次TLS资源失败引起初始化中断；该次不记通过 | [初次失败](initial-qa-failure.json) |
| TLS只读复验 | 12次GET和4次冷启动成功，未能复现TLS层故障 | [结果](tls-readonly-probe.json) |
| 资源故障恢复 | 正常/core首次失败/cloud首次失败，隔离和公网各3项通过，提示/重载恢复，无额外失败 | [隔离](start-load-guard.json)、[公网](public-guard.json) |
| 安装合并 | 196份公开文件、455份缓存，7,207个受保护文件一致，54份非生成源码哈希通过 | [部署](deployment-validation.json) |
| 自动历史冲突 | 456项版本绑定决议；39份历史保留78条旧新记录，人工字段不变 | [审核](merge-resolutions-audit.json)、[实际应用](stage-merge.json) |
| 部署工具检查 | 39项合并/归档边界测试通过，4项安装成功/失败回滚模拟通过 | [合并测试](stage-tests.log)、[回滚模拟](install-rollback.json) |
| 后补加载保护部署 | 独立哈希验证、服务账号重建，私有文件不变 | [部署](guard-deployment.json) |
| 生产最终快照 | 3服务/5定时器active；7,173导师、111条2027政策、9条机构活动；明确2028活动0；总待办272 | [检查](final-server-validation.json) |
| 专用账号清理 | 首次1个、复验2个账号精确清理；私有资料保留 | [首次](qa-cleanup-first.json)、[复验](qa-cleanup.json) |

真实公网流程包括注册登录、导师到申请的上下文、上传/下载、沟通与提醒保存、跨设备读取、账号隔离、退出、旧本机入口关闭、届别语义和手机布局。人工查看[账号手机截图](account-mobile.png)、[材料页](materials-desktop.png)、[沟通页](communication-desktop.png)及[资源失败提示](public-guard-core-error-mobile.png)、[恢复页面](public-guard-core-ready-mobile.png)。故障恢复场景主动中断指定资源一次，不能描述为TLS故障再次自然重现。

验证用来源与账号均按上述范围执行。浏览器推送没有真实终端投递，本轮不声称已收到通知。生产待办272包含本批剩余264与后续自动识别的8条；定时任务继续更新，静态验收快照不是长期固定数量。详见[统一交付记录](../../../deploy/DELIVERY_V1.11.5_2026-11-16.md)。

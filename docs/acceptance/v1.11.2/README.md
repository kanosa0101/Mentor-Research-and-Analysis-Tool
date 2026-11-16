# v1.11.2 体验与性能验收

- Python完整回归：689项通过，3条第三方依赖弃用警告；Node的14个规则文件通过，运行器报告23项。
- [原有账号HTTPS流程](account-https.json)：16项通过，包括跨设备、隔离、冲突提示、会话失效和材料编辑删除。
- [新增使用流程](workflow-https.json)：8项通过，包括保存项目后继续上传/沟通、上传失败保留输入、防止重复提交、多导师不擅选及按需加载准备清单。
- [公网HTTPS流程](browser-public.json)：9项通过，生产证书校验开启，无页面异常或失败请求；连续操作不需要重新选择项目和导师。
- [精简导师资源](contact-payload.json)：全部7173位导师保留，仅去除当前页面不用的字段。压缩传输量减少49.86%。
- [前后速度对比](navigation-comparison.json)，原始[优化前](navigation-before.json)/[优化后](navigation-after.json)：同一公网入口，同样的空账号、浏览器及就绪条件。每页一次清缓存加载，再做两轮页面切换；对比中的回访采用第二轮，第一轮可能仍需重新填充其他页面缓存。不将单样本墙钟时间当作稳定提速保证。
- [部署文件保护](deployment.json)、[基线账号清理](qa-baseline-cleanup.json)、[最终验收账号清理](qa-cleanup.json)。共5个明确的合成账号已清理，未操作其他账号。

已目视检查：[旧申请页](before-applications.png)、[新建申请桌面](create-desktop.png)、[手机上传](materials-mobile.png)、[公网材料](public-materials-desktop.png)。创建按钮约794px；390px手机上传按钮底部约923px，减少了此前的长距离滚动。320/390/1440px检查无横向溢出。

此次没有修改安全隔离、个人记录存储、招生事实或自动发布规则。性能变化包括数据量和请求数量的确定性下降；联系页本次冷加载时长没有下降，缓存回访约1秒，不声称全站耗时普遍改善。

[完整交付记录](../../../deploy/DELIVERY_V1.11.2_2026-11-16.md)。原始执行日志见 `cache/online-ux/`，技术验收不代替用户最终验收。

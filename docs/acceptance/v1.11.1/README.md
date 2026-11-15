# v1.11.1 在线流程验收证据

- Python：686项通过，3条第三方依赖弃用警告；日志 `cache/online-cleanup/pytest.log`。
- Node：14个规则测试文件全部通过，运行器报告23项通过；日志 `cache/online-cleanup/node.log`。
- [隔离HTTPS浏览器](browser-https.json)：16项，包括密码变更引发的异地会话失效、清空私人显示、冲突重试、材料编辑与删除。仅该隔离自签名测试环境忽略证书信任错误。
- [公网HTTPS浏览器](browser-public.json)：8项，真实证书校验；从导师卡片开始注册并建立申请、保存联系目标、上传材料与沟通记录，独立浏览器登录读取同一文件，其他账号隔离及退出撤权。最终无JS异常或失败请求。
- [文档与页面检查](document-audit.json)：14份现行文档、116个相对链接、7173个导师详情页账号脚本版本一致。
- [部署数据保护](deployment.json)、[验收账号清理](qa-cleanup.json)。仅删除本次7个明确记录的合成账号及其测试材料。

已实际查看：[材料桌面](materials-desktop.png)、[申请导航手机](start-mobile.png)、[公网账号手机](public-account-mobile.png)、[公网沟通桌面](public-communication-desktop.png)。[320px账号布局](account-320.png)纳入浏览器宽度检查。

公网验证中的非最终失败也有记录：验收脚本先遇到跳转后读取响应体失败，已去掉该观察器；另一次公共依赖未初始化，以及一次 `ERR_SSL_PROTOCOL_ERROR`。最终关闭Chromium系统代理参数后重走完整流程成功。未以单次成功宣称所有网络环境稳定，也未将未经复现的失败归结为初始化顺序问题。原始日志在 `cache/online-cleanup/public*`，未包含密码。

详细交付与保留边界见[交付记录](../../../deploy/DELIVERY_V1.11.1_2026-11-16.md)。本次技术验收不替代用户验收。

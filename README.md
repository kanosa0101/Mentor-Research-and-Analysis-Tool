# 导师库 · 申请助手

面向CS学生的在线网站：找合适的导师，核对学校和院系要求，了解院校活动，管理自己的申请、材料和联系进展。

唯一用户入口：[打开在线网站](https://8.213.137.82:8443/start.html)。产品不再提供本机版，不要求安装Python、下载运行包、启动服务或手工更新资料。

## 使用路径

1. 免登录查看[导师](https://8.213.137.82:8443/discovery.html)、[院校活动](https://8.213.137.82:8443/opportunities.html)和[学校要求](https://8.213.137.82:8443/admissions.html)，通过原始来源核对适用条件。
2. 注册/登录账号后保存收藏、关注目标和申请。账号下的记录在不同设备登录后读取。
3. 在申请中关联导师和上传材料，保存联系草稿、实际沟通记录与下一步提醒。

“准备申请”不等于已在学校报名；“保存邮件草稿”不等于已发送。官方公告、报名入口和咨询联系方式分别呈现。导师资格不等于当前有招生名额。

## 文档

- [使用手册](USER_GUIDE.md)：账号、申请、材料和跨设备使用。
- [项目地图](PROJECT_MAP.md)、[需求](REQUIREMENTS.md)、[用况](docs/USE_CASES.md)、[UI规则](docs/UI_GUIDELINES.md)。
- [在线服务决策与验收标准](docs/ONLINE_SERVICE.md)、[实施计划](IMPLEMENTATION_PLAN.md)。
- [架构](ARCHITECTURE.md)、[维护交接](HANDOVER.md)、[自动核验](docs/AUTOMATIC_REVIEW.md)。

v1.12.1 优化现有在线流程：每批4位推荐、保留跨页申请与研究兴趣上下文，并按官方来源分批补齐导师联系信息。[版本说明](RELEASE_NOTES.md)、[本版验证与部署](deploy/DELIVERY_V1.12.1_2026-11-22.md)记录实际结果。资料由服务器定时任务继续核验，版本升级不代表整库刷新，也不将2027博士政策计为2028保研机会。[前版维护与资料结果](deploy/DELIVERY_V1.11.9_2026-11-17.md)和[全部文档索引](docs/INDEX.md)分别保留证据与历史。

## 开发与运维

仓库中的Python服务、采集和构建脚本供开发维护人员使用，不是学生的安装要求。公共来源配置在 `sites/`，公共资料在 `data/`，模板在 `site/templates/`。维护核验台保持独立限制，不因开放账号而暴露到公网。部署与恢复见维护交接。

源码保留模板、脚本和公开开发基线；生成HTML、资料索引与拼接脚本由构建步骤产生，不作为手工维护的源码。使用Python 3.12与Node.js 24进行开发验证：

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python scripts/build_site.py
python -m pytest tests -q
node --test tests/*.cjs
python scripts/preflight.py --allow-open-issues
```

最后一条命令仍会拒绝结构和安全问题，只把已登记的待处理资料单独列为质量警告；去掉参数即使用严格模式。Linux CI另安装浏览器系统依赖。线上公共资料由定时任务持续更新，部署时应保留服务器的较新数据，不能用仓库开发基线覆盖。旧本机打包脚本仅保留历史测试用途，对当前在线版拒绝生成运行包。

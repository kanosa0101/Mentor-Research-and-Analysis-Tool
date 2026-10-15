# v1.0 本机版维护交接

当前版本v1.0.0，2026-10-15。用户要求停止其他扩展并整理大版本：不继续采集、扩院系或新增功能。当前入口为README、USER_GUIDE及RELEASE_ACCEPTANCE；旧计划不作为继续执行授权。

## 运行与公开数据

VERSION和release.json记录版本；scripts/build_site.py生成site。默认serve.py监听127.0.0.1:8000；启动应用.cmd优先根.venv，再选PATH的python和py。requirements.txt声明依赖，普通服务无需下载Playwright浏览器。工作区18768只是现有预览端口。停止服务前先核实际监听PID及命令，不凭旧状态文件操作。

data/professors为7173公开记录，39校59配置单位中56有名单。admissions.yaml/checks/entries分别保存政策、回源状态和入口；111政策183来源96入口、69政策310动作。notices.json为18栏目182未人工核验候选。覆盖、旧来源和7组67项质量问题见发布验收，不代表本轮已经刷新。

site/data.js、search.js、compare-data.js及7173详情来自公开记录，必须一起分发；site/templates和sites配置是重建输入。公开采集数据和私人记录不能混放。

## 私人边界与兼容

outreach.yaml为旧跟进；student.yaml、student_sop.md、letters和backups也属私人。workflow.yaml及discovery.yaml首次保存才创建。它们、材料原件、cache和sources不进入运行包。

material_task_util是工作流v4包装，旧模块接收v3投影。GET兼容不自动迁移；明确保存追加材料记录并绑定完整目标、动作/来源指纹及文件版本。恢复支持工作台1/2/3/4和筛选核验1/2，替换对应文件前保存旧备份，不是合并。材料原文件、画像/SOP和独立信件不在工作台备份内；浏览器候选localStorage也独立。

目标8字段为学校、院系、年度、学位、渠道、普通/专项、专业代码和名称。学习形式、就业方式和批次未独立建模，不能声称所有日期能自动判断适用。

## 发布维护

scripts/package_release.py在Git源码工作区通过白名单制作运行ZIP及逐文件SHA256，记录源提交，不复制真实私人文件；普通解压运行不需要Git。干净解压验证使用当前已验证Python环境，不等于全新依赖环境或所有系统都已验证。只本地交付，不推送。

资源按实际字节变化定向更新缓存查询串，不为版本号整齐强改全部脚本。重建后核实际HTTP字节。可写验收只用临时private；旧脚本可能硬编码输出，重跑时把证据重定向新目录，不覆盖冻结缓存。

旧v20有4件缓存误写未恢复，保留v0.21记录，不能写为已恢复。此前四份主文档原字节存docs/history/pre-v1；其他调研、交付和计划保留原路径，从docs/INDEX.md查阅。历史数字、v3说明、推送状态及“预检0问题”不能当本版现状。

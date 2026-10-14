# 同类开源项目源码对照与后续推进建议

调研日期：2026-10-14。目的：解释同类工作实际怎样处理材料、导师身份、申请进度与通知更新，再决定本项目下一批范围。

## 调研边界

本轮读取官方仓库的实际源码，未安装或运行这些项目。Git HTTPS 克隆失败，改用官方 raw 文件和 GitHub API；不能据此声称完成整仓审计或部署验收。可核验提交如下：

| 仓库 | 核验提交 | 本轮重点 |
| --- | --- | --- |
| BlairCode/baoyan_workbench | 2c05e088b1fca67cc29241107522f2c272674fe6 | 材料扫描、联系工作台、SQLite 表与备份 |
| wzyn20051216/postgrad-contact-manager | 08f90b5a674a892738514f56d5fa5356f6fb8a60 | Prisma 模型、导师服务、模板导入、资源健康、邮件服务 |
| Haoyu-Gu/camp-tracker | 未锁定提交；读取当日 main | 通知去重、手工截止日期、文件与申请状态 |
| emeryberger/CSrankings | 5e8a27d68310c728a182b8bb3b6437c39bce0cad | 作者名核验、机构核验、DBLP 别名生成 |

部分 workbench 文件与 contact-manager schema 首次读取的是 main；已核验仓库提交，但这不等同于逐文件内容哈希锁定。原始网页工具返回保存于 sources/open_source_2026-10-14_1.txt 至 _6.txt，其中也包含未成功读取的链接。以下结论只采用成功返回的源码。

## 1. baoyan_workbench：用材料把工作流串起来

contact_workspace 会把导师资料和相关材料汇总到同一联系人下，区分套磁信与其他文件；材料中出现但数据库未登记的人保留为待补充对象。这比单独的导师列表更接近实际使用：进入一个人，就能找到相关论文、信件和附件。[contact.py](https://github.com/BlairCode/baoyan_workbench/blob/2c05e088b1fca67cc29241107522f2c272674fe6/baoyan_app/contact.py)

材料文件仍留在本地目录，数据库记录路径、大小、修改时间、分类与关联对象。扫描先标记可能缺失，重新发现文件后解除标记；已存在的人工分类和关联优先保留，文件消失不立即删除记录。值得借鉴的是“索引原文件并维护关联”，而非把所有材料复制或抽取到数据库。[materials.py](https://github.com/BlairCode/baoyan_workbench/blob/2c05e088b1fca67cc29241107522f2c272674fe6/baoyan_app/materials.py)

它另设 programs 与 tasks，申请项目有阶段、结果等字段，任务有截止时间和状态；申请项目不完全等同于导师联系状态。[db.py](https://github.com/BlairCode/baoyan_workbench/blob/2c05e088b1fca67cc29241107522f2c272674fe6/baoyan_app/db.py)

限制：联系人合并键主要是规范化姓名，补齐字段偏向资料完整度；跨学校、跨院系的全量导师库不能沿用这个身份规则。完整度也不等于官方权威性。数据库备份函数复制 app.db，并不同时备份所有原始材料。当前本地 Python 无 cgi 模块，而其材料模块导入 cgi，直接移植还存在运行兼容性问题。[合并实现](https://github.com/BlairCode/baoyan_workbench/blob/2c05e088b1fca67cc29241107522f2c272674fe6/baoyan_app/contact.py)、[备份实现](https://github.com/BlairCode/baoyan_workbench/blob/2c05e088b1fca67cc29241107522f2c272674fe6/baoyan_app/repositories.py)

对我们的建议：保留现有公开导师 YAML，增加私人材料索引，使用稳定导师 ID 关联。文件名只能推荐关联候选，确认结果必须单独保存。

## 2. postgrad-contact-manager：把沟通、状态和提醒分别记录

Prisma 模型将 Professor、Communication、StatusLog、Reminder、Interview、Note 分开。Communication 保存主题、内容、发送及回复时间；StatusLog 保存状态变化；提醒可有多个，并有完成标记。这解决了单条备注或单个 next_action 无法容纳多次联系的问题。[schema.prisma](https://github.com/wzyn20051216/postgrad-contact-manager/blob/08f90b5a674a892738514f56d5fa5356f6fb8a60/prisma/schema.prisma)

导师列表按 userId 限定并使用 skip/take 后端分页；详情一次加载沟通、状态、提醒等关联对象。状态更新会记录历史，但检查到的方法分两次写入，不能据此声称整个流程具备原子事务保证。[professor.service.ts](https://github.com/wzyn20051216/postgrad-contact-manager/blob/08f90b5a674a892738514f56d5fa5356f6fb8a60/packages/server/src/services/professor.service.ts)

模板管理支持人工创建、上传以及本地文件夹导入，FILE_LINK 可记录原文件路径；预览保留文件缺失这一状态。材料管理可以独立于 AI 生成。检查到的 mail.service.ts 主要发送注册和重置密码验证码，不能把“有邮件服务”解读为已经实现导师套磁自动发送。[template.controller.ts](https://github.com/wzyn20051216/postgrad-contact-manager/blob/08f90b5a674a892738514f56d5fa5356f6fb8a60/packages/server/src/controllers/template.controller.ts)、[mail.service.ts](https://github.com/wzyn20051216/postgrad-contact-manager/blob/08f90b5a674a892738514f56d5fa5356f6fb8a60/packages/server/src/services/mail.service.ts)

资源健康检测先 HEAD，特定失败再 GET，保存检查时间、HTTP 状态和批次统计，并限制检查数量。可借鉴有界检查与批次报告；链接能访问仍不等于内容真实、完整或招生信息有效。[resource-health.service.ts](https://github.com/wzyn20051216/postgrad-contact-manager/blob/08f90b5a674a892738514f56d5fa5356f6fb8a60/packages/server/src/services/resource-health.service.ts)

限制：模型中 acceptingStudents 默认为 true，source 主要是单个字符串，这不满足我们的逐字段证据要求。没有招生证据时应保留未知；不能因为导入成功就认定招生。也没有必要为了单人本地工作流立即照搬其账户和完整服务架构。

对我们的建议：增加多条沟通和多条提醒，保持私人存储；需要的原子写入、恢复与校验复用现有本地服务。后端分页只有载荷和使用数据证明必要时再增加，不把浏览器切页当成减少下载量。

## 3. camp-tracker：通知发现自动化，申请判断允许人工覆盖

通知爬虫从页面锚点提取链接，用标题与 URL 的 MD5 判断是否见过，再把新条目写入记录。这个实现适合发现新链接，但同一标题、同一 URL 下正文变化不会改变该标识，不能覆盖截止时间延期等修订场景。网络异常会被捕获，最终退出路径仍可能是成功退出码；“没有新条目”和“抓取失败”需要另外区分。[monitor/crawler.py](https://github.com/Haoyu-Gu/camp-tracker/blob/main/monitor/crawler.py)

Web 工作台支持手工状态与截止日期；文件夹或文件名关键词用于推断进度，手工状态优先。导师目录中的草稿、回复材料也参与状态推断。它提供了实用的最低成本工作台，但这些文件推断应作为提示：草稿存在不能证明已发送，回复文件名也不能替代实际沟通记录。[webapp/app.py](https://github.com/Haoyu-Gu/camp-tracker/blob/main/webapp/app.py)

另一个边界是日期精度：代码部分 URL 日期规则会把月份补成月初，这可以作为排序启发式，不能作为已核实的招生截止日期。爬虫的关键词排除也反映特定申请偏好，不能无条件扩展到所有招生类别。

对我们的建议：保留当前官方通知候选模式，增加正文快照或规范化内容版本；分别记录抓取成功、无变化、解析失败。招生年度、申请类别、截止时间必须有原文证据与人工确认，通知发布日期独立保存。

## 4. CSrankings：身份核验依靠外部实体与校验流程

提交校验对照机构列表与 DBLP，要求精确作者名匹配，保留 DBLP 名称中的数字消歧后缀；无法精确确认时给出人工复查与候选提示。当前检查路径还要求 ORCID。这说明可靠论文归属首先是身份维护工作。[validate_submission.py](https://github.com/emeryberger/CSrankings/blob/5e8a27d68310c728a182b8bb3b6437c39bce0cad/util/validate_submission.py)

别名生成从 DBLP 的同一主页实体读取多个 author 名称，并建立对应关系，而非仅凭姓名相似度推断别名。[generate-aliases.py](https://github.com/emeryberger/CSrankings/blob/5e8a27d68310c728a182b8bb3b6437c39bce0cad/util/generate-aliases.py)

限制：它是特定领域的人工维护名册，覆盖目标与我们不同；一些主页或 Scholar 校验仍包含启发式和网络限制。我们可以采用实体 ID、明确证据与人工复查流程，但不能把缺少 ORCID 的导师直接排除，也不能把这套校验称为零误差消歧。

对我们的建议：导师主页 ID 与 DBLP/ORCID 候选分开，记录候选依据、确认人和时间。未确认作者的论文不能进入自动匹配结果；可以先建设候选审核工具，不必等真实 AI API。

## 5. 对当前项目推进顺序的修正

当前公开导师数据、来源日期和本地私人记录边界已有基础；联系记录仍以状态、备注、单个下一步和日期为主。主要缺口是材料、申请项目和多次沟通尚未形成关联。因此下一批应先形成一个可手工完成的申请闭环，再用 AI 减少重复劳动。

| 顺序 | 最小范围 | 验收标准 |
| --- | --- | --- |
| 1 | 私人申请项目：院校、院系、申请类型、年度，关联导师与通知 | 同一导师可关联不同年度项目；联系状态与申请状态互不覆盖；未知年度可保存 |
| 2 | 材料索引：原路径、类型、大小、修改时间、人工关联、缺失标记 | 重扫保留关联；重名导师不自动合并；文件消失可见；索引备份明确不含原文件 |
| 3 | 沟通历史与多个提醒 | 草稿、已发送、已回复分开；历史追加保留；完成一个提醒不覆盖其他提醒 |
| 4 | 通知确认与内容修订 | 旧 URL 正文修改能发现；抓取失败不显示成无更新；截止时间可追溯到原文 |
| 5 | 作者身份候选审核与短名单论文 | 同名候选保留；仅确认实体进入论文归属；可人工否决和纠正 |
| 6 | 基于已确认资料的辅助草稿 | 手工写作可用；生成内容链接依据并人工审核；实际 API 质量单独验收 |

这里不要求一次完成所有模块，也不要求立即迁移数据库。最小实现可沿用当前 YAML/本地服务，对多表查询和写入一致性有实际压力后再评估 SQLite。

这一排序修正了上轮把后续重点集中到短名单论文和 AI 的安排：材料关联、沟通历史、身份候选审核都可以先推进；用户资料完整度影响个性化文书生成，不应阻塞这些基础工具。检查到的源码没有为我们证明“通知自动识别即可当招生事实”或“有模板即可自动可靠套磁”，这些环节仍需独立验证。

## 6. 本轮交付状态

本轮新增调研报告和 sources 中的网页返回记录，没有修改业务代码、公开导师数据或私人申请记录，没有运行外部项目，也没有复制第三方实现。设计借鉴与代码复用应分开；若后续选择复制模块，再逐项核验固定版本许可证、依赖和兼容性。

# 材料动作后端 v0.19 交付与验证（2026-10-15）

基线 `25d842aec48ef243a1e009a849f89c641d75fd6c`。本分工只修改 `crawler/material_task_util.py`、`scripts/serve.py`、`tests/test_material_tasks_v19.py` 与本文；测试产物位于 `cache/policy_v19/backend/`，不得提交 cache。未修改 contact/project/workflow 核心、公开政策、前端或中央数据，未提交，未重启主服务。

## 行为

- v4 wrapper 保留 v3 六个集合并新增 `material_tasks`；所有旧模块接收 v3 投影，正常旧写路径合并保留 v4 历史。旧 GET `/api/workflow` 返回 v3。读 v1/2/3 仅内存规范化，无新文件/磁盘升级。
- `/api/workflow/backup` 导出规范化完整形态：旧版本为 v3，有材料记录为完整 v4。restore 接受 1—4，保存旧文件原字节，旧备份恢复明确替换已有 v4。
- 新 GET `/api/workflow/material-tasks` 返回 `version:1, actions:{pid:list}, records:{uuid:derived}`。POST 同端点每次生成 UUID4 新历史，不覆盖已有记录；POST `/{uuid}/reminders` 只选择该动作明确绑定事项。
- POST 严格字段白名单。目标八字段或完整动作指纹冲突返回 409；来源失效、变更或待复核时不可新登记/导入提醒。条件使用显式 boolean 确认；确认不改变既有日期导入规则，也不代表资格认证。
- 年/学校/院系/渠道/学位/track 隔离，具体专业未知不能靠确认绕过。目标专业代码非空而名称缺失时，即使学校通用动作也不可保存，视图返回 `program_pending` 与 `applicability_reasons`。
- 指纹绑定 goal snapshot、policy id、primary source id、政策范围、政策与动作条件、完整 action、resolved events、来源 URL 与 review hashes。恢复严格验证快照字段/类型/来源 URL/内部指纹。latest_record_id 只在完整目标和完整动作指纹均一致时返回历史记录。
- 人工状态 `todo/prepared/submitted/needs_revision` 均允许无附件，不从文件存在推断完成。复用 contact 内容 SHA-256 与 metadata 快照，总附件 20 MB；完整 workflow envelope 16 MB。附件正文不写入索引。
- GET 检查历史文件时，只打开当前 material index 同 ID、同路径的文件；历史未知 ID 或路径变化仅标问题，禁止读取历史任意路径。相同 size/mtime 仍读取内容 hash，变化/丢失/移动显示需复核。
- 提醒按北京时间日期保存，notes 保留原始事项种类、精确时间、原文、定位、全部事项来源 URL、材料动作说明/原文；同项目/动作/事项去重，不写 project.deadlines。文件变化而官方动作/目标/来源仍有效时可设提醒，notes 明确文件版本需复核，不表示已准备完成。
- 既有 local Host/Origin、JSON content-type、全局锁与 atomic save 路径保留。discovery 项目核验读取 v4 时先投影。

## 前端接口与样例

`cache/policy_v19/backend/view.fixture.json` 由真实 util 函数生成，包含 view/save_body/save_response。已同步前端负责人。

动作行字段：`policy_id, policy_title, action_id, action, action_fingerprint, goal_snapshot, conditions, program_pending, quality, events, latest_record_id, applicable, can_record, applicability_reasons`。

- `quality` 复用公开规则的 `state/label`，state 为 checked/changed/unknown/error/stale/review。
- `conditions` 是 `{scope:'policy'|'action', evidence:{text,quote,locator,source_ids?}}` 列表。
- `events` 是 `{event_index,event,source_url}` 列表。
- records 保留保存快照，增加 `applicable,review_required,review_reasons,files`。files 为原 attachment 快照加 `state`，取 unchanged/changed/missing/path_changed/unknown_material/unreadable。
- 保存响应是 derived record；提醒响应是 reminder 字段加 `duplicate:boolean`。

`source_snapshot` 作为后端 opaque 快照，形状为 `{source_id,sources:{sid:{url,review_hash}},scope,conditions}`。

## 验证

先运行新测试确认缺失 material_task_util 导致失败，再实现。root 复核发现 latest 目标/动作版本隔离与不完整专业对问题后，各加失败测试复现，再修复转绿。

- `python -m unittest discover -s tests -p test_material_tasks_v19.py`：15 项通过（最终日志 `cache/policy_v19/backend/material_tests.log`）。
- `PYTHONPATH=tests python -m unittest test_material_tasks_v19 test_workflow test_applications test_contact_flow test_project_model test_project_api test_project_reviews_v16 test_conditional_project_v18`：组合回归 78 项通过、261.182 秒。该组合执行时新测试为 13 项；后续新增两项隔离测试和提醒说明断言由最终 15 项覆盖。
- `python -m py_compile crawler/material_task_util.py scripts/serve.py` 通过。

新测试覆盖：旧 1/2/3 只读无写；完整 v4 备份恢复与旧恢复替换/原字节；scan、project/material/target/draft POST/PATCH、confirm、reply+task、communication、reminder、EML、discovery 的 v4 兼容；目标/来源 TOCTOU 409；条件/专业/范围矩阵；无 actions 旧政策；多动作/多项目隔离；不可伪造附件；same-size/mtime 内容变化；文件丢失、历史未知/移动路径禁止读取；20 MB/16 MB；提醒事项显式绑定/类型/时间/重复；非法 Host/Origin/content-type。

全部可写测试均用 TemporaryDirectory 和临时 private/index；未向真实私人文件写入，无网络上传，不执行材料内容。

## 集成与限制

需要根任务最终重新启动现有 Python 后端，才会加载新 serve 和 material_task_util；本分工未自行重启 18768。公开动作数据的真实原文与事件关系由公开分工及根任务审核；本后端合成 fixture/通过测试不构成官方政策完备性或个人资格证明。前端浏览器真实流程与资源版本由前端及根任务收口。

# 申请目标模型 v0.10 / workflow v3

本次仅扩展私人申请工作流。公开导师、招生政策、材料原文件保持原有存储；材料仍由 `materials.project_ids` 关联申请。

## 结构与 API

`projects` 保留 v1 的全部字段，包括自由文本 `school`、`college`、`application_type` 和现有 `year`。新增 `school_id`、`dept_id`、`degree`、`route`、`track`、`program_code`、`program_name`，未知均为 `''`；新增 `deadlines` 默认为 `[]`。旧项目不根据名称、导师或年度推断目标。

学校/院系组合来自公开 `data/schools.yaml` 与 `sites/*/*.yaml`。学位为 `master/phd`，渠道为 `recommend/exam/assessment`，类别为 `ordinary/special`，均允许未知空串。不要求一次填齐，但导入政策事件必须目标范围齐全。

现有 `POST /api/workflow/projects` 创建，`PATCH /api/workflow/projects/{id}` 更新；时间以完整 `deadlines` 列表提交。`GET /api/workflow` 返回 workflow v3，`GET /api/workflow/backup` 返回 `{version: 3, workflow: ...}`。恢复接受 v1/v2/v3，要求内外版本一致；校验成功后先保留旧文件原始字节备份，再原子替换。GET 仅在内存升级，不创建或重写私人文件。

时间项固定字段：

```json
{"label":"个人计划：整理材料","kind":"plan","at":"2026-11-01","origin":"manual","policy_id":"","source_ids":[],"source_url":"","quote":"","locator":""}
```

`kind` 允许 `deadline/exam/qualification/plan`，`origin` 为 `manual/policy`。`at` 只接受 ISO 日期或带时区的 ISO 日期时间，保留原精度和时区；不补时间，且事件年份不必等于入学年度。重复相同时间项被拒绝。

个人计划可附可选 HTTP(S) 参考 URL、原文或定位说明，但必须没有 `policy_id/source_ids`。这些引用未经系统核验，不会升级为政策事件。来源 URL 拒绝非 HTTP(S) 和带用户名密码的 URL。

新增或改动的政策快照必须逐字对应当前 `data/admissions.yaml` 的政策事件：`label/kind/at/quote/locator` 相同，`policy_id` 对应政策，`source_ids` 为事件自身来源或政策主来源默认列表，`source_url` 为实际 `source_ids[0]` 的 URL；其余引用完整保留供逐项查看。范围必须对应学校、院系、入学年度、学位、渠道、类别，具体专业必须明确选择且专业代码/名称匹配。专项目标不能把学校通用政策作为明确适用事件导入。来源检查质量由前端动态显示，不持久化或当作当轮仍开放的保证。

## 历史快照与上下文变化

历史快照保留登记时事实。政策更改或删除、学校院系从当前目录移除后，GET、备份、恢复、材料扫描、备注、沟通和提醒仍可使用，不以当前目录逐字一致为条件阻断私人工作流。历史目标不重映射，界面显示目录未收录、需核对。结构校验仍严格；新建或更改目标范围须验证当前学校院系目录，新导入或改动的政策事件须通过当前公开目录核验。恢复历史快照不意味着再次核验有效。

修改项目结构目标或年度时，不允许原样保留旧政策快照。界面应解释并经明确确认清理旧政策时间，然后重新选择适用事件；个人计划可保留。后端遇到残留旧政策时间返回 400，且不修改原文件。

## 实现与验证

`crawler/project_util.py` 管理 v3 结构、上下文和新事件导入校验；`crawler/contact_util.py` 的核心视图剥离扩展后复用 v1 校验，合并时恢复扩展。v1 核心 schema 无变更。

`tests/test_project_model.py` 与 `tests/test_project_api.py` 使用合成记录、临时文件与临时 HTTP 服务，覆盖旧版本只读升级、备份恢复、目标校验、政策快照与条件专业、非法日期/URL、原子拒绝，以及扫描/材料/目标/草稿/确认发送/回复/提醒/备注操作后扩展字段不丢失。策略更改后历史读取与写入可用有专门反例测试。既有 API 输出版本断言改为 v3，旧 v1/v2 输入仍保留测试。

未运行 build、未读取或写入真实私人工作流、未 stage 或 commit。当前测试结果由交付记录另外报告，不将测试通过解释为招生信息仍有效。

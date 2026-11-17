# v0.16 项目核验后端交付

本记录仅覆盖后端与临时私人目录测试；不等同于页面联调、真实用户资格判断或全部版本验收。

## 文件与兼容边界

- `crawler/project_review_util.py`：目标八字段快照、确定性ID、人工核验保存及两项独立证据状态。
- `crawler/discovery_util.py`：读取与校验v1/v2；旧preferences/reviews逐对象保留。
- `scripts/serve.py`：新端点、现有锁内重新读取workflow、旧接口保持v2、匹配版本备份恢复。
- `tests/test_project_reviews_v16.py`：纯函数与临时目录HTTP测试。

GET不迁移、不写文件；第一次明确保存项目核验才写version 2及project_reviews。项目名和备注不参与ID。普通目标允许未指定专业；专项必须有正式名称，代码可空；填代码而名称空视为不完整。学校院系必须已登记，导师实际登记单位须精确一致。服务器不接受客户端goal_snapshot/source_hash/communication_hash。

## API合同

`POST /api/discovery/project-reviews`：精确字段为`project_id, mentor_id, expected_goal, opportunity, eligibility, opportunity_evidence, eligibility_evidence, confirmed`。expected_goal为`school_id/dept_id/year/degree/route/track/program_code/program_name`。机会、资格均取pass/fail/unknown；confirmed必须true；非unknown必须有各自证据。

证据为null，或`{kind: official, source_url, quote, scope, source_id?}`，或`{kind: reply, communication_id, quote, scope}`。scope为用户明确登记的非空适用范围文本。回复必须是当前工作流同项目同导师kind=replied，引用原文为正文子串；draft/sent/note不可引用。服务器捕获整条回复指纹，以检测之后恢复造成的内容或关联变化。

官方证据验证HTTP(S)、主机、无凭据；官方性质和原文适用性仍由用户核对。source_id可省；URL按登记源的资源身份匹配时服务器自动绑定并捕获当前hash，同资源多个登记源优先选当前有效来源。scheme/host大小写、默认端口等价；HTML/PDF锚点不改变资源，format=json保留fragment文章路由。指定id时也按此规则匹配。最近检查失败、缺hash或最近成功超过7天拒绝保存；后续出现这些状态则仅该项回unknown。未知URL保存为未监测，无网络访问，也不认证其官方性质。旧未监测URL后来被登记时，GET返回source_registered并使该项unknown，必须重新确认保存才能捕获指纹；登记源失效则另附source_unavailable，不写回存储。

保存响应为纯存储记录，以`goal_snapshot/id/checked_at`替换expected_goal；登记来源附source_hash，回复附communication_hash。目标在表单打开后变化或丢失返回409；其他输入错误400；同源保护403、非JSON写415；错误为`{error: 中文说明}`。

`GET /api/discovery/project-reviews`返回：

- projects：id映射到`{id,name,goal_snapshot,complete}`。
- replies：仅已收到回复，id映射到`{id,project_id,mentor_id,subject,date,content}`。
- project_reviews：id映射到存储记录，加`applicable/reasons/opportunity_status/eligibility_status/opportunity_reasons/eligibility_reasons`。

applicable仅由全局项目目标、单位匹配、核验日期决定。两项证据独立；一项失效不会撤下另一项有效结论。全局原因包括project_missing/goal_changed/goal_incomplete/mentor_mismatch/expired；证据原因包括evidence_missing/evidence_changed/source_missing/source_unavailable/source_changed/source_registered/source_unmonitored。source_unmonitored是提示而非失效。核验日期超过30天全局失效。

旧GET和backup仅返回存储schema，不混入上下文或动态状态。backup外层version与存储版本一致；restore接受相符的v1/v2，保留被替换文件原始字节；沿用Host/Origin/Referer/Sec-Fetch-Site、JSON内容类型、锁和原子替换保护。

## 验证

先增加测试并观察缺失新模块导致失败，再实现及补充边界测试。`python -m unittest discover -s tests -p test_project_reviews_v16.py`：17项通过。覆盖项目隔离与目标变化、409保存拒绝、回复草稿/跨项目/跨导师/原文变更/丢失、8天来源失效与30天核验过期、hash变化、来源URL绑定、自动捕获hash及失败源不能绕过、两项独立、v1无自动迁移、v2旧写保留、备份版本及原字节、同源保护。独立审查发现的fragment绕过及新登记源漏检，先补3项测试并观察失败，再修复为按资源身份匹配；包括HTML/PDF锚点、大小写/默认端口、JSON不同文章路由，以及新登记源成功/失败均须重新核对且不连带另一维度。补充非法端口备份恢复API回归：schema校验主动读取port，拒绝bad端口400且文件原字节不变，随后GET仍正常。

回归通过：`test_discovery.py` 6项、`test_project_api.py` 4项、`test_project_model.py` 7项、`test_contact_flow.py` 13项。最新v16日志在`cache/policy_v16/backend-v16-tests.log`，审查修复前的3项失败在`cache/policy_v16/backend-source-identity-red.log`。总计本后端验证47项通过，未计协调者运行的其他检查。

未修改真实私人文件、未运行构建、未commit。本模块不发送邮件，不自动补充申请人条件，不把人工结论当系统资格认证。文件被站外程序直接改写不受服务进程锁约束；支持的API写入会在同一锁内重新读取目标并原子写核验。

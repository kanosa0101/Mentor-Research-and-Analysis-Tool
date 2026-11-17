# 北组招生政策与材料动作 v0.20（2026-10-15）

独立分片，中央数据、站点与私人数据未改动。冻结分片为 `cache/policy_v20/north/fragment.json`，证据清单 `manifest.json`、`discovery-manifest.json`、`action-evidence.json`，复核脚本 `assemble.py`，结果 `validation.json`。不提交 cache。

本轮新增29个材料动作：7个既有政策增补21动作，3个真实缺失的补充政策包含8动作；3个新增正式来源。原11政策33动作完整保留。既有政策的reviewed_at/review_hashes不变，没有policy_updates。原始22个官方来源于本轮直接HTTP GET取得并落盘，包含18个既有来源，全部规范指纹与中央旧值相同；另7个官方发现页也本轮GET并保存原字节。请求UTC时间见manifest，对应北京时间2026-10-15。fingerprint使用现有crawler/admissions_util.py语义；raw_sha256独立保存，未用网络缓存替代实际请求。

清华普通硕士新增报名核验、应届成绩单原件、拟录取函调及条件性定向协议；新10003报名公告政策分开在京二学位（10月24日22:00）、在读研究生和学历学籍校验未通过者（12月18日22:00）扫描件截止，只有真正对应动作才关联各自事件。二学位/在读研究生/校验异常均有条件，普通在校本科生不会被无条件要求提供这些证明。

北理工学校政策补报名承诺、学历学籍核验、条件性在读研究生证明。新1107考点政策仅适用选择1107并符合其受理范围者；身份证核验失败、应届学籍失败分别准备相应材料，收到资格复核或材料不符通知者10月31日12:00前补交。学校网报截止没有套成全部补正截止。

北航学校政策新增采集照片报名缴费、按提示名单交补充材料、复试通用包、应届成绩表、往届学历和档案成绩、同等学力资格材料及应届入学毕业证交验。1106考点官方公告明确：10月15—24日“无需在网上报名系统上传材料”，按10/14、19、23、25提示名单中的类别和指定网址另交；需复核者10月31日中午12:00前补充。新增独立1106条件性政策保留这一渠道差异，未把其规则套到其他考点。

南开学校政策新增研招网报名承诺缴费、条件性学历学籍认证、函调盖章现实表现、定向合同。认证具体提交渠道/日期，章程要求继续看专项通知；本轮取得两个专项通知HTML但正文无可提取材料条款、未发现明文附件链接，不据此编造截止或新增政策。

清华计算机推免补现场身份证/学生证交验；自动化推免补9月3日现场原件包并明确前期已结束；学校推免补2027年6月最后学期结束前最后学年正式成绩单交寄，原文未给日，不生成日期事件。未为已结束推免批次伪造当前可报名状态。

## 院系范围与缺口

本轮复取清华计算机085400科目调整、CS推免和自动化推免；北航网安2027第四单元408；南开CS/网安/软件2027正式统考目录及推免、软件预报名PDF；北理CS推免通知。以上既有源都未变，科目通知和招生目录本身没有新增可操作材料清单，不填充空动作。

本轮另读北理CS首页、北航CS首页、北航网安首页、南开研究生教育栏目与软件学院首页。可见2027内容以已结束推免、北航网安科目调整为主，北航CS首页有2027推免方案。结合官方域名网页检索，未取得四校CS/软件/网安/自动化各单位完整2027普通统考复试材料细则，不能宣称所有院系额外要求已齐，也不能把2026复试细则移植2027。发现页只证明此次检查到的内容，不证明全站没有其他公告；后续仍需分页、招生目录备注及当年复试通知继续补全。

## 校验

- 对内存合并数据运行现有validate和validate_checks，均通过；未写中央文件。
- 29动作52个instruction/applies_if证据对象均逐一确认是本轮提取原文的精确子串，引用源属于对应政策review_hashes且与本轮规范指纹相同。
- 新政策所有字段、条件、事件引文均确认原文子串；事件索引/阶段/条件schema通过。
- 只有3个实际缺失补充范围新建政策，没有给旧政策刷新review时间或用新哈希搭旧摘要。
- 原有11政策33动作保持；未接触真实私人文件、未联系任何人、未提交。

正式来源：
- [清华10003报名公告](https://yz.tsinghua.edu.cn/info/1009/3269.htm)
- [北理工1107考点公告](https://grd.bit.edu.cn/zsgz/ssyjs/tzgg_ss/5340e5a835934810b5e314fe10eaa2e1.htm)
- [北航1106考点公告](https://yzb.buaa.edu.cn/info/1003/3637.htm)
- [南开硕士招生栏目](https://yzb.nankai.edu.cn/5509/list.htm)

## 独立审查后的修正与重冻结

根任务审查指出：动作自身的applies_if无法阻止project_util将无政策级条件的学校events当成通用官方日期。已给新清华10003特殊材料政策补上政策级union适用条件，只涵盖在京二学位在校生、在读研究生、学历学籍核验未通过三类；证据为“以下三类”到第三类说明结尾的连续官方原文，动作自身条件继续细分。两个截止不应自动写入普通申请目标。

`python cache/policy_v20/north/check_conditional_dates.py`在纯内存构造普通CS本科硕士统考目标，证实旧无条件政策原会applicable，新条件政策applicable=False；两个事件经真实project_util.validate_imports均拒绝自动导入，3动作仍保留各自身份条件，未读取或写入私人数据。`assemble.py`重新schema/原文校验通过。

重冻结fragment SHA-256：`337ac1d4cfca9ed434c1d2eb01a5f2ce1d811557f62a373a14cd46200b84411e`。精确回归结果 `cache/policy_v20/north/conditional-deadline-regression.json`。总数仍为29动作、3新政策、3新来源。

## 正式防回归测试

新增正式测试文件 `tests/test_conditional_deadlines_v20.py`（只新增此测试文件，不改生产实现）。直接读取中央公开政策配置，并将全部工作流读写限制在测试临时目录。覆盖三条新政策的policy级条件、普通CS目标适用性拒绝、真实validate_imports阻断所有特殊日期、动作条件细分及清华两个截止分别绑定，以及临时HTTP GET不创建工作流、既有临时工作流字节不变、只展示policy/action条件而不生成材料记录或确认身份。

红灯命令：`python cache/policy_v20/north/run_conditional_mutation.py`。仅在内存副本删除清华policy.applies_if，运行同套5测试，产生5个预期失败（含两个事件子用例）；日志 `conditional-tests-mutation.log`。该包装命令以“成功复现失败”为成功退出，原unittest结果明确FAILED。

绿灯命令：`python -m unittest discover -s tests -p test_conditional_deadlines_v20.py -v`。实际中央现态5测试全部通过，7.709秒，日志 `conditional-tests-pass.log`。没有全局固定政策/来源/动作总数断言；未修改已冻结来源分片、中央数据或真实私人文件，未提交。

## 原招生UI验收夹具适配

`scripts/admissions_ui_check.py`首轮失败来自旧夹具把清华CS 2027硕士统考卡固定为2张；本轮新增10003特殊身份材料政策属于合法可见卡，应为原学校规则、085400科目规则及新条件政策三个明确ID。仅修改该旧UI脚本的范围断言：首次统考及无效年度改回2027两处使用精确ID集合，并核新政策的policy.applies_if正文/引文/定位；推免保持原2卡且新增原ID集合校验；file模式从原6政策更新为原6明确ID加新条件政策，仍保留两条博士原ID计数断言。未知年度0卡及其他分支不变，未改生产和正式tests。

`python scripts/admissions_ui_check.py`通过全部剩余分支，包括上下文、未知院系/年度/渠道、来源变更、XSS、项目预填/临时保存、移动端和file模式。通过日志 `cache/policy_v20/north/admissions-ui-updated-pass.log`；首次失败由根任务保存在`cache/policy_v20/integration/admissions_ui_check.log`。本次通过日志有一次页面导航中止旧HTTP响应引发的WinError10053服务线程噪声，脚本最终退出0，浏览器pageerror为空且所有断言完成；未借此改服务实现。

## 原v19材料UI试点选择固定

`scripts/material_frontend_v19_integration_check.py`原先按学位寻找首个有动作政策；v20扩展政策后首个硕士候选已变为清华，与脚本内西工大6112条件检查目的不一致。仅把选择策略改为明确原v19试点ID：硕士`nwpu-school-2027-master-exam-v18`、博士`tsinghua-cs-2027-phd-assessment-v16pilot`，继续断言政策存在、学位匹配且有动作。原6112条件展示、提醒时间/原文/源链接、官方原文弹窗、文件版本变化、备份恢复及1440/390布局等断言完全保留。

`python scripts/material_frontend_v19_integration_check.py`双试点完整通过并退出0。日志 `cache/policy_v20/north/material-v19-pinned-pilot-pass.log`。全部申请、材料及恢复操作仅在脚本临时目录，公共招生页未调用私人API。未修改production或fullpytest读取的tests。新v20政策行为由独立v20验证覆盖；此旧脚本继续专门保护原v19行为。

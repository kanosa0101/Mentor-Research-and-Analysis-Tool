# 机会组织层级、分发与来源审核

**状态：只读建议，未迁移、未更新产品数据、未部署。** 审核日期：2026-11-15。

审核覆盖 data/opportunities.json 全部18条；现有来源配置61个。核对已登记证据、审核记录及快照，17条快照SHA-256与已登记值一致；高能所条目没有已核验正文。仅北师大、软件所科创计划、同济3个官方详情在本轮实网复核，其余不是本轮重新发布/重新核验。

## 结论

建议9条进入活动页（其中7条历史营、2条当期机构项目），6条改为导师招募标签，3条待定/待核验。三条边界：高能所来源不可用；北师大是学院统筹实习管理但外校范围及具体岗位未明；同济是正式推免预报名，建议归招生通知和学校要求历史轮次。分类不代表正在报名或符合本人资格。

6条个人招募均无现成mentor_id关联。只有董谨豪有同校同邮箱身份候选ruc-info-dongjinhao，仍需处理机会cs/导师info差异；复旦张帆不能绑定库里中南或浙大同名导师，另4人未找到同名条目。

|条目|主办层级／类型|建议去向|关键理由|
|---|---|---|---|
|高能所2027年全国大学生冬令营|unconfirmed_institute / winter_camp|待核验线索；核验后进入活动页|登记单位为高能所，但现有证据仅搜索索引，正文未安全取得；不能根据标题确认主办或当前开放。|
|北师大人工智能学院2026—2027学年秋季本科生科研实习|school_department / coordinated_internship_management|待定：学院统筹科研项目；不能拆成未经证实的导师标签|学院统一管理、分期申请及备案，可作为院系项目的候选；本文是招募管理建议而非已发布导师岗位清单，外校范围未知。需明确产品是否纳入学院内部科研实习管理通知。|
|软件所2026年大学生创新实践训练计划（科创计划）|research_institute / institute_research_program|活动页：院所科研计划|软件所研究生部统一发起、部门初选、系统立项并统一结题，属于院所级项目例外；附件联系人不是自动等同于导师。|
|清华AIR WINTER@AIR 2026冬令营|university_research_institute / winter_camp|活动页：历史冬令营|研究院统一组织冬令营；包含线下工作要求也不应因此改为个人导师招募。历史2026活动，不可换算成2027/2028当期。|
|北京大学科学智能学院2026冬令营|school_department / winter_camp|活动页：历史冬令营|学院组织；同篇公告另有拔尖培养计划，不能把两个不同事项混为同一报名窗口。|
|沈阳自动化所2026智慧赋能·创领未来冬令营|research_institute / winter_camp|活动页：历史冬令营|沈阳自动化所主办的机构级冬令营；日期为既有历史轮次，预计营期不能提升为已确定。|
|计算所2026计算未来暑期研修班|research_institute / summer_training|活动页：历史暑期研修|计算所统一暑期研修班；后续推免选拔是不同事项，入营不是研究生录取。|
|软件所2026软件与网络夏令营|research_institute / summer_camp|活动页：历史夏令营|软件所统一营，实验室安排科研实践不改变机构级主办；纸质材料是入营提交而非在线报名附件。|
|计算机网络信息中心2026智能与网络夏令营|research_institute / summer_camp|活动页：历史夏令营|计算机网络信息中心统一营；网报与入选后材料截止不同，必须保留阶段。|
|上海交大计算机学院2026优秀大学生夏令营|school_department / summer_camp|活动页：历史夏令营|计算机学院统一夏令营；不能视为某一导师个人实习招募。|
|电子与信息工程学院2027年接收推荐免试研究生（含直接攻博）预报名通知|school_department / formal_recommendation_application|建议招生通知／学校与要求历史轮次，不属导师标签|正式2027入学推免预报名，不是夏冬令营等体验活动。若活动页严格按新边界，应归招生通知及政策；是否保留独立预推免类别由产品决定。|
|复旦大学张帆团队本科科研实习联系|individual_team / undergraduate_research_recruitment|导师标签：长期招募本科科研实习|公告为张帆个人教师介绍中的团队招募，不因托管于大数据研究院官网就变成研究院统一活动。|
|上海交通大学洪亮团队AI与生物方向长期实习|individual_team / research_internship_recruitment|导师标签：长期科研实习招募|洪亮团队加入我们页面；联系地点张江高等研究院不能证明研究院统一组织。邮箱是招募联系人，不能把其姓名当导师。|
|中国科大胡奇强实验室本科机器人科研联系|individual_lab / undergraduate_research_recruitment|导师标签：可联系本科科研|胡奇强教师主页的实验室本科生招募；同页27级研究生名额已满，不能提升成保研有名额。|
|西湖大学丁士超实验室访问学生联系|individual_lab / visiting_student_recruitment|导师标签：访问学生招募，资格须联系确认|丁士超实验室岗位招募，访问学生未明确本科限制；不是西湖大学统一科研营，招满即止不能声称始终有名额。|
|北航解佳豪课题组本科生科研实习|individual_team / undergraduate_research_recruitment|导师标签：长期科研实习招募|解佳豪个人教师主页明确长期招收实习生，非北航统一项目；不得推断所属院系、2028届限制或名额。|
|人大董谨豪课题组科研实习联系|individual_team / research_internship_recruitment|导师标签：长期科研实习招募|官方实验室教师页中董谨豪课题组招募；官方实验室站点是发布平台，不代表全实验室统一报名项目。|
|北京脑所2027年冬季培训班|research_institute / winter_training|活动页：院所冬季培训|北京脑所统一培训、统一材料与选拔安排，机构级项目；本科与硕士分层条件不转换成单一毕业届别。|

## 逐条来源与边界

### 1. 高能所2027年全国大学生冬令营

- ID：`ihep-winter-2027`；登记单位：中国科学院高能物理研究所。
- 建议：待核验线索；核验后进入活动页。登记单位为高能所，但现有证据仅搜索索引，正文未安全取得；不能根据标题确认主办或当前开放。
- [官方详情](https://www.ihep.cas.cn/edu/bks/xly/202611/t20261106_8304185.html)；已登记来源状态 `unavailable`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：无已核验匹配快照。
- 监测配置：[中国科学院高能物理研究所](https://ihep.cas.cn/edu/bks/xly/)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 需保留的限制：2026-11-15复查：搜索索引可读，www官方正文因证书过期无法安全取得；非www同路径返回404，官方栏目未列出该条。报名条件、材料和日期均保留为待复核线索，不能确认报名开放。

### 2. 北师大人工智能学院2026—2027学年秋季本科生科研实习

- ID：`bnu-ai-research-autumn-2026`；登记单位：北京师范大学人工智能学院。
- 建议：待定：学院统筹科研项目；不能拆成未经证实的导师标签。学院统一管理、分期申请及备案，可作为院系项目的候选；本文是招募管理建议而非已发布导师岗位清单，外校范围未知。需明确产品是否纳入学院内部科研实习管理通知。
- [官方详情](https://ai.bnu.edu.cn/ggjxz/tzgg/f7db49ad446c4a8ca26a34a80c4677e1.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：本轮官方网页核对：学院招募管理通知、分阶段流程、学院落款；未明确外校资格。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/v16/sources/f8fad73f4184556ffcb8e3723433feaf0f1f91b3cc383b0c440840188250acc1.body`。
- 监测配置：[北京师范大学人工智能学院](https://ai.bnu.edu.cn/ggjxz/tzgg/index.htm)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 附件／额外字段来源：[来源1](https://ai.bnu.edu.cn/docs/2026-11/1574318ca54e44ce90d277d904dd0297.docx)；[来源2](https://ai.bnu.edu.cn/docs/2026-11/e30c0717c5ec4ae58e2024ea250ce351.docx)。字段定位与SHA见JSON。
- 需保留的限制：已取得并核对学院官网正文；当前是导师征集阶段，学生申请尚未开始。原文称“各课题组、全体本科生”，未明确外校学生范围，不宣称面向全国开放。

### 3. 软件所2026年大学生创新实践训练计划（科创计划）

- ID：`iscas-research-2026`；登记单位：中国科学院软件研究所。
- 建议：活动页：院所科研计划。软件所研究生部统一发起、部门初选、系统立项并统一结题，属于院所级项目例外；附件联系人不是自动等同于导师。
- [官方详情](https://www.iscas.ac.cn/yjsjy/zsxx/202610/t20261028_8299649.html)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：本轮官方网页核对：所研究生部组织、系统立项及统一结题，截止只到月份。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 3 条；匹配原文快照：`cache/extraction_v13/opportunity_evidence/af7ab1ec85ff0e2994a5e6f792b8b601c07507f44cdc5ec00a86e34faffbe121.html`。
- 监测配置：[中国科学院软件研究所](https://www.iscas.ac.cn/yjsjy/zsxx/)（review_log_listing，listing）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:22:51+00:00，Codex official-source review v1.7；[已登记发现入口](https://www.iscas.ac.cn/yjsjy/zsxx/)。
- 附件／额外字段来源：[来源1](https://www.iscas.ac.cn/yjsjy/zsxx/202610/P020261028618405519532.xlsx)。字段定位与SHA见JSON。
- 需保留的限制：已核对官方正文与招募研究方向附件。受理截至月份明确，具体截止日未公布；毕业届次和研究生入学年份未明确，不由年级推断。

### 4. 清华AIR WINTER@AIR 2026冬令营

- ID：`air-winter-2026`；登记单位：清华大学智能产业研究院。
- 建议：活动页：历史冬令营。研究院统一组织冬令营；包含线下工作要求也不应因此改为个人导师招募。历史2026活动，不可换算成2027/2028当期。
- [官方详情](https://air.tsinghua.edu.cn/info/1007/2476.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/current_opportunities_v12/air-winter-2026.html`。
- 监测配置：未找到直接URL或同官方主机的来源；需补机构栏目发现。
- 需保留的限制：2025年发布的2026冬令营，仅历史参考；不等于正式保研录取。报名日期、材料与活动确切日期待核查。

### 5. 北京大学科学智能学院2026冬令营

- ID：`pku-ai4s-winter-2026`；登记单位：北京大学深圳研究生院科学智能学院。
- 建议：活动页：历史冬令营。学院组织；同篇公告另有拔尖培养计划，不能把两个不同事项混为同一报名窗口。
- [官方详情](https://ai4s.pkusz.edu.cn/info/1007/1335.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/current_opportunities_v12/pku-ai4s-winter-2026.html`。
- 监测配置：[北京大学深圳研究生院科学智能学院](https://ai4s.pkusz.edu.cn/xydt/tzgg1.htm)（same_host_candidate_not_proven_parent，listing）；[北京大学科学智能学院招生信息](https://ai4s.pkusz.edu.cn/zspy/zsxx.htm)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 需保留的限制：日期年份由2025年发布及2026年活动上下文确定；此条只记录冬令营，不把同文拔尖计划混成同一活动。

### 6. 沈阳自动化所2026智慧赋能·创领未来冬令营

- ID：`sia-winter-2026`；登记单位：中国科学院沈阳自动化研究所。
- 建议：活动页：历史冬令营。沈阳自动化所主办的机构级冬令营；日期为既有历史轮次，预计营期不能提升为已确定。
- [官方详情](https://sia.cas.cn/zpjy/yjsjy/zs/zsgg/202512/t20251215_8027511.html)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/current_opportunities_v12/sia-winter-2026.html`。
- 监测配置：[中国科学院沈阳自动化研究所](https://sia.cas.cn/zpjy/yjsjy/zs/zsgg/)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 需保留的限制：活动日期为原通知预计日期；截止原文为1月15日之前，未给具体时刻。

### 7. 计算所2026计算未来暑期研修班

- ID：`ict-summer-2026`；登记单位：中国科学院计算技术研究所。
- 建议：活动页：历史暑期研修。计算所统一暑期研修班；后续推免选拔是不同事项，入营不是研究生录取。
- [官方详情](https://www.ict.ac.cn/yjsjy/zsxx/sszs/202607/t20260702_8237097.html)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/current_opportunities_v12/ict-summer-2026.html`。
- 监测配置：[中国科学院计算技术研究所](https://www.ict.ac.cn/yjsjy/zsxx/sszs/)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 需保留的限制：暑期班和8月20—21日推免选拔为不同事项；本文不把入营等同录取。发布日期经官方通知列表确认。

### 8. 软件所2026软件与网络夏令营

- ID：`iscas-summer-2026`；登记单位：中国科学院软件研究所。
- 建议：活动页：历史夏令营。软件所统一营，实验室安排科研实践不改变机构级主办；纸质材料是入营提交而非在线报名附件。
- [官方详情](https://www.iscas.ac.cn/yjsjy/zsxx/202607/t20260716_8250354.html)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/current_opportunities_v12/iscas-summer-2026.html`。
- 监测配置：[中国科学院软件研究所](https://www.iscas.ac.cn/yjsjy/zsxx/)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 需保留的限制：URL路径为7月但页面明确来源时间及落款5月28日，采用正文日期；具体活动日期未公布，不推断起止日。

### 9. 计算机网络信息中心2026智能与网络夏令营

- ID：`cnic-summer-2026`；登记单位：中国科学院计算机网络信息中心。
- 建议：活动页：历史夏令营。计算机网络信息中心统一营；网报与入选后材料截止不同，必须保留阶段。
- [官方详情](https://cnic.cas.cn/yjsjy/tzgg/202605/t20260527_8209811.html)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/current_opportunities_v12/cnic-summer-2026.html`。
- 监测配置：[中国科学院计算机网络信息中心](https://cnic.cas.cn/yjsjy/tzgg/)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 需保留的限制：网上报名截止与入选后材料提交截止不同，不合并成一个截止。

### 10. 上海交大计算机学院2026优秀大学生夏令营

- ID：`sjtu-cs-summer-2026`；登记单位：上海交通大学计算机学院（网络空间安全学院、密码学院）。
- 建议：活动页：历史夏令营。计算机学院统一夏令营；不能视为某一导师个人实习招募。
- [官方详情](https://cs.sjtu.edu.cn/bsyjs_zsgz/1748.html)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 0 条；匹配原文快照：`cache/winter_20261115/sjtu-cs-summer-2026.html`。
- 监测配置：[上交计算机学院](https://www.cs.sjtu.edu.cn/bsyjs_zsgz.html)（same_host_candidate_not_proven_parent，listing）。同域候选不能视为已证明的公告父列表。
- 需保留的限制：校内学生成绩单与排名证明有单独安排。仅历史参考；营期以入围通知为准。

### 11. 电子与信息工程学院2027年接收推荐免试研究生（含直接攻博）预报名通知

- ID：`tongji-ee-recommend-2027`；登记单位：同济大学电子与信息工程学院。
- 建议：建议招生通知／学校与要求历史轮次，不属导师标签。正式2027入学推免预报名，不是夏冬令营等体验活动。若活动页严格按新边界，应归招生通知及政策；是否保留独立预推免类别由产品决定。
- [官方详情](https://see.tongji.edu.cn/info/1173/14903.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：本轮官方网页核对：学院官网标题与发布日期确认正式推免预报名；本轮未重新逐页下载PDF，字段沿用登记证据。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/extraction_v13/opportunity_evidence/1217f9a6b0f237f6bbb918308c814f6909b10cc9567c8eaa04681f91996ead6f.html`。
- 监测配置：[同济大学电子与信息工程学院](https://see.tongji.edu.cn/jxgz/yjsjx/zsgz.htm)（review_log_listing，listing）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T04:55:06+00:00，Codex官方原文逐页核验；[已登记发现入口](https://see.tongji.edu.cn/jxgz/yjsjx/zsgz.htm)。
- 附件／额外字段来源：[来源1](https://see.tongji.edu.cn/__local/0/CA/40/80ACF42AA9C448546B4B52A25D2_433060EA_4F2DE.pdf)。字段定位与SHA见JSON。
- 需保留的限制：已核验官方PDF第1—5页及其文件版本；仅供历年申请要求参考，不代表新一轮要求或名额。

### 12. 复旦大学张帆团队本科科研实习联系

- ID：`activity-d6cf0d3b78a48e8ce493`；登记单位：大数据研究院张帆团队。
- 建议：导师标签：长期招募本科科研实习。公告为张帆个人教师介绍中的团队招募，不因托管于大数据研究院官网就变成研究院统一活动。
- [官方详情](https://ibd.fudan.edu.cn/0f/12/c24067a724754/page.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/v17/publication_a/opportunity_evidence/7adcbde5292886f7f1fed22fd6709346e7065eecadbc2a6fbc122c42bc1ecc98.html`。
- 监测配置：[大数据研究院张帆团队](https://ibd.fudan.edu.cn/0f/12/c24067a724754/page.htm)（direct_exact_url，direct_page）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:16:07+00:00，v17-official-research-a；[已登记发现入口](https://ibd.fudan.edu.cn/0f/12/c24067a724754/page.htm)。
- 需保留的限制：未公布本科实习具体时长、费用或住宿；每年研究生招生数量不视为当前本科实习名额；未明确2028届资格
- 导师关联：尚无同校姓名及官方身份一致的现有导师记录；不得只凭姓名绑定或创造导师ID。 候选：无可直接使用的候选。

### 13. 上海交通大学洪亮团队AI与生物方向长期实习

- ID：`activity-ebd85b5bcea64ce072c2`；登记单位：洪亮团队／张江高等研究院。
- 建议：导师标签：长期科研实习招募。洪亮团队加入我们页面；联系地点张江高等研究院不能证明研究院统一组织。邮箱是招募联系人，不能把其姓名当导师。
- [官方详情](https://ins.sjtu.edu.cn/people/lhong/join-us.html)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/v17/publication_a/opportunity_evidence/71ff651c962c834fbc63ffe531fbdd333c924529c15f24b66f2f73bc664df8de.html`。
- 监测配置：[洪亮团队／张江高等研究院](https://ins.sjtu.edu.cn/people/lhong/join-us.html)（direct_exact_url，direct_page）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:16:07+00:00，v17-official-research-a；[已登记发现入口](https://ins.sjtu.edu.cn/people/lhong/join-us.html)。
- 需保留的限制：未公布固定截止、实习时长或届别限制；待遇原文为详情面谈，没有金额承诺；表现优异可进一步申请学位，不代表保研录取
- 导师关联：尚无同校姓名及官方身份一致的现有导师记录；不得只凭姓名绑定或创造导师ID。 候选：无可直接使用的候选。

### 14. 中国科大胡奇强实验室本科机器人科研联系

- ID：`activity-03f42b3a3c32a4c22d97`；登记单位：胡奇强实验室／人形机器人研究院。
- 建议：导师标签：可联系本科科研。胡奇强教师主页的实验室本科生招募；同页27级研究生名额已满，不能提升成保研有名额。
- [官方详情](https://faculty.ustc.edu.cn/qqhu/zh_CN/zdylm/1029917/list/index.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/v17/publication_a/opportunity_evidence/4d3fa8e052ac9805f6b405a43b597957ac9c72fb927ba333e8efdd3ab2fadd80.html`。
- 监测配置：[胡奇强实验室／人形机器人研究院](https://faculty.ustc.edu.cn/qqhu/zh_CN/zdylm/1029917/list/index.htm)（direct_exact_url，direct_page）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:16:08+00:00，v17-official-research-a；[已登记发现入口](https://faculty.ustc.edu.cn/qqhu/zh_CN/zdylm/1029917/list/index.htm)。
- 附件／额外字段来源：[来源1](https://faculty.ustc.edu.cn/qqhu/zh_CN/zdylm/1029914/list/index.htm)。字段定位与SHA见JSON。
- 需保留的限制：同页27级保研研究生名额明确已满，本条仅为本科科研长期招募；不把研究生或国际学生材料要求套给本科生；外校接收、经费和时长未明示
- 导师关联：尚无同校姓名及官方身份一致的现有导师记录；不得只凭姓名绑定或创造导师ID。 候选：无可直接使用的候选。

### 15. 西湖大学丁士超实验室访问学生联系

- ID：`activity-ffaa8dc527fe9b19b72d`；登记单位：网络化生物电子系统实验室。
- 建议：导师标签：访问学生招募，资格须联系确认。丁士超实验室岗位招募，访问学生未明确本科限制；不是西湖大学统一科研营，招满即止不能声称始终有名额。
- [官方详情](https://shichaoding.lab.westlake.edu.cn/)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/v17/publication_a/opportunity_evidence/75648601c1cf00dc1354ca96dfe7ab17b12afe2f058d6af8c7d6ba9326e12114.html`。
- 监测配置：[网络化生物电子系统实验室](https://shichaoding.lab.westlake.edu.cn/)（direct_exact_url，direct_page）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:16:09+00:00，v17-official-research-a；[已登记发现入口](https://shichaoding.lab.westlake.edu.cn/)。
- 需保留的限制：岗位招满即止，未获导师确认前不能承诺有名额；访问生未明确限定本科或应届年级，需联系确认；官网有2026年11月外校访问学生加入记录，仍不推定所有学校无条件可申请；未公开费用、待遇或访学时长
- 导师关联：尚无同校姓名及官方身份一致的现有导师记录；不得只凭姓名绑定或创造导师ID。 候选：无可直接使用的候选。

### 16. 北航解佳豪课题组本科生科研实习

- ID：`buaa-xiejiahao-research-rolling`；登记单位：北京航空航天大学解佳豪课题组。
- 建议：导师标签：长期科研实习招募。解佳豪个人教师主页明确长期招收实习生，非北航统一项目；不得推断所属院系、2028届限制或名额。
- [官方详情](https://shi.buaa.edu.cn/jiejiahao/en/xsxx/230178/list/index.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/v17/publication_b/opportunity_evidence/152832292c753e77c3721e84c3fe4778e21d76d834cd5ce4179e637ae44df37a.html`。
- 监测配置：[北京航空航天大学解佳豪课题组](https://shi.buaa.edu.cn/jiejiahao/en/xsxx/230178/list/index.htm)（direct_exact_url，direct_page）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:22:52+00:00，Codex official-source review v1.7；[已登记发现入口](https://shi.buaa.edu.cn/jiejiahao/en/xsxx/230178/list/index.htm)。
- 需保留的限制：北航官方教师主页明确长期招收科研实习生。是否仍有位置及线下/线上安排需导师确认；不标成2028届专属。
- 导师关联：尚无同校姓名及官方身份一致的现有导师记录；不得只凭姓名绑定或创造导师ID。 候选：无可直接使用的候选。

### 17. 人大董谨豪课题组科研实习联系

- ID：`ruc-dongjinhao-research-contact`；登记单位：信息学院·数据工程与知识工程教育部重点实验室。
- 建议：导师标签：长期科研实习招募。官方实验室教师页中董谨豪课题组招募；官方实验室站点是发布平台，不代表全实验室统一报名项目。
- [官方详情](https://deke.ruc.edu.cn/kytd/zzry/ab852a64cdbe42468db8234b238a03ca.htm)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/v17/publication_b/opportunity_evidence/3dd000dd3633b7222d2a523cf8b0ddfebd09bfef54e30c7a80277ea2c9cf3e3b.html`。
- 监测配置：[信息学院·数据工程与知识工程教育部重点实验室](https://deke.ruc.edu.cn/kytd/zzry/ab852a64cdbe42468db8234b238a03ca.htm)（direct_exact_url，direct_page）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:22:52+00:00，Codex official-source review v1.7；[已登记发现入口](https://deke.ruc.edu.cn/kytd/zzry/ab852a64cdbe42468db8234b238a03ca.htm)。
- 需保留的限制：官方实验室教师页明确长期面向本科生和研究生开放科研实习。未公布材料、年级、排名、时长、待遇和校内外边界。
- 导师关联：同校姓名和公开邮箱一致，可进入人工身份核对；机会dept=cs与现有导师dept=info不一致，不能自动改院系。 候选：ruc-info-dongjinhao。

### 18. 北京脑所2027年冬季培训班

- ID：`cibr-winter-training-2027`；登记单位：北京脑科学与类脑研究所。
- 建议：活动页：院所冬季培训。北京脑所统一培训、统一材料与选拔安排，机构级项目；本科与硕士分层条件不转换成单一毕业届别。
- [官方详情](https://cibr.ac.cn/detail/cibrPersonneladmissions/4c3c22415af7498da6049027ccdd65cd)；已登记来源状态 `verified`；已登记核验日 `2026-11-15`；本轮：未在本轮重新联网；只读已登记证据及本地原文快照。
- 现存来源链：data/opportunities.json → 官方详情；审核日志 1 条；匹配原文快照：`cache/v17/publication_b/opportunity_evidence/82bf351c4c3ff3f0a9b37c7c7ce7ef949e9c870d322c0f94dcd74e5518c83dc6.html`。
- 监测配置：[北京脑所培训实习](https://cibr.ac.cn/cibrPersonnel/admissions)（review_log_listing，listing）；[北京脑所培训实习](https://cibr.ac.cn/cibrPersonnel/admissions)（review_log_listing，listing）。同域候选不能视为已证明的公告父列表。
- 最近已登记审核：2026-11-15T10:27:54+00:00，Codex official-source review v1.7；[已登记发现入口](https://cibr.ac.cn/cibrPersonnel/admissions)。
- 附件／额外字段来源：[来源1](https://cibr.ac.cn/file/common/download/13a079470f7d44c49e79407fdf73259c)；[来源2](https://cibr.ac.cn/file/common/download/44d8af4c5fbe42898a84882e17b51ee5)。字段定位与SHA见JSON。
- 需保留的限制：官方HTML及两份DOCX模板均直接取回。培训不收费、提供食宿及保险，交通自理。

## 现有导师字段能否承载

|字段|可利用|缺口／不得混用|
|---|---|---|
|`Professor.supervisor`|硕导/博导资格，找导师资格筛选使用。|静态任教资格不是当前招生名额，也不是科研实习招募，不得复用存招募标签。 参考 `crawler/model.py:42; site/discovery-core.js:25`。|
|`Professor.facets`|id/origin/confidence/evidence可作有出处标签基础。|缺招募类型、导师关联、适用对象、时间精度、名额状态、原文URL及定位和复核日期；list_record仅输出id，discovery_record未输出facets，不能直接稳定呈现新招募标签。 参考 `crawler/model.py:13; scripts/build_site.py:72,98`。|
|`Professor.provenance`|每字段origin/source/fetched_at/confidence。|抓取日期不等于核验日期；不足以独立表达一条招募声明的附件、原句定位、过期/撤回状态。 参考 `crawler/model.py:6; site/templates/detail.html.j2:145`。|
|`Professor.research_direction_raw/email/homepage/institutes`|研究匹配、公开联系方式、原主页与团队信息。|没有recruitment或活动引用结构；团队联系人不保证是导师本人。 参考 `crawler/model.py:44-60`。|
|`私人project_reviews.opportunity/eligibility`|用户具体项目、年/学位/渠道范围下的本人核对；超过30天或不匹配回到unknown。|私人主观/已核对申请状态不能当公共招募事实，也不能由实习公告自动赋pass。 参考 `site/discovery-core.js:31-43`。|
|`公共招募声明与导师的显式关联`|建议新增独立、可复核招募记录，并由mentor_id引用。|18条均未登记mentor_ids。6条转标签候选只有董谨豪找到同校同邮箱的身份候选，仍有dept不一致；其余须新增/补核导师资料，不能丢掉招募记录。 参考 `data/opportunities.json; site/data.js`。|

## 下一步数据与体验规则

1. 活动页默认只展示学校/学院/研究院/研究所统一组织的营、培训、研修和正式院所科研计划；公告在.edu.cn或.ac.cn上，不自动说明是机构统一活动。
2. 个人教师/实验室/课题组实习或访问学生招募归导师重要标签。标签展开显示研究方向、对象、申请材料、联系人角色、时间/名额不确定项、官方原文及核验时间。
3. 导师尚未入库时保留待关联招募池和证据，不假造mentor_id，不丢公告，不挪用同名其他学校导师。
4. 机构计划可关联已核验导师，但软件所附件部门联系人不能直接转为导师；机构级主记录仍保留活动页。
5. 正式推免/考研申请通知与科研体验活动分类型；同济历史预报名建议进入招生通知与学校要求，不放到个人标签。
6. 来源不可用保持待核验；历史条目只在历史参考中出现；原文未给具体截止日、毕业届别或当前名额时必须保留未知。
7. 来源展示需要同时区分发布机构、组织者、官方详情、报名入口、附件与字段定位、网页发布时间、系统核验时间；内部抓取/hash日志放详情。
8. 来源列表也要有organizer_level/content_type及分发目的地；6个direct_page仍应监测但分发到导师招募，不继续混入活动池。

最低招募结构建议：recruitment_id、organizer_level、recruitment_type、mentor_id（可空但需link_state）、官方source_url/quote/locator、source_published_at/checked_at、contact_role、target_audience、application_window及精度、availability（如需联系确认）、材料分阶段清单和status。不要把这整套事实压成无证据的字符串标签。

额外材料边界：北京脑所个人陈述官方模板明确要求申请人独立完成，AI协助会取消资格。产品可以说明要求与提醒，但不能替该项目代写个人陈述。该限制已在原source_attachments字段登记，本审核不新增推断。

验证：18个唯一ID逐条覆盖；17个本地原文hash匹配；输入文件签名核对未变。可解析结果：`opportunity-audit.json`。

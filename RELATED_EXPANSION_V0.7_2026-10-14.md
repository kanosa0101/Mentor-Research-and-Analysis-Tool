# 相关院系扩充 v0.7（2026-10-14）

基线：b70503ffe。此次仅新增华中科技大学人工智能与自动化学院（hust/aia）和中南大学自动化学院（csu/auto）；没有改动既有教师数据、schools.yaml、共享钩子、招生/通知/私人数据，没有 build、commit、push、AI 调用或 SMTP。

## 官方身份与名单边界

- 华中科技大学学院简介：https://aia.hust.edu.cn/yxgk/xyjj.htm ，现名为人工智能与自动化学院。现有 hust/cyber 是另一个院系，未重复单位。采用中文学院师资“按系列表” https://aia.hust.edu.cn/szdw/xysz/axlb.htm ：125 个 name+URL 对（124 个不同姓名，王博对应两个人主页）。与中文拼音列表 https://aia.hust.edu.cn/szdw/xysz/axmpyszmlb.htm 的 125 个登记项同名范围一致，其中 35 个链接不同（栏目/详情入口不同）；保留系列表入口，未把两个显示视图叠加入库。未纳入独立实验工程人员、博士后、荣休教师栏目及英文名单。
- 中南大学学院简介：https://soa.csu.edu.cn/xygk/xyjj.htm ，现名为自动化学院。现有 csu/cs 是计算机学院，未重复单位。中文教师名录 https://soa.csu.edu.cn/szdw/jcrc.htm 有 176 个锚点：四教学系（自动化科学与技术系、电气工程系、电子信息工程系、人工智能系）和电工电子基础教学中心共 132 项；44 项属于党政、学工或实验教学中心，学术身份未在该登记范围明示，未纳入。教学范围中 17 项只有指向教师名录本身的占位链接，115 个有效个人主页锚点按 name+URL 去掉一组重复后为 114 条。未覆盖英文名单。名录使用“电气工程系”，学院简介使用“电气控制系”，本次 institutes 逐字保留名录名称，未擅自合并机构身份。

两个配置均有 explicit_supervisor_only: true 和 roster_pending，公开说明该子集边界；本次结果不是学院全体教职工名单，也不是全部硕士/博士招生导师名单。官方教师登记身份明确、职称/导师资格不足的条目仍保留姓名和来源；缺字段不自动排除人员。

## 采集与字段规则

名单复用 sites/related_roster.py 的卡片/正式姓名/同源白名单/name+URL 去重规则，新增 sites/related_v7.py 仅包装中南大学显式 dept/title/type 属性和个人详情范围。华科名单“正高/副高/中级”不映射教授/副教授。职称仅取个人身份块中的完整职称或名单明确 title 属性；博士学位、曾任职务、他人/论文作者职称均不取。导师资格仅取个人身份资格行或名单本人 type，不继承共享 tsites 的全文兜底，不以页面导航/论文/学位推断。详情入口现设名单本人身份门禁：官方个人页标题含独立本人中文姓名，或明确姓名区确认本人，才能导入字段；英文姓名不靠拼音猜测，保留缺口。

邮箱仅取个人身份及“其他联系方式”区公开明文标签；不从全文、论文作者或公共联系方式取值。隐藏密文字段不解密、不猜测，因此 CSU 邮箱本轮保持空白。方向仅取明确“研究方向/研究领域”标签/栏目，嵌入简介的方向栏目截止招生、联系、项目或下一标题；简介只作为 bio_raw 辅助搜索，不自动推断研究方向。纯栏目名/暂无内容不是简介。

每个单位只有一个已登记、无需分页的名单页。列表空、未登记分页或解析异常会失败而非宣称没有教师。每条字段来源日期来自对应 HTTP 缓存元数据，缓存复解析保持原 fetched_at；此次全部成功保存来源的日期为 2026-10-14。

## 冻结数量与字段覆盖

| 单位 | 记录 | 详情解析成功 | 详情解析缺口 | 职称 | 导师资格 | 个人邮箱 | 明确方向 | 有内容简介 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| hust/aia | 125 | 123 | 2 | 104 | 76 | 31 | 67 | 116 |
| csu/auto | 114 | 110 | 4 | 109 | 91 | 0 | 52 | 84 |

239 条登记个人页均保存 HTTP 200 原始响应；详情缺口是当前解析器未识别安全范围的字段，不是网络死链，也不表示没有教师。院系中文名单链接可能跳转到英文模板，以下缺口保留名单数据和未解决 issues，不扩大为英文名单覆盖。韩守东和覃爱娜缺明确中文本人身份门禁证据；邹旭中文身份可确认但当前安全字段解析不足；姜霞、汤嘉伟、苏丹未识别安全字段。6 条失败记录的详情字段及详情 provenance 全部为空，只保留可信名单值。

| 单位 | 教师 | 登记个人页 | 当前缺口 |
| --- | --- | --- | --- |
| hust/aia | 韩守东 | http://faculty.hust.edu.cn/hanshoudong | ValueError('详情无明确个人字段，保留名单并登记失败') |
| hust/aia | 邹旭 | http://faculty.hust.edu.cn/zx | ValueError('详情无明确个人字段，保留名单并登记失败') |
| csu/auto | 姜霞 | https://faculty.csu.edu.cn/jiangxia/zh_CN/index.htm | ValueError('详情无明确个人字段，保留名单并登记失败') |
| csu/auto | 覃爱娜 | https://faculty.csu.edu.cn/tanaina/zh_CN/index.htm | ValueError('详情无明确个人字段，保留名单并登记失败') |
| csu/auto | 汤嘉伟 | http://faculty.csu.edu.cn/tangjiawei/zh_CN/index.htm | ValueError('详情无明确个人字段，保留名单并登记失败') |
| csu/auto | 苏丹 | https://faculty.csu.edu.cn/sudan/zh_CN/index.htm | ValueError('详情无明确个人字段，保留名单并登记失败') |

CSU 17 个教学范围占位链接待后续官方登记页核验：陈革辉、陈科文、陈智勇、高琰、黄廷文、胡燕瑜、罗启章、廖一寰、刘丽珏、李仪、毛先柏、吴显金、王一军、王击、肖晓明、叶华文、张涛。本轮不将同一个名单 URL 伪装成这些人的独立详情页。

## 验证与交付

- 先有范围/防污染测试，再实现包装钩子；最终 `python -m pytest tests/test_related_v7.py tests/test_cyber_expansion.py tests/test_seu_auto.py -q`：29 passed，只有现有 pytest_asyncio 对 Python 3.16 event-loop-policy 的弃用警告。
- 此次新增测试 11 项，覆盖院系配置/资格开关/公开子集、姓名+URL 去重、行政/占位链接过滤、博士/曾任/公共与论文邮箱/密文拒绝、明确个人联系字段、分行导师资格、方向栏目边界、h1 模板、空名单和未登记分页失败，以及错配个人页拒收、英文页标题但明确中文身份可用。
- 冻结审计通过：239 条模型均可读取、名单对与存储对一致、每个非空核心字段有来源、全部 provenance.fetched_at 与原缓存元数据一致、无 AI 块、职称/资格字段符合严格规则、方向没有栏目空值或项目污染。
- 原始缓存与哈希 JSON 位于 cache/related_v7/，已被现有 Git ignore 规则排除，不纳入 Git。新记录在 data/professors/hust/aia/ 与 data/professors/csu/auto/；issues 在对应新文件；复解析字段规范化及最终审计纠正记录在 data/changes/csu-auto.jsonl 与 data/changes/hust-aia.jsonl。已有单位文件没有改写。
- 首轮复解析纠正了分行资格汇总、h1 样式和嵌套方向边界；本次引入的空简介值已清除，详情解析仍不足的条目标为 roster。遗留缺口如上，不声称全覆盖或招生资格验证完成。
- 最终身份与逐字段一致性审计覆盖全部 239 条：233 条通过本人身份及安全字段解析，6 条失败记录只留名单来源值。复核清除了桑农、宋冬然的“研究方向”栏目名空值及周晶当前未得到安全解析支持的详情职称（此前姓名名单未明示职称）；这些纠正仅涉及此次新增目录，写入对应 changes。审计结果与纠正清单位于 cache/related_v7/identity_field_audit.json。两个目录现存全部详情来源字段均与本轮通过身份门禁的解析值逐字段一致。

可复现目标调用：在独立 Python 进程设置 `fetch.CACHE = Path('cache/related_v7/http')`，`fetch.set_direct(True)`，依次调用 `crawl.phase_roster(cfg, hook, False)` 和 `crawl.phase_enrich(cfg, hook, False)`（cfg 分别为 hust/aia、csu/auto）。不会全库抓取。需再次真实刷新时明确使用 refresh，来源日期以响应元数据为准。

## 逐页原文哈希清单

### 独立审查后生命周期修复

独立审查指出：即使新详情解析拒绝姓名错配，旧自动详情值仍可能通过 shared crawl 的异常保留路径继续公开。本次增加 `related_v7.IdentityMismatch` 专用信号，只对官方姓名标题或明确姓名区显示另一人的情况触发；无姓名/普通栏目模板不足仍是普通解析失败。

`scripts/crawl.py` 的撤回处理精确限定 hust/aia 与 csu/auto 且 hook 为 related_v7：仅清除 provenance.source 为当前 detail_url、origin 非 manual 的自动详情字段及其 provenance，写 changes 保存完整旧值、旧 provenance、撤回原因，状态回到 roster。人工值、名单来源值、其他来源值保持；网络/超时/普通模板解析失败保持历史。已用临时数据回归验证 phase_enrich 到 list_record、search_record、compare_record 的公开输出不再包含被撤回的他人职称、邮箱或简介。

此修复只改新钩子、shared crawl 的上述限定异常分支和维护回归测试；239 条真实数据及原始来源缓存没有改动。完整 Python 测试一次通过：`122 passed`（3 个现有依赖弃用警告）。CJS helper 检查中 admissions_rules、checklist_rules、discovery_rules 通过；当前新增 discovery_scope 有 2 项与本修复无关的范围回归失败，已通知整合负责人处理，不声称全局 helper 已通过。

本次相关保存源页 244 个（239 个人页、2 名单页、2 学院简介、1 华科名单对照页）。下表 SHA-256 是原始 HTTP body 字节的哈希；JSON manifest SHA-256：`4e019f91b720a6db545d6d87843e4d489c579b2ad57fa4f635eede4c0f9cbbd3`。探路猜测的两个错误 URL 返回 404，未登记为来源，未生成成功缓存。

| 单位 | 来源页 | 抓取日期 | HTTP | 原文 SHA-256 |
| --- | --- | --- | ---: | --- |
| hust-aia | http://faculty.hust.edu.cn/ChenLiQun/zh_CN/index.htm | 2026-10-14 | 200 | `72f5647dc0f9566450e06f49605795f6d85528f12a650c5d65e61c69246c01b5` |
| hust-aia | http://faculty.hust.edu.cn/HUBINBIN/zh_CN/index.htm | 2026-10-14 | 200 | `a734a58dd13a0e8dd2cdf8d5abdf9037f312d612e4c9f4f8fed79a9d38148076` |
| hust-aia | http://faculty.hust.edu.cn/JIANGYI/zh_CN/index.htm | 2026-10-14 | 200 | `10d723f13f20d1780e3f28b1f1d8ad51a708c6a4ba5732f01c690c007f2b9a20` |
| hust-aia | http://faculty.hust.edu.cn/LIUTONGJUN/zh_CN/index.htm | 2026-10-14 | 200 | `8915462ba16f906416c6ea303997caffd7614785d46b492154f639867034fc35` |
| hust-aia | http://faculty.hust.edu.cn/LUOQINQIN/zh_CN/index.htm | 2026-10-14 | 200 | `53f89dfa69a279628f641907f03baf5661913b1b2543ff56210cf78593a99f5c` |
| hust-aia | http://faculty.hust.edu.cn/ShengYin/zh_CN/index.htm | 2026-10-14 | 200 | `fc6fe9dc162638ec41ee4473655a7582b35a414816a35f80c6e33d56b832176e` |
| hust-aia | http://faculty.hust.edu.cn/SunJianKun/zh_CN/index.htm | 2026-10-14 | 200 | `3a121ead09f4d23497c40bd66670126a91ff520e2b030cb2cbd239278eca98a5` |
| hust-aia | http://faculty.hust.edu.cn/TANGCHAOQING/zh_CN/index.htm | 2026-10-14 | 200 | `e4f11962ae14b1175ffffa26a8f205b21358c6b54d2ce79e98ccb29d719e936d` |
| hust-aia | http://faculty.hust.edu.cn/TangQipeng/zh_CN/index.htm | 2026-10-14 | 200 | `1d4d26f943f7838782d555aa331966c84aae57956473bbfce189f985f965328b` |
| hust-aia | http://faculty.hust.edu.cn/WANGBo/zh_CN/index.htm | 2026-10-14 | 200 | `4ae57154f5750b9e4866e71e13b2b49e2721c4a09a133089f7baf19f8367c9fe` |
| hust-aia | http://faculty.hust.edu.cn/YiChang/zh_CN/index.htm | 2026-10-14 | 200 | `40cd172ebbe0f18c2f9e9c5339d675de7ff9773c1bb2e89e8b0ba23b06eb0200` |
| hust-aia | http://faculty.hust.edu.cn/YuYaowen/zh_CN/index.htm | 2026-10-14 | 200 | `fdf1c83157f4a6edbed1e1d70de4d213759634eff75bccb65be2e462d38c92c4` |
| hust-aia | http://faculty.hust.edu.cn/ZHANGYAHUI/zh_CN/index.htm | 2026-10-14 | 200 | `b3dda62ce74e9408b680ff445f5c663a8a1de8c28891cf19a1eec88c3aa8601d` |
| hust-aia | http://faculty.hust.edu.cn/ZHAOTIANMING/zh_CN/index.htm | 2026-10-14 | 200 | `4bd03e01b4ed30ecb18f071d1d571aaac17e689c3d90f2713a3b311aa23bcb4f` |
| hust-aia | http://faculty.hust.edu.cn/ZHULIJUN/zh_CN/index.htm | 2026-10-14 | 200 | `e345b7d6c25c070362df168e88699ba77604fc27902023f6843b65864f1924dc` |
| hust-aia | http://faculty.hust.edu.cn/bowang/zh_CN/more/2538470/jsjjgd/index.htm | 2026-10-14 | 200 | `f09b5b2860ee6307170e902f96d5e13ea922d0bbb23bdb3ae997d23cad163357` |
| hust-aia | http://faculty.hust.edu.cn/caichaocv/zh_CN/index.htm | 2026-10-14 | 200 | `de1a52136f8606023d4c64a6a060a180030df69447231b089421f12752c8677b` |
| hust-aia | http://faculty.hust.edu.cn/caozhiguo1/zh_CN/index.htm | 2026-10-14 | 200 | `0ff3818946bccbd6a20eee45a1176ea24cdc21720449c5288baa7d4c3abc8b66` |
| hust-aia | http://faculty.hust.edu.cn/cgao/zh_CN/index.htm | 2026-10-14 | 200 | `770976b2ea796dfdc23c2f8f4484668e0d6280f74c5eb7952704d550eb472c75` |
| hust-aia | http://faculty.hust.edu.cn/chengshanmei1/zh_CN/index.htm | 2026-10-14 | 200 | `2e7a5a685f01cbb191956b91de4a2fdb9d89c83cb5618c8c29124d17a7b1fc8b` |
| hust-aia | http://faculty.hust.edu.cn/chenxi10/zh_CN/index.htm | 2026-10-14 | 200 | `2a827c97d5174f432a71aa85fa0a63ebe696977cc042752fc6b609f29dc1ea88` |
| hust-aia | http://faculty.hust.edu.cn/chenxx | 2026-10-14 | 200 | `92fde4a7ab8afa261daeb54c5e66a2abc03c04ebd95298535dc4c964e781974e` |
| hust-aia | http://faculty.hust.edu.cn/chenzhong2/zh_CN/index.htm | 2026-10-14 | 200 | `368aa58cf921b75384960871adefd90eab73d53a6cabd0cc710e349f4cef67aa` |
| hust-aia | http://faculty.hust.edu.cn/chiming/zh_CN/index.htm | 2026-10-14 | 200 | `af63fd55c81ac34cdcc2e76a21c2f7935e7d8d9b40d6f4cc0a8be2257787e492` |
| hust-aia | http://faculty.hust.edu.cn/drwu/zh_CN/index.htm | 2026-10-14 | 200 | `7f2975a7bb638e1d707432e86de7a0c80cc3f421b14bebfc4f6d23dca5842469` |
| hust-aia | http://faculty.hust.edu.cn/fangzhemei/zh_CN/index.htm | 2026-10-14 | 200 | `27df640f5aad0cdcf1e5b4a616b69ea62d94dd2141e771c8c17720121cadc286` |
| hust-aia | http://faculty.hust.edu.cn/fanhuijin/zh_CN/index.htm | 2026-10-14 | 200 | `2a586efb24e5f9fe3b7bd6d14e5578be561b3c86fb22fdf8495dae531a1047fc` |
| hust-aia | http://faculty.hust.edu.cn/hanshoudong | 2026-10-14 | 200 | `1539871b0f6b2f784d43101541f97ff5bda9d2c6455feddfac6a1da00ddddca7` |
| hust-aia | http://faculty.hust.edu.cn/hlu/zh_CN/index.htm | 2026-10-14 | 200 | `aa0169033d19b7eed17d1393d48736cba75e1e671f5f972bb21cebd05906145d` |
| hust-aia | http://faculty.hust.edu.cn/huxiaoya/zh_CN/index.htm | 2026-10-14 | 200 | `15d74f9381ed0041d2643029f5872170092816e49e3307597101cc936e29a5b4` |
| hust-aia | http://faculty.hust.edu.cn/jiangjianhua/zh_CN/index.htm | 2026-10-14 | 200 | `9bcc7526d4fb8b8b335b83c7b0522db8c712b4247b353f20c4468d997a6b01ae` |
| hust-aia | http://faculty.hust.edu.cn/laijingang1/zh_CN/index/2406056/list/index.htm | 2026-10-14 | 200 | `bad08fa5488295a1019543caf7a1ed9d1d6f51a3955da9346f70ed7cf4bf9986` |
| hust-aia | http://faculty.hust.edu.cn/liuhui10/zh_CN/index.htm | 2026-10-14 | 200 | `64f10dc7ff3276841443a5232874588acd37be6122d030095d64e0dac3562158` |
| hust-aia | http://faculty.hust.edu.cn/liulei4aia/zh_CN/index.htm | 2026-10-14 | 200 | `618df68a32e46d4e9209c17cef250163a1aaf5bd0e7056890a46ea034a88d9db` |
| hust-aia | http://faculty.hust.edu.cn/liuwenzhong/zh_CN/index.htm | 2026-10-14 | 200 | `26d103d5bfe35786fb45479137aba71f59d6db959a435e4af69ea8764d93397d` |
| hust-aia | http://faculty.hust.edu.cn/liuxueming/zh_CN/more/742745/jsjjgd/ | 2026-10-14 | 200 | `d0dcca277ca6fb13f9d3e58760c32646ff025a2c8e3fbdbdf3c8baa45ea81d02` |
| hust-aia | http://faculty.hust.edu.cn/liuyang18/zh_CN/index.htm | 2026-10-14 | 200 | `585d96e8e691ae5e736cd6fbcc5631e8c6b812fa8e9f5998dec09e2e440ad3e5` |
| hust-aia | http://faculty.hust.edu.cn/liuyuliang/zh_CN/index.htm | 2026-10-14 | 200 | `092fbbc0ac57347f33982e484ca337fd0afff73566d0ffa371abbdf3f93f8a83` |
| hust-aia | http://faculty.hust.edu.cn/liuzhenyuan/zh_CN/index.htm | 2026-10-14 | 200 | `942531a8e7be865226ff9a530145fff32a97633445cf2c3b26b38ee50c9ce3c6` |
| hust-aia | http://faculty.hust.edu.cn/liwei33/zh_CN/index.htm | 2026-10-14 | 200 | `1e8649c6b8412e07b7292c450252addcaa2f38ede8d6e077d40d5fc3b5e03837` |
| hust-aia | http://faculty.hust.edu.cn/lixi2/zh_CN/index.htm | 2026-10-14 | 200 | `ee22006c584f0daf26a2b20bf3316f482d1b4dc70ed22039d70ecaae866d7a70` |
| hust-aia | http://faculty.hust.edu.cn/liyesong/zh_CN/index.htm | 2026-10-14 | 200 | `d7aeb8ac4372277c07978f71872077b7000c6f1f9b51fdacd35bb69abb329b48` |
| hust-aia | http://faculty.hust.edu.cn/liyuanzheng2/zh_CN/index.htm | 2026-10-14 | 200 | `d26d90ee91a9ab86f89e5cbe8f42328ff5b72c3de6e132ad45e1d5f82ffe0fd2` |
| hust-aia | http://faculty.hust.edu.cn/luoxin6/zh_CN/index.htm | 2026-10-14 | 200 | `d613d750cd67f4abe110e1a685da97552b14df71c2bf1792f636ebb26cec4aa2` |
| hust-aia | http://faculty.hust.edu.cn/lurenzhi/zh_CN/index.htm | 2026-10-14 | 200 | `10757fe78eed761527b12d82a378ffb9813322b47bbd4be6259c8bc4ad8deacb` |
| hust-aia | http://faculty.hust.edu.cn/maguijun1/zh_CN/index.htm | 2026-10-14 | 200 | `e6d4c19342c5c1809f2807b08dba90983012fdb88c6e9b85cc51bd2189878a8e` |
| hust-aia | http://faculty.hust.edu.cn/majie/zh_CN/index/1491001/list/index.htm | 2026-10-14 | 200 | `54a494a3836068874ef95a64f112f269a406cbb65f3cf752d9806d56511ac8ad` |
| hust-aia | http://faculty.hust.edu.cn/mmwang/zh_CN/index.htm | 2026-10-14 | 200 | `5f99984b6d4e3a1a26b93a22f3e043da3337c5f342a6d2fe2de197c6718b68bc` |
| hust-aia | http://faculty.hust.edu.cn/ouyangmin/zh_CN/index.htm | 2026-10-14 | 200 | `14735f7cbe78d4f94c9519cf58543a1353682d656b7c33c94e77e894356498f9` |
| hust-aia | http://faculty.hust.edu.cn/panlinqiang/zh_CN/index.htm | 2026-10-14 | 200 | `b9b2942c28e4a6e89fc2a8467abed36b1a890afbf35b0f5f9eda76d7ded3f3a8` |
| hust-aia | http://faculty.hust.edu.cn/penggang3/zh_CN/index.htm | 2026-10-14 | 200 | `d377c1ce10f4a32b44e0d2b6388664680730797bc034ddc8416b816f50ceaf43` |
| hust-aia | http://faculty.hust.edu.cn/qxiao/zh_CN/index.htm | 2026-10-14 | 200 | `77ba38a1847d74be03dd5bb5aebbe5c0f125a95f05a5fccb50c5c64cb9c6227e` |
| hust-aia | http://faculty.hust.edu.cn/sanghongshi/zh_CN/index.htm | 2026-10-14 | 200 | `f13728a12cd1ef7fb2d3cd3f1625cd522fe7c854750ede37e5cce940c94d900e` |
| hust-aia | http://faculty.hust.edu.cn/sangnong/zh_CN/index.htm | 2026-10-14 | 200 | `b683fcc9e39c24a6b4ddc311cac23862de5797a84c9b58c542c60659b7d27079` |
| hust-aia | http://faculty.hust.edu.cn/sunyali/zh_CN/index.htm | 2026-10-14 | 200 | `b13654360ee6b3447dc491b15b0d008216f0fc844f9b83e92d7179710ddc9f44` |
| hust-aia | http://faculty.hust.edu.cn/tairuochen/zh_CN/index.htm | 2026-10-14 | 200 | `a4079fabc909db21a1aebe6cc1f51d6683b076d447d95e02c3de92aea07d3f98` |
| hust-aia | http://faculty.hust.edu.cn/tanyihua/zh_CN/index/1529049/list/index.htm | 2026-10-14 | 200 | `d3aa8601a4ab8771a585f1b8c0d15de2bc948fb67b90ffa26eddf6d69e75a3d4` |
| hust-aia | http://faculty.hust.edu.cn/taowenbing/zh_CN/index/1485744/list/index.htm | 2026-10-14 | 200 | `389ab553315be6d20aa14c85944fe84e811b0f6bf487340640a38cfabbf3567c` |
| hust-aia | http://faculty.hust.edu.cn/ttian/zh_CN/index.htm | 2026-10-14 | 200 | `073c2400cb673484cd5284e49d9934020ef10d131a3cc23f3771b8fba12d9af1` |
| hust-aia | http://faculty.hust.edu.cn/wangjian13/zh_CN/index.htm | 2026-10-14 | 200 | `c2e693a47df7b364ad2848844671162cfa22332c1f4505c5284d61a7d44eaf46` |
| hust-aia | http://faculty.hust.edu.cn/wangxiaoping4/zh_CN/index.htm | 2026-10-14 | 200 | `2cd313e6fac5c437cd5748c715140498d1d38cbd48686dae11b26b26c4b4ba16` |
| hust-aia | http://faculty.hust.edu.cn/wangyanwu/zh_CN/index.htm | 2026-10-14 | 200 | `38fff913c6b8cffbe9e0368c324d2acdc2a31c1d21d9e78291c6eb6e6dcc5f08` |
| hust-aia | http://faculty.hust.edu.cn/wangyuehuan/zh_CN/index.htm | 2026-10-14 | 200 | `9b8904aa10ba50af559164582679141fdce9eaeb4f0f4d5db344d8b096c8b068` |
| hust-aia | http://faculty.hust.edu.cn/wangzhuo/zh_CN/index.htm | 2026-10-14 | 200 | `26d1568765078f4c5272a0d212dbc9be7c012986c22bdd59fd92a427d9d2d6c1` |
| hust-aia | http://faculty.hust.edu.cn/wanyiming/zh_CN/index.htm | 2026-10-14 | 200 | `a10880f76fa455d9d7353398a525b97b5b2cd5124b67020aa8cbd048b79711d0` |
| hust-aia | http://faculty.hust.edu.cn/xiaojiangwen/zh_CN/index.htm | 2026-10-14 | 200 | `5bd39eba17573686ccf0db182fe7cbda667504fbae4ac9d29ae614415c926982` |
| hust-aia | http://faculty.hust.edu.cn/xiaoyang/zh_CN/index/1037129/list/index.htm | 2026-10-14 | 200 | `1385e9ee3e1f275459599886d5d32de9dd0d14e86cd4ab71a9668e656de69815` |
| hust-aia | http://faculty.hust.edu.cn/xieyong/zh_CN/zhym/1526843/list/index.htm | 2026-10-14 | 200 | `4162f2c240ccda34d52a06402ea849e018651841dd6dd17a86563fdd26e1eeb7` |
| hust-aia | http://faculty.hust.edu.cn/xufei12/zh_CN/index.htm | 2026-10-14 | 200 | `abe2e5dd2e8e227ee4d53b2ccb917db5243e50eb2583a0eb041f1f931b2dd6c1` |
| hust-aia | http://faculty.hust.edu.cn/xujinbang/zh_CN/index.htm | 2026-10-14 | 200 | `ac7680dbd3592e7b4a5ddcf61e680f67dd30efcb4ca629d7d88dad7e233c9f79` |
| hust-aia | http://faculty.hust.edu.cn/yanluxin/zh_CN/index.htm | 2026-10-14 | 200 | `5a69fd84591626ab745c466313fd8472683c6aa9cc4b22b908050e71a3c9c9a9` |
| hust-aia | http://faculty.hust.edu.cn/yejie/zh_CN/index.htm | 2026-10-14 | 200 | `38d79f69c099310db3764c42231fa140faf112d80220d6c55acc5440b295471d` |
| hust-aia | http://faculty.hust.edu.cn/yelintao/zh_CN/index.htm | 2026-10-14 | 200 | `66e710abb36a7e20f5faf83ef1cd17346c7e62d377248a02fe765b6ffbdb6db6` |
| hust-aia | http://faculty.hust.edu.cn/yeyuan/zh_CN/index/752531/list/index.htm | 2026-10-14 | 200 | `6d745db87ee14b69823e177a67d642ba27cc6af021f9b0f8eecdca15217db6b5` |
| hust-aia | http://faculty.hust.edu.cn/yuezuogong/zh_CN/index.htm | 2026-10-14 | 200 | `e5a9560698300a08f86ea890c16f7f4e880cccf03fd356c531d2d1ee9302386e` |
| hust-aia | http://faculty.hust.edu.cn/zhanghao12345/zh_CN/index/2700208/list/index.htm | 2026-10-14 | 200 | `04342732951455aece0fb95dd5e2333011a9a6c607b72d76fc1c2858cd578de2` |
| hust-aia | http://faculty.hust.edu.cn/zhangpo1/zh_CN/index.htm | 2026-10-14 | 200 | `cd1e0c42de3d101597a7eb0f89a153f84a688453d4849a1a99a13783475468f8` |
| hust-aia | http://faculty.hust.edu.cn/zhaojin1/zh_CN/index.htm | 2026-10-14 | 200 | `290748049eb0ffc32d2f1bf9be732e8103093d875446f3823e856f315fce8364` |
| hust-aia | http://faculty.hust.edu.cn/zhengce123/zh_CN/index.htm | 2026-10-14 | 200 | `6e7ad214a4917d75f8a9ea98dacaee2ce95b2afb9772a092e498a77336d2ce32` |
| hust-aia | http://faculty.hust.edu.cn/zhengying2/zh_CN/index.htm | 2026-10-14 | 200 | `1eb9e4f4980e8242c7d4b3bbb5a2a5e67eb5534c1f80329b80d7eeb413f62271` |
| hust-aia | http://faculty.hust.edu.cn/zhongsheng/zh_CN/index.htm | 2026-10-14 | 200 | `510fc77c9bcdcdc7b9b0706b7f0d7b19862023fac4a1e4eead7c9a1bf2151702` |
| hust-aia | http://faculty.hust.edu.cn/zhouchunjie/zh_CN/index.htm | 2026-10-14 | 200 | `ec57b83c93aafc7395002ba252f5e5ea4a9c0c1486f4a4d71e23450ed6214682` |
| hust-aia | http://faculty.hust.edu.cn/zhoujianlan/zh_CN/index.htm | 2026-10-14 | 200 | `09bc0733497ce76d3677b9306557af421fb826064575ecced86a09585ba0adbe` |
| hust-aia | http://faculty.hust.edu.cn/zhoukaibo/zh_CN/index.htm | 2026-10-14 | 200 | `81049e2e61164962f29eb901dda869856def4f2503d477cba70cef6c903d43d1` |
| hust-aia | http://faculty.hust.edu.cn/zwliu | 2026-10-14 | 200 | `7e4f7c300196efee519efd606186b869d8564515f16a938a7b83c8ff324abb5d` |
| hust-aia | http://faculty.hust.edu.cn/zx | 2026-10-14 | 200 | `ab916aca16f6c387687a3f3bad182fe31d118c84b024729120896beb07d951e2` |
| hust-aia | http://faculty.hust.edu.cn/~bI3UNv/zh_CN/index.htm | 2026-10-14 | 200 | `efe3753c0f77d7f6deef3cc94aef0cbbc383e00844e7f2b628a54a743b3ca079` |
| hust-aia | http://faculty.hust.edu.cn/~qYFZFz/zh_CN/index.htm | 2026-10-14 | 200 | `6849f66bdf11e9d6dd7955fded679f9cd2f46ec12ca1973bd7b5216048292c05` |
| hust-aia | http://faculty.hust.edu.cn/~uQb2Mf/zh_CN/index.htm | 2026-10-14 | 200 | `7bcb7b9f5fb191f69a445ad91cb3ff25301bc72b85a671b00009ee5519731b6c` |
| hust-aia | http://faculty.hust.edu.cn/~uqaUne/zh_CN/index.htm | 2026-10-14 | 200 | `6866f43fd113c3e78bb40f66b20d02acc2e876c58d03c47fd3cb8320761f293a` |
| hust-aia | http://faculty.hust.edu.cn/~vuq6zm/zh_CN/index.htm | 2026-10-14 | 200 | `d40782341700c8e95b789bb751abd9b705b4ce44907229685679583e3f641179` |
| hust-aia | https://aia.hust.edu.cn/info/1691/10467.htm | 2026-10-14 | 200 | `e6dfc2f7b5de26c919a0138ba0150c3d7327e3ed596457334ae7c857ffbaca2f` |
| hust-aia | https://aia.hust.edu.cn/info/1691/10468.htm | 2026-10-14 | 200 | `1c70e3b33e110e9fa9d55b5513c9c78e43c45ae27256b6cc8b84f89b5056b922` |
| hust-aia | https://aia.hust.edu.cn/info/1691/10474.htm | 2026-10-14 | 200 | `b104226e25a0c34b2bb4a0c27b2b49bc4167c604f0f76d7d8fec1ac2dd866e43` |
| hust-aia | https://aia.hust.edu.cn/info/1691/10478.htm | 2026-10-14 | 200 | `188e9d63cad9fea13677cb0f91f5dbddba838d9a36d329dc489c99d212a0071f` |
| hust-aia | https://aia.hust.edu.cn/info/1691/10480.htm | 2026-10-14 | 200 | `3ad9c00ab8c510a6f972e378a49084e52ba80b83033f32d358e9b8be5f20f599` |
| hust-aia | https://aia.hust.edu.cn/info/1692/10488.htm | 2026-10-14 | 200 | `a683ac036f62982a08c19e459f51d17a5de02f42e8174870a2cc4475afebd236` |
| hust-aia | https://aia.hust.edu.cn/info/1692/10492.htm | 2026-10-14 | 200 | `8fab8d5171bdff803a46a0c56fda98285205e5997da63d95e32579ff94dcb29c` |
| hust-aia | https://aia.hust.edu.cn/info/1693/10499.htm | 2026-10-14 | 200 | `743514c6858715cf90e6226a34b8fd78b109bedd0f47229885a5cc9ea4df0e16` |
| hust-aia | https://aia.hust.edu.cn/info/1695/10507.htm | 2026-10-14 | 200 | `d3add08441fc2faa8d5af9e0237d32d602b3bbbd822ec779fad2b9a3dbac26a5` |
| hust-aia | https://aia.hust.edu.cn/info/1696/10510.htm | 2026-10-14 | 200 | `b76c2ed88fe0088b53a95b0fded35d83f002114d5e6f39e9338acc2f1c513534` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10512.htm | 2026-10-14 | 200 | `853b1b581c2e5d509159cef2dc1470cb347dc23b0321ab7b3a49b4abf48b5a6b` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10517.htm | 2026-10-14 | 200 | `165da26a3fac922bd6e6518ef59c2838b0de88e83e1573fd9938a65c2318bfb7` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10519.htm | 2026-10-14 | 200 | `9ae0152f8cffaa6b36f57dda8b0e8c9839217b1d279b9d10692b91e23937b0de` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10520.htm | 2026-10-14 | 200 | `f084e489cb010ff40de5e5a23a4db15fb9887b56986f329e13770b8f86741b6d` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10524.htm | 2026-10-14 | 200 | `d54087497a215d96d796e2debd21c78552293bd342c48f60d472e82b64cd91c3` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10526.htm | 2026-10-14 | 200 | `77e1abb33f5d87dcc1a5b932fe8f3ead255b6a9fdbbb321faba3dc0452a28507` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10527.htm | 2026-10-14 | 200 | `c59da03d857b9b3366153826a7fb5b509531ae4356ec97c0763707431ef00db6` |
| hust-aia | https://aia.hust.edu.cn/info/1697/10528.htm | 2026-10-14 | 200 | `6d185e7025ee3cb00dbc285e2509d0d7a5e374a89b2af6591d24536727c174da` |
| hust-aia | https://aia.hust.edu.cn/info/1698/10537.htm | 2026-10-14 | 200 | `9bb42d7b2b75549babbc2a227c7c47747ba480c696313e0222cc09a77d6dddc9` |
| hust-aia | https://aia.hust.edu.cn/info/1698/10539.htm | 2026-10-14 | 200 | `78a6d0cea8964005e81eec9c083a5fee249b0b6d4649c04b6bf9bb0a48816eb5` |
| hust-aia | https://aia.hust.edu.cn/info/1700/10544.htm | 2026-10-14 | 200 | `477dac5147b365dfae25336de1bac5b6cc576f5ce20ce835912eaaf47f6982fa` |
| hust-aia | https://aia.hust.edu.cn/info/1700/10557.htm | 2026-10-14 | 200 | `bf3ec60d430949e8f8af4d2d4d4c63965c2989d28337368056e7da37954cbfd4` |
| hust-aia | https://aia.hust.edu.cn/info/1700/10562.htm | 2026-10-14 | 200 | `f99d2262a7fdaf0861ee02b249a59e8ebc338befccebac4e0d8921c2d48fe507` |
| hust-aia | https://aia.hust.edu.cn/info/1700/10563.htm | 2026-10-14 | 200 | `23525b3f4cbb359b0dc3a75001decaff89ed0c82a9830fed44569bb0db1c01c4` |
| hust-aia | https://aia.hust.edu.cn/info/1700/10565.htm | 2026-10-14 | 200 | `976468e352ae4e81d21322285f8ac591a42683dde82f48fe8193cacc4c2dc90f` |
| hust-aia | https://aia.hust.edu.cn/info/1700/11060.htm | 2026-10-14 | 200 | `31194f80112ee90d208b23d96f949242a98816966f77264032fe255a047fdef4` |
| hust-aia | https://aia.hust.edu.cn/info/1701/10570.htm | 2026-10-14 | 200 | `df6073ef2363ccaaae30714aeda16ef891b47bd2677db07d03066c024e010b90` |
| hust-aia | https://aia.hust.edu.cn/info/1701/10571.htm | 2026-10-14 | 200 | `856767a1c52e1c87d75f623d4ae884b43bf82e547035ef168d773254aa7ee728` |
| hust-aia | https://aia.hust.edu.cn/info/1701/10573.htm | 2026-10-14 | 200 | `b5672ba1b649dd34e6ead87999a5ad55d637971ffbd34d7ac23c42ff1dc4ff59` |
| hust-aia | https://aia.hust.edu.cn/info/1701/10577.htm | 2026-10-14 | 200 | `a321d110826cbcf019daa603d1323101bbf7523296bc837813391e470f1bf897` |
| hust-aia | https://aia.hust.edu.cn/info/1701/10578.htm | 2026-10-14 | 200 | `bc613fb9f7247c5208bfd3d4bc3fa6db77dbe550cf4ab73422e649e9ed12d201` |
| hust-aia | https://aia.hust.edu.cn/info/1702/10581.htm | 2026-10-14 | 200 | `54115a620dc011ed14efec24a07d0c15412b813387ac858e0d43fd6a0a54af3e` |
| hust-aia | https://aia.hust.edu.cn/info/1702/10582.htm | 2026-10-14 | 200 | `e91adb1f4c797f740489a3ecee40c38bf57213336cac8df734e9f021e2e17cb2` |
| hust-aia | https://aia.hust.edu.cn/info/1702/10583.htm | 2026-10-14 | 200 | `45b97bdb4f24e631faaca546583391f94ec4529b009c2ca0e02368af37b65571` |
| hust-aia | https://aia.hust.edu.cn/szdw/xysz/axlb.htm | 2026-10-14 | 200 | `f26b586648a13ed6b17ff24c99a76afb00e1f97d3005bd067951c857d61e2347` |
| hust-aia | https://aia.hust.edu.cn/szdw/xysz/axmpyszmlb.htm | 2026-10-14 | 200 | `8e562f3997b0701c7fdf4fac2385ab8f60ab2ebfa17249d98fa88313d55b2509` |
| hust-aia | https://aia.hust.edu.cn/yxgk/xyjj.htm | 2026-10-14 | 200 | `5e3a9e1674d2e418a3f678353df3856a77b9f7cea8198a7057b2b8606c6b1cc1` |
| csu-auto | http://faculty.csu.edu.cn/XiaohongNian/zh_CN/index.htm | 2026-10-14 | 200 | `6f245330029d352ecabe7775ab415c25e0a926bb8f43a13612a9c3a56a879a12` |
| csu-auto | http://faculty.csu.edu.cn/bsun/zh_CN/index.htm | 2026-10-14 | 200 | `76e56c03d1f9e0ae6ac42f2d4b70d9e5117e92bb8fa13bacb4d1961f7d6585f5` |
| csu-auto | http://faculty.csu.edu.cn/caoyuan/zh_CN/index.htm | 2026-10-14 | 200 | `ce6a15f1e6dbd0d301858e2a32bea4928e6cec1a8a4164f6f2f6722916eeff91` |
| csu-auto | http://faculty.csu.edu.cn/cenlihui/zh_CN/index.htm | 2026-10-14 | 200 | `53bd0c2e329ac176b002fa79a28afcd0e90fc1251c857625a5316664e291e935` |
| csu-auto | http://faculty.csu.edu.cn/chenqifeng/zh_CN/index.htm | 2026-10-14 | 200 | `c1a1f7bd0d29d0bd28ea7173f5489247382bd96eaa46fb67e10dc18148870fc0` |
| csu-auto | http://faculty.csu.edu.cn/chenxiaofang/zh_CN/index.htm | 2026-10-14 | 200 | `55cd146300bd683d1ae12caf782d7675880d411e35634de59311b8af9c01d6ee` |
| csu-auto | http://faculty.csu.edu.cn/chenyougen/zh_CN/index.htm | 2026-10-14 | 200 | `1990339fb0436996ea88cb75a5a593f5259ea70dd0ade3ddd75693abd5633c57` |
| csu-auto | http://faculty.csu.edu.cn/chenzhipeng/zh_CN/index.htm | 2026-10-14 | 200 | `0958d7facf682dea55d9d8475be4610a767c106703209c0b3b20180279eae063` |
| csu-auto | http://faculty.csu.edu.cn/dongmi/zh_CN/index.htm | 2026-10-14 | 200 | `5dcbd8c0bb1db0ffd672f31e65f4f7e5c1dcf7f89c09fcba2b27516743217216` |
| csu-auto | http://faculty.csu.edu.cn/duchenglong1/zh_CN/index.htm | 2026-10-14 | 200 | `b41080db4b99212aef6b97b37eb6aca93bb765dd383ac74ee45f808593e2bd3e` |
| csu-auto | http://faculty.csu.edu.cn/gengjingxuan/zh_CN/index.htm | 2026-10-14 | 200 | `f2709b3c3f5aeac6da785f20b3d027e8be183fdd7c9a9983c2c64d58ba720abf` |
| csu-auto | http://faculty.csu.edu.cn/guigui/zh_CN/index.htm | 2026-10-14 | 200 | `2cf3a5fda98d64058d69703cd4e751b3d36bcfc92da8c49e97a723d0393dc311` |
| csu-auto | http://faculty.csu.edu.cn/guohuawu/zh_CN/index.htm | 2026-10-14 | 200 | `67c8043d54852410148af17aa06ede489c9761c43e55ac7966396819adb11738` |
| csu-auto | http://faculty.csu.edu.cn/guoyuqian/zh_CN/index.htm | 2026-10-14 | 200 | `2d311d7d31d1b533f30aa3bf6eb25a1b6382adbecf2afcf61a2e1747e52f4469` |
| csu-auto | http://faculty.csu.edu.cn/houfeifei/zh_CN/index.htm | 2026-10-14 | 200 | `ca81e475b4b27ac04374ff3d92cc2cdf1a4ce6d0a578536095064eed05dfe9ea` |
| csu-auto | http://faculty.csu.edu.cn/huangkeke/zh_CN/index.htm | 2026-10-14 | 200 | `a3fbf8b0e46d0907821a1536ce1f8535f172311f25a15bb3c4f9dd4b2f4a0fb1` |
| csu-auto | http://faculty.csu.edu.cn/huwenfeng/zh_CN/index.htm | 2026-10-14 | 200 | `3d70dcdda6fac3fa9fc6968ce692554d40494ef498e517a9f312521c00162691` |
| csu-auto | http://faculty.csu.edu.cn/huyang/zh_CN/index.htm | 2026-10-14 | 200 | `42875ec6cae8c820fd31567b9265d71b6ce323c51ef3c6d359a8618709faff14` |
| csu-auto | http://faculty.csu.edu.cn/jiangchaohui/zh_CN/index.htm | 2026-10-14 | 200 | `50e0e3e79b71e825e39eb42b75e3c947cbee2e04280449fb9023f7646e2362b7` |
| csu-auto | http://faculty.csu.edu.cn/jiangshouyong/zh_CN/index.htm | 2026-10-14 | 200 | `f0d1857a84553033b4a3f407e3ecd8dd88d5b5d2e0a59fead54fdb4796c16f3b` |
| csu-auto | http://faculty.csu.edu.cn/jie_HAN/zh_CN/index.htm | 2026-10-14 | 200 | `77ed909863a0290f232fd97f0528cbce276a07527d8f5a9b4e314aa51d5322b4` |
| csu-auto | http://faculty.csu.edu.cn/junzhang/zh_CN/index.htm | 2026-10-14 | 200 | `c4ec80850c056a59b7b621a39661c7fc996fae51c9748b07b9fa6b460c94033d` |
| csu-auto | http://faculty.csu.edu.cn/liangbuge/zh_CN/index.htm | 2026-10-14 | 200 | `1365ced0f70bb6a63f1082b47992640c1143b7dea3f9732f38df4ea7247792f9` |
| csu-auto | http://faculty.csu.edu.cn/lifanbiao/zh_CN/index.htm | 2026-10-14 | 200 | `e45e176b80422e3d84fe72f238cd98883471ac058876f6c73e3455409bf7e30d` |
| csu-auto | http://faculty.csu.edu.cn/lijuan_lan/zh_CN/index.htm | 2026-10-14 | 200 | `79ecd3507c2b6e4afa270145101de78c5ed0e6b32377fb314f06b055d27a5f50` |
| csu-auto | http://faculty.csu.edu.cn/liujianfeng/zh_CN/index.htm | 2026-10-14 | 200 | `434f73e726fcc082615d4b8f367d49a5d16de914fad8b6a38901095fb7e28101` |
| csu-auto | http://faculty.csu.edu.cn/liuyishun/zh_CN/index.htm | 2026-10-14 | 200 | `54491d3367fc152a3623cc0fd0257ba17093539f9886ee229c1ebefd1f5e8222` |
| csu-auto | http://faculty.csu.edu.cn/liyan1/zh_CN/index.htm | 2026-10-14 | 200 | `84aa094f773f082e3e45f4edb271b70534e8ddaa635ddd8abf634e4d2796c564` |
| csu-auto | http://faculty.csu.edu.cn/liyonggang/zh_CN/index.htm | 2026-10-14 | 200 | `47a3c9fedd8479f8177df51980d248bb4987e86dca3bea5ee1088343bf83460c` |
| csu-auto | http://faculty.csu.edu.cn/lizhiyong/zh_CN/index.htm | 2026-10-14 | 200 | `06f0bbb6abccbccc903c11970287501070013e9b5a6afddc479010dd5e402422` |
| csu-auto | http://faculty.csu.edu.cn/luobiao/zh_CN/index.htm | 2026-10-14 | 200 | `3ac990216ad971996e08d0cb6921ed1c60401424479e792187f01f154dde25b3` |
| csu-auto | http://faculty.csu.edu.cn/luoruiqiong/zh_CN/index.htm | 2026-10-14 | 200 | `ed237c33d22d74c92e59e6fc17841293c47f14a88de4461803592d70afa07169` |
| csu-auto | http://faculty.csu.edu.cn/michael_x_zhou/zh_CN/index.htm | 2026-10-14 | 200 | `2339b806330b6a7d883b3d4bd867fd7beba4f5e25ab2a1bcc5909135ca07a09b` |
| csu-auto | http://faculty.csu.edu.cn/pandong/zh_CN/index.htm | 2026-10-14 | 200 | `adcaf895ff2841a6b62c408866c08f5e914cfdf6c130d6877e3a9381e680153f` |
| csu-auto | http://faculty.csu.edu.cn/pengtao/zh_CN/index.htm | 2026-10-14 | 200 | `c775a6d076f5986d68241fdf21c5cc4d9a25f952b700c7881bc19b2c3f85cd6a` |
| csu-auto | http://faculty.csu.edu.cn/qiuzhifeng/zh_CN/index.htm | 2026-10-14 | 200 | `488189ecbc44002398b7f3ca749549fef5ca5cd66eac5a9d5200bd3c04224214` |
| csu-auto | http://faculty.csu.edu.cn/songcao/zh_CN/index.htm | 2026-10-14 | 200 | `fcd6c4547b1527144e8e38a80f8de8b3275674bdc0335eaf4ecf1a55fc7e55c5` |
| csu-auto | http://faculty.csu.edu.cn/tangjiawei/zh_CN/index.htm | 2026-10-14 | 200 | `e14eb1802d99cf75db1c881b2e25b6692ed751d1d262d0f2ac7b834a9827652e` |
| csu-auto | http://faculty.csu.edu.cn/tangjin/zh_CN/index.htm | 2026-10-14 | 200 | `3760542aa3d61ffe2853f3a98947c1501abab9c36174eb8893acbeb0ab4fbda8` |
| csu-auto | http://faculty.csu.edu.cn/wangchunsheng/zh_CN/index.htm | 2026-10-14 | 200 | `6167e0e17f554bd09c80e34edd65161c27c1148617af1d159aac3dcdeb4aee23` |
| csu-auto | http://faculty.csu.edu.cn/wanghaibo/zh_CN/index.htm | 2026-10-14 | 200 | `e056d41a0e7750691c4399e5dd90f460af2f6aae0c5684a6f91d4df18a8db624` |
| csu-auto | http://faculty.csu.edu.cn/wangluheng/zh_CN/index.htm | 2026-10-14 | 200 | `5ceef0f47a31eb991024d5fcf0a33406db3f0aafdba16ec59d3e28aba0e0c3e4` |
| csu-auto | http://faculty.csu.edu.cn/wangxiaoli/zh_CN/index.htm | 2026-10-14 | 200 | `b3e4047b1df9bcc26f5830df46bbde348a4f849caaf7c9d852ffc0b0ff80d6bf` |
| csu-auto | http://faculty.csu.edu.cn/wangyong/zh_CN/index.htm | 2026-10-14 | 200 | `4145038283fbdadecf332d236ed6b148e40ae0f89203feb88ebdf9466461605c` |
| csu-auto | http://faculty.csu.edu.cn/wangyun1/zh_CN/index.htm | 2026-10-14 | 200 | `af194807f7306af3081a5dfb515f755a492341078ed9a18b657c888f3cfd5db5` |
| csu-auto | http://faculty.csu.edu.cn/xieshiwen/zh_CN/index.htm | 2026-10-14 | 200 | `cf37bc511bc60262d54f645507bbf4d66c18f2c00b7fef20de8884f3deabb525` |
| csu-auto | http://faculty.csu.edu.cn/xiexiaotian/zh_CN/index.htm | 2026-10-14 | 200 | `bb4e6548372990817adf7e9f222e165a76d51de22c5a02214c41952f6c4f9e5a` |
| csu-auto | http://faculty.csu.edu.cn/xieyongfang/zh_CN/index.htm | 2026-10-14 | 200 | `4f3bc2489880f7509c45bb8347579aa2077638c479abc6918c717f816c4d4be3` |
| csu-auto | http://faculty.csu.edu.cn/xinglu/zh_CN/index.htm | 2026-10-14 | 200 | `5e98b9414189da7e96aef25cbdb5a984330cdac8604f527278a4c4d78adaf677` |
| csu-auto | http://faculty.csu.edu.cn/xionghongyun/zh_CN/index.htm | 2026-10-14 | 200 | `861d2dd0cb7cc6f5994fea7fe094d695a1f886e808e586f6537ce9476d96a2fe` |
| csu-auto | http://faculty.csu.edu.cn/xudegang/zh_CN/index.htm | 2026-10-14 | 200 | `32c876dfe1c63260b89fd53894e9c368ed860a845cd7ac7724ffc1e17de3414d` |
| csu-auto | http://faculty.csu.edu.cn/xuexiaopeng/zh_CN/index.htm | 2026-10-14 | 200 | `94b4ef95b17d467e09794963b0300bbb5491d8ad1cf2a33e29fc54d3f2738b63` |
| csu-auto | http://faculty.csu.edu.cn/xuxiaodong/zh_CN/index.htm | 2026-10-14 | 200 | `2ed80f9ecfa50b86c3610a99cee8e77f21b2a2bde2a6aeb60d35876b2f905978` |
| csu-auto | http://faculty.csu.edu.cn/yangchao/zh_CN/index.htm | 2026-10-14 | 200 | `ca491a5fca203fe7e9182192eb5a6a456bd47770ee0b9f4409687e801d530f2a` |
| csu-auto | http://faculty.csu.edu.cn/yangchunhua/zh_CN/index.htm | 2026-10-14 | 200 | `57c9510e7ea667e689b8b465d472701e1082abd58cb498a3d8fd8afed69eeda4` |
| csu-auto | http://faculty.csu.edu.cn/yangdegui/zh_CN/index.htm | 2026-10-14 | 200 | `60901d2de18ac8f10e313ddd0352fa6733b24b7853baa56f88c98a3bc7d1f940` |
| csu-auto | http://faculty.csu.edu.cn/yangjian_root/zh_CN/index.htm | 2026-10-14 | 200 | `fdb78b8ef04b6e69e8a8478a820ad3f7534e2657cc31bb6bfd8976e793cf2439` |
| csu-auto | http://faculty.csu.edu.cn/yinzeyang/zh_CN/index.htm | 2026-10-14 | 200 | `78995ba71c3982faaf2382c4bd1a5de7cae3b9072e4556403d86f94231d8390b` |
| csu-auto | http://faculty.csu.edu.cn/yuanxiaofeng/zh_CN/index.htm | 2026-10-14 | 200 | `1e8132687cda1d7c1328a698c5712d5b2a758e17210eda9e9fdb209c34a98fed` |
| csu-auto | http://faculty.csu.edu.cn/yuhaoyang/zh_CN/index.htm | 2026-10-14 | 200 | `ed9d17bd8100a2f2df97003f2de964b5b807f674c6f0a97ac5654b4382a8ec0f` |
| csu-auto | http://faculty.csu.edu.cn/yujingrong/zh_CN/index.htm | 2026-10-14 | 200 | `0f96f92757434b5297228ff8c3c13838734e66be870d002d26c477b77474692a` |
| csu-auto | http://faculty.csu.edu.cn/zhangling/zh_CN/index.htm | 2026-10-14 | 200 | `820041e6afb4adc95b82aac6ce75d2eb88bc51aba4793136e88bca101da78aa1` |
| csu-auto | http://faculty.csu.edu.cn/zhiwen_chen/zh_CN/index.htm | 2026-10-14 | 200 | `7795e8833f31648ea9dfb9177132ce79a2f6b02dee09760aeef5e8c0e713a3b4` |
| csu-auto | http://faculty.csu.edu.cn/zhoujing123/zh_CN/index.htm | 2026-10-14 | 200 | `d3942f6b82c805e7405808a435e57d0c1f763b70017a689a7a91940c4e0fb440` |
| csu-auto | http://faculty.csu.edu.cn/zhoushengchao/zh_CN/index.htm | 2026-10-14 | 200 | `4a36792ac019ad246faeeb0b70c68426f42157153b58b465fdeae28d3d9becb5` |
| csu-auto | http://faculty.csu.edu.cn/zhuhongqiu/zh_CN/index.htm | 2026-10-14 | 200 | `5b9ee53791629b89fb83b7059184c60df3c2a42370c356edd0bd5b3e65deba87` |
| csu-auto | https://faculty.csu.edu.cn/JianjunHE/zh_CN/index.htm | 2026-10-14 | 200 | `9961801fe115a91cd907a39171d1ff254ac183d5af6020ebb45cc6827da1293a` |
| csu-auto | https://faculty.csu.edu.cn/chenjianlai/zh_CN/index.htm | 2026-10-14 | 200 | `e0ba5e9c98736b0c75af06d9eadc68558658461ebd59dd4d4b67de321bb4cf00` |
| csu-auto | https://faculty.csu.edu.cn/chenliping/zh_CN/index.htm | 2026-10-14 | 200 | `98eabfc2ac1f20533f238dd1faef07b2dc925c7665dcaa49b9adc63affa3d166` |
| csu-auto | https://faculty.csu.edu.cn/chenning/zh_CN/index.htm | 2026-10-14 | 200 | `ad905af9dfff8159d6a7ea1db901e7aba376e2fee90d1117e10d76b1965a39ad` |
| csu-auto | https://faculty.csu.edu.cn/chenxianda/zh_CN/index.htm | 2026-10-14 | 200 | `63f667b4d0ed7102b5cc0444d19802ef286a4f5dafc7b093ae11f0853d1d53be` |
| csu-auto | https://faculty.csu.edu.cn/daimingzhe/zh_CN/index.htm | 2026-10-14 | 200 | `d483e566c619bf4afbdd3fea5c387d3df506114a46428fd2bb8b7771d6ff9023` |
| csu-auto | https://faculty.csu.edu.cn/dengzhenhua/zh_CN/index.htm | 2026-10-14 | 200 | `72113c4eb08e7980d94ed4dc6f9452c1b6221eb734928e28b8a9c3e8df6e7178` |
| csu-auto | https://faculty.csu.edu.cn/fanxinyu/zh_CN/index.htm | 2026-10-14 | 200 | `55058c9ff772c92bb03477997216b0a14cb3a75e010e5b6c88ef24865235c8f8` |
| csu-auto | https://faculty.csu.edu.cn/guimingzhen/zh_CN/index.htm | 2026-10-14 | 200 | `b16f74fae4925851a5a6925c308d8cdadc6d443c003ff225888a7991ed922a1e` |
| csu-auto | https://faculty.csu.edu.cn/guiweihua/zh_CN/index.htm | 2026-10-14 | 200 | `df06622781583e295013263b4bd2bad52f2de9d14beb2687707f056c678b52b0` |
| csu-auto | https://faculty.csu.edu.cn/huangpeiqiu/zh_CN/index.htm | 2026-10-14 | 200 | `73f5d07b6517ad15982a9f03db72d9ab72af2474f2bf1330e43418f28522f4c7` |
| csu-auto | https://faculty.csu.edu.cn/huangzhiwu/zh_CN/index.htm | 2026-10-14 | 200 | `27034e0ad65a3716ee79080e78f42346e48710e8b25afa2b1baf70901d6abfef` |
| csu-auto | https://faculty.csu.edu.cn/jiangcaoyang/zh_CN/index.htm | 2026-10-14 | 200 | `8f0b217cd44c81f6af79dff7143b3c4d1e59cc3b03195554dfd6197cdb84c962` |
| csu-auto | https://faculty.csu.edu.cn/jiangnan1/zh_CN/index.htm | 2026-10-14 | 200 | `450e60ca6dcc460287321fc31a1e87f2a1c2d6215a2b616a63766f0178e7ec5d` |
| csu-auto | https://faculty.csu.edu.cn/jiangxia/zh_CN/index.htm | 2026-10-14 | 200 | `cd73ad4f4508fe9f2bb513ce0a5d88dabbdd60ab6852dec5c61ffed2e600014b` |
| csu-auto | https://faculty.csu.edu.cn/leiqi/zh_CN/index.htm | 2026-10-14 | 200 | `e8c12adc4c017ef96dd1d7037e496a5df11d6508b5281aa35ebef815e05ffbba` |
| csu-auto | https://faculty.csu.edu.cn/liaoyuxin/zh_CN/index.htm | 2026-10-14 | 200 | `453961f0fb8c5965f5a26b406ada9b935b9d9aa5b6a42834acc14e595b01cd14` |
| csu-auto | https://faculty.csu.edu.cn/lifei1/zh_CN/index.htm | 2026-10-14 | 200 | `2a88d18a082019e7303669c8d1cc1ef4780df664aefaf1ac6e5b25bfd2464999` |
| csu-auto | https://faculty.csu.edu.cn/liu7y/zh_CN/index.htm | 2026-10-14 | 200 | `864a194d8998e0bccc493c41358aee797c3b9b82ecbf068a2cdd993a36fdfeea` |
| csu-auto | https://faculty.csu.edu.cn/liubo/zh_CN/index.htm | 2026-10-14 | 200 | `86cbc183a4894f5f0687bae40e34049bf101a0fc3bed3e64739462e1667b9573` |
| csu-auto | https://faculty.csu.edu.cn/liuchenliang/zh_CN/index.htm | 2026-10-14 | 200 | `796d2fddf5259a56bc19cb7ab76971d2bbe8dd02b97d795d403f30dcea47640d` |
| csu-auto | https://faculty.csu.edu.cn/liufang/zh_CN/index.htm | 2026-10-14 | 200 | `4ae3e365f3421ed3da7d92ec003b5e0940da56c0b2940a1b163a1c2c80663454` |
| csu-auto | https://faculty.csu.edu.cn/liuxianru/zh_CN/index.htm | 2026-10-14 | 200 | `a82ff071e7108d4146a90dc0d019576da8ec14b5461987f78aec053789f8813b` |
| csu-auto | https://faculty.csu.edu.cn/liuzijian/zh_CN/index.htm | 2026-10-14 | 200 | `e9a407e7140ce6f670603cd6556b1e683ae729ee04aa6d0b454ab8125be689f3` |
| csu-auto | https://faculty.csu.edu.cn/lizhonghua/zh_CN/index.htm | 2026-10-14 | 200 | `0139e377d4012c2e3b7dfb38fdbc90266954a477c9f38628d76e68d208a787a0` |
| csu-auto | https://faculty.csu.edu.cn/luoqiwu/zh_CN/index.htm | 2026-10-14 | 200 | `65b41f0d0fedd168cb78392e1eca3d325414a98d01a9b27ef836a0389070bebf` |
| csu-auto | https://faculty.csu.edu.cn/shiwei/zh_CN/index.htm | 2026-10-14 | 200 | `9d42c0543796d1635bc8c80f66979917e232c8130ca6a6222588ac3580b46b41` |
| csu-auto | https://faculty.csu.edu.cn/songdongran1/zh_CN/index.htm | 2026-10-14 | 200 | `3776f7edf288bf23071940ce23d247249e665c404809f955bc1071c8d611f463` |
| csu-auto | https://faculty.csu.edu.cn/sudan/zh_CN/index.htm | 2026-10-14 | 200 | `6f9c8037e8cf61798be43d9ceccb11a794dda7fc0d458106676153a94d1f3501` |
| csu-auto | https://faculty.csu.edu.cn/tanaina/zh_CN/index.htm | 2026-10-14 | 200 | `58513ff49bd8eda92fadb2981f45c451f97a2a78bacef89aa6d990d8b9e8590e` |
| csu-auto | https://faculty.csu.edu.cn/wangbingchuan/zh_CN/index.htm | 2026-10-14 | 200 | `323077fa7cf3b8054cfe5a89b61025aa69e0669f155007cbb3ae3c51d1dc2436` |
| csu-auto | https://faculty.csu.edu.cn/wangkai/zh_CN/index.htm | 2026-10-14 | 200 | `701b4396373bcb0ef377ecc29a6d510c7702afd5502e9332c15d748a874d5519` |
| csu-auto | https://faculty.csu.edu.cn/wangyalin/zh_CN/index.htm | 2026-10-14 | 200 | `547218a62d0bb8077d0739d630d7ec48b534d2b20f0a0071e3b6825541665cad` |
| csu-auto | https://faculty.csu.edu.cn/weicaisheng/zh_CN/index.htm | 2026-10-14 | 200 | `41cd538f0bc427a967eea691065d06ae65664e41ed885a14258266812ac1ff83` |
| csu-auto | https://faculty.csu.edu.cn/wudehao/zh_CN/index.htm | 2026-10-14 | 200 | `8880180b2b22a8b1f28282ca86ae1325abe9b5eb37c595f1b2666778b937e53a` |
| csu-auto | https://faculty.csu.edu.cn/xiebin/zh_CN/index.htm | 2026-10-14 | 200 | `70d251df60bc12cb73455eb8ae6bb60b8799b432587b00b8fab5eac8cc4df3f9` |
| csu-auto | https://faculty.csu.edu.cn/xiongsha/zh_CN/index.htm | 2026-10-14 | 200 | `c378de2ced799977ba9bfcb5eda98614ce4cc6c62e42c407b13b7350a1b57df5` |
| csu-auto | https://faculty.csu.edu.cn/yuejun/zh_CN/index.htm | 2026-10-14 | 200 | `9c764b1038cd4ba97ee33c5564e3504ead386343cda7b026df42d5a8fa3bd4ad` |
| csu-auto | https://faculty.csu.edu.cn/yulingli/zh_CN/index.htm | 2026-10-14 | 200 | `16ec014ad3846210b3cf07b546c63965eec980b1b3c189c63d874472ac4b5e7b` |
| csu-auto | https://faculty.csu.edu.cn/zhangfan/zh_CN/index.htm | 2026-10-14 | 200 | `8d178cc8f96b5c704c0c93bdd7e103e274b392f76a03d0536e13b631b5ac2713` |
| csu-auto | https://faculty.csu.edu.cn/zhanghang/zh_CN/index.htm | 2026-10-14 | 200 | `5bf05214d245b7ffa141dbd6b9578b8ba66605bde3e2ba68a9f90f7d5b53e805` |
| csu-auto | https://faculty.csu.edu.cn/zhangjunchao/zh_CN/index.htm | 2026-10-14 | 200 | `b7366caf7e88855d5bcab81c48333ae6367a2e3aa4b0190831717796d3633cf5` |
| csu-auto | https://faculty.csu.edu.cn/zhaodj/zh_CN/kyxm/15009/list/index.htm | 2026-10-14 | 200 | `acfa821a115f109c09535cc1f1f2f06afcbf325264e4a3612b208a4b10566768` |
| csu-auto | https://faculty.csu.edu.cn/zhaoyiyun/zh_CN/index.htm | 2026-10-14 | 200 | `e3bbc4c95ec88db2db0fcfbc32f31b35975affbe15eb0432e44761d2af5e4c13` |
| csu-auto | https://faculty.csu.edu.cn/zhaoyuqian/zh_CN/index.htm | 2026-10-14 | 200 | `4d7eefc112dff772488d4c4cd5999a1bdd1e7f4e6d6bcb4fee302fa8747b845a` |
| csu-auto | https://faculty.csu.edu.cn/zhoucan1/zh_CN/index.htm | 2026-10-14 | 200 | `7e8dd1cc0953fcb212433bcaf2d7706f040e9edff20278f41b88acfab1ba7b85` |
| csu-auto | https://faculty.csu.edu.cn/zouyiqun/zh_CN/index.htm | 2026-10-14 | 200 | `adc4ba2d0b5eb6ae10e2aac30670167a2fec7d3345ac7bf496958ecce94dfb2e` |
| csu-auto | https://faculty.csu.edu.cn/zuozhiyue/zh_CN/index.htm | 2026-10-14 | 200 | `0017bcc3956a41a2a198affd0406f02d918f087adc8835fbeeac253e3e0dde89` |
| csu-auto | https://soa.csu.edu.cn/szdw/jcrc.htm | 2026-10-14 | 200 | `1fc06348421c21209acffa3cc5cff77fbeacb5e7500508dcc7034a32d741e3cf` |
| csu-auto | https://soa.csu.edu.cn/xygk/xyjj.htm | 2026-10-14 | 200 | `c956d4b4f9c2178eb8a9885de8f33f9cee81c103b4518bf2e2d0ce9a5f761880` |

# 交付：学校、院系与招生政策0.4

日期：2026-10-14。基线 `3ad8fe2b3`。本地开发/验证交付，不含上线推送、实际招生资格结论或真实发信。

## 可使用的功能

- 新 `admissions.html` 学校与政策入口，目录36校42院系，与5649名导师库衔接；四条清华2027硕士样本分别为学校统考、学校推免、计算机系推免、电子信息085400统考科目。规则覆盖1校1院系，与目录覆盖分别显示。
- 按学校、院系、年度、学位和渠道查询；学校通用与院系/专业规则共同显示，明确适用范围。八类摘要带原文短片段和条款/页码定位；没整理的项目显式未知。摘要不是完整条款或个人资格判定。
- 独立公开政策YAML与来源检查JSON；原文/PDF落地页/附件链接的变化提示复核，失败保留旧成功记录，读缓存不会掩盖网络失败或推进来源日期。
- 政策→导师发现保留学校/院系和申请目标；发现/详情/通知可返回学校政策。政策→申请管理预填可审阅项目与官方参考备注，直到用户主动提交才写私人文件。
- 全站新增统一导航入口，九类页面沿用0.3视觉与手机布局；所有5649个详情重建。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| 全套Python | `python -m unittest discover -s tests`：66 passed，`cache/admissions_tests.log` |
| 新政策后端 | 8项测试，覆盖范围/出处、正文与附件指纹、缓存日期、网络失败保留、失败不被缓存清除、人工摘要不被观测改写、检查状态校验；实现前失败，修复后通过 |
| 纯JS规则 | `node tests/admissions_rules.cjs` 与 `node tests/discovery_rules.cjs` 均通过；学校通用/院系、年度/渠道、变化/失败/过期/未知分离 |
| 政策浏览器 | `python scripts/admissions_ui_check.py` 通过；临时私有存储，范围与缺失、政策到导师/项目、预填不自动写、显式提交、无效年度不扩大、未知渠道、通知院系联动、转义、变化提示、390px/file模式；`cache/admissions_ui_green.log` |
| 全站条件发现 | `python scripts/discovery_ui_check.py` 通过；9类页面导航/配色/390px不溢出及0.3流程回归；`cache/admissions_discovery_ui.log` |
| 原三组流程 | `ui_check.py` ALL GREEN，`application_ui_check.py`、`contact_ui_check.py` 均通过；`cache/admissions_old_ui.log`、`admissions_application_ui.log`、`admissions_contact_ui.log` |
| 全量重建/体检 | 5649详情重建；`python scripts/preflight.py`：0问题，4条上下文规则/5来源结构有效；`cache/admissions_build.log`、`admissions_preflight.log` |
| 实际来源 | 5个登记官方来源执行 `check_admissions.py --refresh` 均成功，与人工核对指纹一致；`cache/admissions_check_refresh.log`。学校PDF14页/院系PDF3页及官网正文已读取，院系年度与权重另做下载内容核对 |
| 数据与原文 | 5729个原data文件SHA256全部不变，仅新增 `admissions.yaml` 和 `admissions_checks.json`；所有12项短片段在对应下载原文中找到，所有核对指纹与观测一致；`cache/admissions_audit.json` |
| 独立审查 | 找出3项P2并加回归修复：缓存掩盖联网失败、非法年度变全部、通知切换后链接错院系。只读复核确认修复，无新实质问题；官网内容不是代码复核结论 |
| 视觉 | 查看桌面政策页与390px手机截图；`cache/admissions_ui/`。手机检查截图含测试用转义/变化fixture，不是真实政策变更 |

真实 `workflow.yaml`、`discovery.yaml` 未创建，旧私人记录/材料未更改。验证中的项目与人工记录均为临时fixture，没有发送邮件。只增加公开官方政策摘要和监测状态，不复制完整PDF到公开仓库。

## 来源与信息范围

调研结论、同类产品的信息字段、来源及新鲜度/完整性边界，见 `ADMISSIONS_PRODUCT_REVIEW_2026-10-14.md`。原文和定位存 `data/admissions.yaml`。取数日期不等于政策当前有效；旧原文不变也不能证明官网没有新通知。

这批是单校可核验试点，没有承诺全国最新/完整。个人成绩/语言/专业要求仍人工核对，尚未实现条款级自动核对、完整材料/截止时间导入、跨学校项目比较和后台自动更新。既有多个提醒可手工登记，时间另行通知不能自动生成截止日。

## 使用与维护

```powershell
python scripts\serve.py
# 打开 http://127.0.0.1:8000/admissions.html
python scripts\check_admissions.py --refresh
python scripts\build_site.py
python scripts\preflight.py
```

`check_admissions.py` 默认缓存优先，只有 `--refresh` 才主动回源；检查后必须重建，网页才能显示新状态。更新人工摘要需重新读原文、核对范围/例外、修改reviewed_at及指纹并通过测试；仅网络检查不能更新人工结论。后续优先扩充关注院系的学校章程+目录+报名公告+院系办法四类文件，再做用户条件逐条核对。

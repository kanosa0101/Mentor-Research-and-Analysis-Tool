# 交付：条件找导师与统一 UI 0.3

日期：2026-10-14。基础版本：`a0e60e83`（联系闭环0.2）。本次本地验证完成；未推送、未发真实邮件、未调用AI接口。

## 用户现在能完成什么

从 `discovery.html` 输入申请年度/学位/渠道、允许院校和研究关键词，逐项设置必须/偏好/不限制，查看候选与命中依据。必须条件未知默认保留，也可主动排除；排序只是已满足规则数量。研究片段带字段出处和抓取日期，资格、邮箱、年度机会、个人申请资格独立展示。

用户按官方原文核验年度招生机会和个人资格，保存来源/原文/日期，适用导师+年度+学位+渠道；超过30天按未知处理并提示复核。条件与核验备份独立于申请工作流，恢复可处理损坏索引且保留旧原始副本。静态打开可筛选，私人写入按钮禁用。

准备联系保留申请目标，项目管理预填年度/类型；否定或混合的旧项目自由文本不会自动匹配为当前渠道。通知入口定位对应院系；尚未接入的院系明确提示且显示零条，不混入其他院系。

发现、全量列表、导师详情、对比、通知、我的申请、项目材料和旧看板八类页面，共用导航、纸白/森林绿配色、标题与表单基线；所有5649个导师详情已重新生成。手机导航横向滚动，来源表在自己的容器滚动。

## 验证记录

| 检查 | 结果 / 证据 |
| --- | --- |
| Python 单元/API全套 | `python -m unittest discover -s tests`：58 passed；`cache/discovery_tests.log` |
| 新私人API | 其中6项覆盖无写入读取、非法输入不写、显式确认/出处、上下文与幂等ID、备份/损坏恢复、跨站拒绝；首次实现前返回404，修复后通过 |
| 纯规则 | `node tests/discovery_rules.cjs`：通过；必须/偏好、未知、学位不推断、年度/日期复用、跨字段短语、HTML/ml均覆盖 |
| 新浏览器流程 | `python scripts/discovery_ui_check.py`：通过；条件保存、临时人工核验、原文转义、换年度不复用、备份/刷新、目标传递、非推免不误选、未接入通知、8类UI、390px不溢出、file模式；`cache/discovery_ui_green.log` |
| 原列表/看板/对比/通知 | `python scripts/ui_check.py`：ALL GREEN，console errors NONE；`cache/discovery_old_ui.log` |
| 原申请材料/沟通/提醒 | `python scripts/application_ui_check.py`：通过，包括临时索引损坏恢复；`cache/discovery_application_ui.log` |
| 原联系闭环 | `python scripts/contact_ui_check.py`：通过，包括附件EML、显式发送确认、回复与任务、持久化和恢复；`cache/discovery_contact_ui.log` |
| 全量生成与体检 | `python scripts/build_site.py`：5649详情、36校42院系；`python scripts/preflight.py`：PROBLEMS NONE，0项；新增私人筛选结构/忽略规则检查 |
| 图片查看 | 人工查看发现页桌面与项目管理手机截图；8类手机截图在 `cache/discovery_ui/`。截图人工结论限于所查看页面，其他页面由浏览器检查 |
| 独立代码复核 | 找出并修复2项P2：跨字段虚假词组、自由文本“非推免”误选；复核后无阻断项 |
| 原数据保护 | `cache/discovery_before.json` 与当前全data逐文件SHA256：5729原文件全部一致，新增0；结果 `cache/discovery_audit.json` |

浏览器与API测试使用临时私人文件，核验原文和URL为fixture；没有把测试记录写入真实data。真实 `workflow.yaml` 和 `discovery.yaml` 尚未创建；`outreach.yaml` 保持原样。

## 范围与下一版

这是可用的条件发现和联系衔接版本。它没有自动理解研究语义、保证联系方式有效、核验真实年度名额或自动判断个人成绩条件；没有全库地区/校区/经费信息。招生通知仍是三个官方院系栏目监测试验，不能声称全国招生覆盖。

产品条件获取、同类官方产品对照与下一步顺序见 `DISCOVERY_PRODUCT_REVIEW_2026-10-14.md`；开源工作台/CRM源码对照沿用 `OPEN_SOURCE_IMPLEMENTATION_REVIEW_2026-10-14.md`。下一步优先把选定院系的当年项目规则结构化，并逐项对照用户自填条件，再扩充经过身份核验的论文与地点证据。

## 启动

```powershell
python scripts\serve.py
```

打开 `http://127.0.0.1:8000/discovery.html`。当前本地交付不含上线/推送或真实申请效果验收。
